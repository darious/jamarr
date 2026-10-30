package com.jamarr.android.playback

import android.content.ComponentName
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.SystemClock
import android.util.Log
import androidx.media3.common.MediaItem
import androidx.media3.session.MediaBrowser
import androidx.media3.session.MediaLibraryService.LibraryParams
import androidx.media3.session.SessionToken
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.common.util.concurrent.ListenableFuture
import com.jamarr.android.auth.SettingsStore
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Walks the Android Auto tree the way a car host would, over a real
 * `MediaBrowser`, against whatever server the installed app is signed in to.
 *
 * Everything else in this package runs against canned JSON. This is the one
 * check that sees real data: folders that are empty, artwork hashes that do
 * not resolve, search results that come back in the wrong groups, pages that
 * overlap. It is skipped when the app holds no session, so it costs nothing
 * on a clean CI device; sign the debug build in first to make it run.
 *
 * Findings go to logcat under [TAG] (`adb logcat -d -s LibraryWalk`), one line
 * per node with its timing, plus a summary. Assertions cover what must hold
 * for any library; the numbers are for reading.
 *
 * Limits: the test shares the app's uid, so the artwork provider's
 * per-controller grant is not exercised here, only the bytes behind it. How a
 * head unit renders any of this is not covered.
 */
@RunWith(AndroidJUnit4::class)
class SignedInLibraryWalkTest {

    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext
    private var browser: MediaBrowser? = null

    /** Query -> item count the service announced through `notifySearchResultChanged`. */
    private val announced = ConcurrentHashMap<String, Int>()
    private val latches = ConcurrentHashMap<String, CountDownLatch>()

    private data class Visit(
        val id: String,
        val depth: Int,
        val count: Int,
        val ms: Long,
        val browsable: Int,
        val playable: Int,
        val withArt: Int,
    )

    private val visits = mutableListOf<Visit>()
    private val report = StringBuilder()

    @Before
    fun requireSession() {
        val session = runBlocking { SettingsStore(context).load() }
        assumeTrue(
            "no stored session: sign the debug app in first",
            session.serverUrl.isNotBlank() && session.accessToken.isNotBlank(),
        )
        log("server=${session.serverUrl}")
    }

    @After
    fun tearDown() {
        instrumentation.runOnMainSync {
            browser?.release()
            browser = null
        }
        if (report.isNotEmpty()) Log.i(TAG, "summary\n$report")
    }

    @Test
    fun theWholeTreeAnswersWithRealData() {
        val b = connect()
        val root = onMain { b.getLibraryRoot(null) }
        assertEquals(0, root.resultCode)
        val rootExtras = root.params?.extras
        log(
            "root extras: searchSupported=${rootExtras?.getBoolean(JamarrLibraryProvider.SEARCH_SUPPORTED_KEY)} " +
                "styleSupported=${rootExtras?.getBoolean(BrowseTree.CONTENT_STYLE_SUPPORTED)}",
        )

        // Breadth first from the root, every top-level folder in full, then a
        // bounded sample deeper so artists -> albums -> tracks is seen too.
        val folders = children(b, BrowseTree.ID_ROOT, depth = 0)
        assertTrue("root listed no folders", folders.isNotEmpty())
        assertTrue(
            "signed in, yet the root offered the sign-in placeholder",
            folders.none { it.mediaId == JamarrLibraryProvider.ID_SIGN_IN },
        )

        val queue = ArrayDeque<Pair<MediaItem, Int>>()
        folders.forEach { queue += it to 1 }
        val sampledPlayables = mutableListOf<MediaItem>()
        val artwork = linkedSetOf<Uri>()
        var visited = 0
        while (queue.isNotEmpty() && visited < MAX_NODES) {
            val (node, depth) = queue.removeFirst()
            if (node.mediaMetadata.isBrowsable != true) continue
            val kids = children(b, node.mediaId, depth)
            visited++
            kids.mapNotNull { it.mediaMetadata.artworkUri }.forEach { artwork += it }
            kids.filter { it.mediaMetadata.isPlayable == true && it.mediaMetadata.isBrowsable != true }
                .take(1).forEach { sampledPlayables += it }
            if (depth < MAX_DEPTH) {
                kids.filter { it.mediaMetadata.isBrowsable == true }
                    .take(if (depth == 1) SAMPLE_PER_FOLDER else 1)
                    .forEach { queue += it to depth + 1 }
            }
        }

        // Every node answered successfully with well-formed, unique rows.
        val failed = visits.filter { it.count < 0 }
        assertTrue("nodes that errored: ${failed.map { it.id }}", failed.isEmpty())

        checkPaging(b)
        checkArtwork(artwork)
        checkItems(b, sampledPlayables)
        checkSearch(b, folders)

        report.append("nodes=${visits.size} ")
            .append("empty=${visits.count { it.count == 0 }} ")
            .append("slowest=${visits.maxByOrNull { it.ms }?.let { "${it.id} ${it.ms}ms" }} ")
            .append("artworkUris=${artwork.size} schemes=${artwork.groupingBy { it.scheme }.eachCount()}\n")
    }

