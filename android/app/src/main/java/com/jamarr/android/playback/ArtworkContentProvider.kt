package com.jamarr.android.playback

import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.util.Log
import com.jamarr.android.JamarrApplication
import com.jamarr.android.auth.SettingsStore
import com.jamarr.android.data.JamarrApiClient
import java.io.File
import java.io.FileNotFoundException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Semaphore
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Serves album art to the Android Auto host over `content://` URIs.
 *
 * Why: the host app loads browse icons itself. It does not permit cleartext,
 * so an `http://` LAN URL silently fails there, and it cannot read this app's
 * private files, so downloaded art was unreachable offline. The provider
 * used to embed bitmap bytes in every browse item for both cases, which
 * meant fetching and decoding a page of art before the page could show.
 * Now browse items carry a content URI and the host asks for each image
 * when it needs it; nothing is loaded for rows the car never scrolls to.
 *
 * Access: not exported. The playback service grants read permission on the
 * authority (prefix grant) to each controller it accepts, so only those
 * packages — and this app — can open a URI. The grammar ([ArtworkUris])
 * admits only artwork hashes: no paths, no URLs, no sizes.
 *
 * Sources, in order: the offline artwork store (downloads), this provider's
 * own disk cache, then one fetch from the server at [ArtworkPolicy.ART_SIZE_PX]
 * bounded by [FETCH_CONCURRENCY] and single-flighted per hash. Files are
 * published by temp-file + rename (same rule as `OfflineArtworkStore`), so a
 * reader never sees a partial JPEG. The cache is trimmed oldest-first past
 * [CACHE_CAP_BYTES]. Grids are composited on demand and cached the same way.
 */