    // ---- browse -------------------------------------------------------------

    private fun children(b: MediaBrowser, parentId: String, depth: Int): List<MediaItem> {
        val started = SystemClock.elapsedRealtime()
        val result = onMain { b.getChildren(parentId, 0, PAGE_SIZE, null) }
        val ms = SystemClock.elapsedRealtime() - started
        if (result.resultCode != 0) {
            visits += Visit(parentId, depth, -1, ms, 0, 0, 0)
            log("$parentId depth=$depth ERROR code=${result.resultCode} ${ms}ms")
            return emptyList()
        }
        val items = result.value.orEmpty()
        val ids = items.map { it.mediaId }
        assertEquals("duplicate ids under $parentId: $ids", ids.size, ids.toSet().size)
        items.forEach {
            assertTrue("blank id under $parentId", it.mediaId.isNotBlank())
            assertTrue("blank title for ${it.mediaId} under $parentId", !it.mediaMetadata.title.isNullOrBlank())
            assertTrue(
                "${it.mediaId} is neither browsable nor playable",
                it.mediaMetadata.isBrowsable == true || it.mediaMetadata.isPlayable == true,
            )
        }
        val v = Visit(
            id = parentId,
            depth = depth,
            count = items.size,
            ms = ms,
            browsable = items.count { it.mediaMetadata.isBrowsable == true },
            playable = items.count { it.mediaMetadata.isPlayable == true },
            withArt = items.count { it.mediaMetadata.artworkUri != null },
        )
        visits += v
        val groups = items.mapNotNull { it.mediaMetadata.extras?.getString(GROUP_TITLE_KEY) }.distinct()
        log(
            "$parentId depth=$depth n=${v.count} browsable=${v.browsable} playable=${v.playable} " +
                "art=${v.withArt} ${v.ms}ms" + (if (groups.isNotEmpty()) " groups=$groups" else "") +
                " first=${items.firstOrNull()?.mediaMetadata?.title?.let { "\"$it\"" }}",
        )
        return items
    }

    /** A full first page must be followed by pages that do not repeat it. */
    private fun checkPaging(b: MediaBrowser) {
        val full = visits.filter { it.count == PAGE_SIZE && it.depth <= 1 }.map { it.id }
        log("paging candidates (full first page): $full")
        for (id in full) {
            val seen = linkedSetOf<String>()
            var page = 0
            var pages = 0
            var total = 0
            while (page < MAX_PAGES) {
                val started = SystemClock.elapsedRealtime()
                val result = onMain { b.getChildren(id, page, PAGE_SIZE, null) }
                val ms = SystemClock.elapsedRealtime() - started
                assertEquals("page $page of $id failed", 0, result.resultCode)
                val items = result.value.orEmpty()
                val overlap = items.map { it.mediaId }.filter { !seen.add(it) }
                assertTrue("page $page of $id repeats ${overlap.take(3)}", overlap.isEmpty())
                total += items.size
                pages++
                log("$id page=$page n=${items.size} ${ms}ms")
                if (items.size < PAGE_SIZE) break
                page++
            }
            report.append("$id: $total rows over $pages pages" + (if (pages == MAX_PAGES) " (capped)" else "") + "\n")
        }
    }

    // ---- artwork ------------------------------------------------------------

    /** The provider-served images behind the browse rows actually decode. */
    private fun checkArtwork(uris: Set<Uri>) {
        val content = uris.filter { it.scheme == "content" }
        val authority = ArtworkContentProvider.baseUri(context).authority
        val foreign = content.filter { it.authority != authority }
        assertTrue("browse rows point at another authority: ${foreign.take(3)}", foreign.isEmpty())
        val sample = content.filter { it.path?.startsWith("/art/") == true }.take(ART_SAMPLE) +
            content.filter { it.path?.startsWith("/grid/") == true }.take(2)
        var ok = 0
        for (uri in sample) {
            val started = SystemClock.elapsedRealtime()
            val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            val opened = try {
                context.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, opts) }
                true
            } catch (e: Exception) {
                log("art $uri failed: $e")
                false
            }
            val ms = SystemClock.elapsedRealtime() - started
            if (opened && opts.outWidth > 0) {
                ok++
                log("art ${uri.lastPathSegment?.take(12)} ${opts.outWidth}x${opts.outHeight} ${ms}ms")
            } else {
                log("art $uri did not decode (${ms}ms)")
            }
        }
        report.append("artwork decoded $ok/${sample.size} sampled content uris\n")
        if (sample.isNotEmpty()) {
            assertTrue("no sampled artwork decoded", ok > 0)
            assertTrue("artwork decode failures: ${sample.size - ok}/${sample.size}", ok == sample.size)
        }
    }

    // ---- getItem ------------------------------------------------------------

    /** Playing from a search result or a resumed queue starts with getItem. */
    private fun checkItems(b: MediaBrowser, items: List<MediaItem>) {
        var ok = 0
        for (item in items.take(ITEM_SAMPLE)) {
            val result = onMain { b.getItem(item.mediaId) }
            val got = result.value
            if (result.resultCode == 0 && got != null) {
                ok++
                log("getItem ${item.mediaId} -> \"${got.mediaMetadata.title}\" playable=${got.mediaMetadata.isPlayable}")
            } else {
                log("getItem ${item.mediaId} failed code=${result.resultCode}")
            }
        }
        report.append("getItem $ok/${items.take(ITEM_SAMPLE).size}\n")
        assertEquals("getItem failures", items.take(ITEM_SAMPLE).size, ok)
    }

    // ---- search -------------------------------------------------------------

    private fun checkSearch(b: MediaBrowser, folders: List<MediaItem>) {
        // A name that is certainly in this library: the first artist the tree
        // itself listed, from whichever artist folder had one.
        val artistFolders = listOf(BrowseTree.ID_RECENT_ARTISTS, BrowseTree.ID_FAV_ARTISTS, BrowseTree.ID_HISTORY_ARTISTS)
        val known = artistFolders.firstNotNullOfOrNull { id ->
            onMain { b.getChildren(id, 0, PAGE_SIZE, null) }.value.orEmpty()
                .firstOrNull { it.mediaId.startsWith(BrowseTree.PREFIX_ARTIST) }
                ?.mediaMetadata?.title?.toString()
        }
        log("search: known artist = $known (folders: ${folders.map { it.mediaId }})")

        val queries = buildList {
            if (known != null) {
                add(known)
                known.split(' ').firstOrNull { it.length >= 3 }?.takeIf { it != known }?.let { add(it) }
            }
            add("the")
            add("zq")        // minimum length, almost certainly nothing
            add("x")         // below minimum length: must be empty, not an error
        }

        for (q in queries) {
            val latch = CountDownLatch(1)
            latches[q] = latch
            val started = SystemClock.elapsedRealtime()
            val ack = onMain { b.search(q, null) }
            assertEquals("search \"$q\" was not accepted", 0, ack.resultCode)
            val notified = latch.await(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            val result = onMain { b.getSearchResult(q, 0, SEARCH_PAGE, null) }
            val ms = SystemClock.elapsedRealtime() - started
            assertEquals("search page for \"$q\" failed", 0, result.resultCode)
            val items = result.value.orEmpty()
            val byGroup = items.groupingBy { it.mediaMetadata.extras?.getString(GROUP_TITLE_KEY) ?: "(none)" }.eachCount()
            log(
                "search \"$q\": notified=$notified announced=${announced[q]} n=${items.size} " +
                    "groups=$byGroup ${ms}ms first=${items.firstOrNull()?.mediaMetadata?.title?.let { "\"$it\"" }}",
            )
            report.append("search \"$q\": ${items.size} rows $byGroup\n")

            assertTrue("no notifySearchResultChanged for \"$q\"", notified)
            assertEquals("announced count disagrees with the page for \"$q\"", announced[q], items.size)
            val ids = items.map { it.mediaId }
            assertEquals("duplicate ids in search \"$q\"", ids.size, ids.toSet().size)
            assertTrue("ungrouped rows in search \"$q\"", items.all { it.mediaMetadata.extras?.getString(GROUP_TITLE_KEY) != null })
            val order = items.map { it.mediaMetadata.extras?.getString(GROUP_TITLE_KEY) }
            assertEquals("groups interleaved in search \"$q\": $order", order.distinct().flatMap { g -> order.filter { it == g } }, order)

            if (q == known) {
                assertTrue(
                    "searching the artist's own name did not return the artist: $items",
                    items.any {
                        it.mediaMetadata.extras?.getString(GROUP_TITLE_KEY) == JamarrLibraryProvider.GROUP_ARTISTS &&
                            it.mediaMetadata.title.toString().equals(known, ignoreCase = true)
                    },
                )
            }
            if (q.length < JamarrLibraryProvider.MIN_SEARCH_LENGTH) {
                assertEquals("short query must return nothing", 0, items.size)
            }
        }
    }

    // ---- plumbing -----------------------------------------------------------

    private fun connect(): MediaBrowser {
        val connected = onMain {
            val token = SessionToken(context, ComponentName(context, JamarrPlaybackService::class.java))
            MediaBrowser.Builder(context, token)
                .setListener(object : MediaBrowser.Listener {
                    override fun onSearchResultChanged(
                        browser: MediaBrowser,
                        query: String,
                        itemCount: Int,
                        params: LibraryParams?,
                    ) {
                        announced[query] = itemCount
                        latches[query]?.countDown()
                    }
                })
                .buildAsync()
        }
        browser = connected
        return connected
    }

    private fun <T> onMain(block: () -> ListenableFuture<T>): T {
        lateinit var future: ListenableFuture<T>
        instrumentation.runOnMainSync { future = block() }
        return future.get(TIMEOUT_SECONDS, TimeUnit.SECONDS)
    }

    private fun log(line: String) {
        Log.i(TAG, line)
    }

    companion object {
        private const val TAG = "LibraryWalk"
        private const val TIMEOUT_SECONDS = 30L
        private const val PAGE_SIZE = 50
        private const val SEARCH_PAGE = 100
        private const val MAX_NODES = 40
        private const val MAX_DEPTH = 3
        private const val MAX_PAGES = 6
        private const val SAMPLE_PER_FOLDER = 2
        private const val ART_SAMPLE = 12
        private const val ITEM_SAMPLE = 6
        private const val GROUP_TITLE_KEY = "android.media.browse.CONTENT_STYLE_GROUP_TITLE_HINT"
    }
}