class ArtworkContentProvider : ContentProvider() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val serverUrl = AtomicReference<String?>(null)
    private val fetchGate = Semaphore(FETCH_CONCURRENCY)
    private val inFlight = ConcurrentHashMap<String, Any>()
    private val http = JamarrApiClient()

    override fun onCreate(): Boolean = true

    override fun getType(uri: Uri): String? =
        if (ArtworkUris.parse(uri.pathSegments) != null) "image/jpeg" else null

    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
        if (mode != "r") throw FileNotFoundException("read-only")
        val request = ArtworkUris.parse(uri.pathSegments)
            ?: throw FileNotFoundException("not an artwork uri")
        val ctx = context ?: throw FileNotFoundException("no context")
        val file = when (request) {
            is ArtworkUris.Request.Art -> artFile(ctx, request.sha1)
            is ArtworkUris.Request.Grid -> gridFile(ctx, request.sha1s)
        } ?: throw FileNotFoundException("no artwork for $uri")
        return ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
    }

    // ----- lookups --------------------------------------------------------

    private fun artFile(ctx: Context, sha: String): File? {
        app(ctx)?.artworkStore?.existing(sha)?.let { return it }
        val cached = File(cacheDir(ctx), "$sha.jpg")
        if (cached.isFile && cached.length() > 0) return cached
        // Single flight per hash: whoever holds the lock fetches *and
        // publishes*; everyone queued behind it then finds the file. Releasing
        // between the two would let a second caller fetch the same bytes.
        val lock = inFlight.getOrPut(sha) { Any() }
        try {
            synchronized(lock) {
                if (cached.isFile && cached.length() > 0) return cached
                val bytes = fetch(ctx, sha) ?: return null
                return publish(ctx, cached, bytes)
            }
        } finally {
            inFlight.remove(sha, lock)
        }
    }

    private fun gridFile(ctx: Context, shas: List<String>): File? {
        val cached = File(cacheDir(ctx), ArtworkUris.gridCacheName(shas) + ".jpg")
        if (cached.isFile && cached.length() > 0) return cached
        val tiles = shas.mapNotNull { sha -> artFile(ctx, sha)?.let { f -> runCatching { f.readBytes() }.getOrNull() } }
        val composed = ArtworkGrid.compose(tiles, ArtworkPolicy.ART_SIZE_PX) ?: return null
        return publish(ctx, cached, composed)
    }

    /** One bounded, timed fetch from the server; null on any failure. */
    private fun fetch(ctx: Context, sha: String): ByteArray? {
        val server = currentServerUrl(ctx) ?: return null
        if (!fetchGate.tryAcquire(FETCH_WAIT_MS, java.util.concurrent.TimeUnit.MILLISECONDS)) return null
        try {
            return runBlocking {
                withTimeoutOrNull(FETCH_TIMEOUT_MS) {
                    http.fetchArtworkBytes(server, sha, ArtworkPolicy.ART_SIZE_PX)
                }
            }?.takeIf { it.isNotEmpty() }
        } finally {
            fetchGate.release()
        }
    }

    private fun publish(ctx: Context, target: File, bytes: ByteArray): File? = runCatching {
        val dir = cacheDir(ctx).apply { mkdirs() }
        val tmp = File.createTempFile(target.nameWithoutExtension + ".", ".tmp", dir)
        try {
            tmp.writeBytes(bytes)
            if (!tmp.renameTo(target)) {
                tmp.delete()
                // Another writer won; its file is just as good.
                return@runCatching target.takeIf { it.isFile && it.length() > 0 }
            }
        } catch (e: Exception) {
            tmp.delete()
            throw e
        }
        trim(dir)
        target
    }.onFailure { Log.w(TAG, "could not publish ${target.name}", it) }.getOrNull()

    /** Oldest files go first once the cache is over its cap. */
    private fun trim(dir: File) {
        val files = dir.listFiles { f -> f.isFile && f.name.endsWith(".jpg") } ?: return
        var total = files.sumOf { it.length() }
        if (total <= CACHE_CAP_BYTES) return
        for (f in files.sortedBy { it.lastModified() }) {
            if (total <= CACHE_CAP_BYTES * 3 / 4) break
            total -= f.length()
            f.delete()
        }
    }

    private fun cacheDir(ctx: Context): File = File(ctx.cacheDir, CACHE_DIR)

    private fun app(ctx: Context): JamarrApplication? = ctx.applicationContext as? JamarrApplication

    /** The stored server URL, read once (bounded wait) and then kept current. */
    private fun currentServerUrl(ctx: Context): String? {
        serverUrl.get()?.let { return it.takeIf { u -> u.isNotBlank() } }
        val store = SettingsStore(ctx.applicationContext)
        val first = runBlocking { withTimeoutOrNull(SETTINGS_WAIT_MS) { store.observeSession().first().serverUrl } }
        if (serverUrl.compareAndSet(null, first.orEmpty())) {
            scope.launch { store.observeSession().collect { serverUrl.set(it.serverUrl) } }
        }
        return serverUrl.get()?.takeIf { it.isNotBlank() }
    }

    // ----- unsupported ---------------------------------------------------

    override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor? = null

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null

    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0

    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int = 0

    companion object {
        private const val TAG = "ArtworkContentProvider"
        const val AUTHORITY_SUFFIX = ".artwork"
        private const val CACHE_DIR = "auto_art"
        const val CACHE_CAP_BYTES = 48L * 1024 * 1024
        const val FETCH_CONCURRENCY = 4
        const val FETCH_TIMEOUT_MS = 10_000L
        const val FETCH_WAIT_MS = 8_000L
        const val SETTINGS_WAIT_MS = 2_000L

        fun authority(ctx: Context): String = ctx.packageName + AUTHORITY_SUFFIX

        fun baseUri(ctx: Context): Uri = Uri.Builder().scheme("content").authority(authority(ctx)).build()

        fun artUri(ctx: Context, sha1: String): Uri = baseUri(ctx).buildUpon().path(ArtworkUris.artPath(sha1)).build()

        fun gridUri(ctx: Context, sha1s: List<String>): Uri? =
            ArtworkUris.gridPath(sha1s)?.let { baseUri(ctx).buildUpon().path(it).build() }
    }
}
