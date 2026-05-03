package com.jamarr.android.playback

import android.app.PendingIntent
import android.content.Intent
import android.net.Uri
import androidx.annotation.OptIn
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.Timeline
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.datasource.ResolvingDataSource
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.MediaLibraryService
import androidx.media3.session.MediaSession
import com.jamarr.android.MainActivity
import com.jamarr.android.auth.SettingsStore
import com.jamarr.android.auth.TokenHolder
import com.jamarr.android.data.JamarrApiClient
import com.jamarr.android.data.JamarrCookieJar
import com.jamarr.android.data.SearchTrack
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout

@OptIn(markerClass = [UnstableApi::class])
class JamarrPlaybackService : MediaLibraryService() {
    private var librarySession: MediaLibrarySession? = null

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val serverUrl = AtomicReference("")

    // Resolved /api/stream/<id>?token=<jwt> URLs. The stream token expires
    // (default 300s server-side) so cached URLs must not outlive the token,
    // otherwise ExoPlayer reopens with a stale token and gets 401.
    private data class CachedStreamUrl(val url: String, val expiresAtMs: Long)
    private val streamUrlCache = ConcurrentHashMap<Long, CachedStreamUrl>()
    private lateinit var settingsStore: SettingsStore
    private lateinit var tokenHolder: TokenHolder
    private lateinit var apiClient: JamarrApiClient
    private lateinit var libraryProvider: JamarrLibraryProvider

    override fun onCreate() {
        super.onCreate()

        settingsStore = SettingsStore(applicationContext)
        tokenHolder = TokenHolder()
        val cookieJar = JamarrCookieJar(settingsStore)
        apiClient = JamarrApiClient(
            tokenHolder = tokenHolder,
            cookieJar = cookieJar,
            onTokenRefreshed = { token -> settingsStore.saveAccessToken(token) },
            onRefreshFailed = { settingsStore.clearAccessToken() },
        )

        val clientId = runBlocking {
            val saved = settingsStore.load()
            serverUrl.set(saved.serverUrl)
            tokenHolder.set(saved.accessToken)
            cookieJar.prime()
            settingsStore.getClientId()
        }

        serviceScope.launch {
            settingsStore.observeSession().collectLatest { session ->
                serverUrl.set(session.serverUrl)
                tokenHolder.set(session.accessToken)
            }
        }

        val httpFactory = DefaultHttpDataSource.Factory()
        val resolvingFactory = ResolvingDataSource.Factory(httpFactory) { spec ->
            resolveDataSpec(spec)
        }
        val mediaSourceFactory = DefaultMediaSourceFactory(this)
            .setDataSourceFactory(resolvingFactory)

        val loadControl = DefaultLoadControl.Builder()
            .setBufferDurationsMs(
                /* minBufferMs */ 30_000,
                /* maxBufferMs */ 60_000,
                /* backBufferMs */ 2_500,
                /* retainBackBufferMs */ 5_000,
            )
            .build()

        val player = ExoPlayer.Builder(this)
            .setMediaSourceFactory(mediaSourceFactory)
            .setLoadControl(loadControl)
            .build()

        serviceScope.launch(Dispatchers.Main) {
            var lastProgressReport = 0L
            var lastReportedQueueKey: String? = null
            var lastReportedMediaId: String? = null
            while (true) {
                val url = serverUrl.get()
                if (url.isNotBlank() && clientId.isNotBlank()) {
                    val qKey = queueKey(player)
                    if (qKey != null && qKey != lastReportedQueueKey) {
                        lastReportedQueueKey = qKey
                        val tracks = queueSearchTracks(player)
                        if (tracks.isNotEmpty()) {
                            apiClient.reportQueue(url, clientId, tracks, player.currentMediaItemIndex)
                        }
                        for (i in 0 until player.mediaItemCount) {
                            val tid = extractTrackId(player.getMediaItemAt(i).mediaId)
                            if (tid > 0L && !isStreamUrlFresh(tid)) {
                                serviceScope.launch(Dispatchers.IO) {
                                    runCatching {
                                        withTimeout(5000) {
                                            apiClient.streamUrl(url, tokenHolder.get(), tid)
                                        }
                                    }.onSuccess { resolved ->
                                        streamUrlCache[tid] = CachedStreamUrl(
                                            url = resolved,
                                            expiresAtMs = System.currentTimeMillis() + STREAM_URL_TTL_MS,
                                        )
                                    }
                                }
                            }
                        }
                    }
                    val mediaId = player.currentMediaItem?.mediaId
                    if (mediaId != null && mediaId != lastReportedMediaId) {
                        lastReportedMediaId = mediaId
                        apiClient.reportIndex(url, clientId, player.currentMediaItemIndex)
                    }
                    val now = System.currentTimeMillis()
                    if (player.isPlaying && now - lastProgressReport >= 5000) {
                        lastProgressReport = now
                        apiClient.reportProgress(
                            url, clientId,
                            positionSeconds = player.currentPosition / 1000.0,
                            isPlaying = true,
                        )
                    }
                }
                delay(500)
            }
        }

        val sessionIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

        libraryProvider = JamarrLibraryProvider(
            apiClient = apiClient,
            serverUrlProvider = { serverUrl.get() },
            tokenProvider = { tokenHolder.get() },
            scope = serviceScope,
        )

        librarySession = MediaLibrarySession.Builder(this, player, libraryProvider.callback)
            .setSessionActivity(sessionIntent)
            .build()
    }

    private fun resolveDataSpec(spec: DataSpec): DataSpec {
        val uri = spec.uri
        if (uri.scheme != JAMARR_SCHEME) return spec
        val trackId = uri.lastPathSegment?.toLongOrNull()
            ?: throw IOException("Missing track id in $uri")
        val server = serverUrl.get()
        if (server.isBlank()) throw IOException("Jamarr server URL not set")

        val now = System.currentTimeMillis()
        streamUrlCache[trackId]?.let { cached ->
            if (cached.expiresAtMs > now) {
                return spec.withUri(Uri.parse(cached.url))
            }
            streamUrlCache.remove(trackId)
        }

        val resolved = runBlocking {
            withTimeout(5000) {
                apiClient.streamUrl(server, tokenHolder.get(), trackId)
            }
        }
        streamUrlCache[trackId] = CachedStreamUrl(
            url = resolved,
            expiresAtMs = System.currentTimeMillis() + STREAM_URL_TTL_MS,
        )
        return spec.withUri(Uri.parse(resolved))
    }

    private fun isStreamUrlFresh(trackId: Long): Boolean {
        val cached = streamUrlCache[trackId] ?: return false
        return cached.expiresAtMs > System.currentTimeMillis()
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaLibrarySession? {
        return librarySession
    }

    override fun onDestroy() {
        librarySession?.run {
            player.release()
            release()
        }
        librarySession = null
        serviceScope.cancel()
        super.onDestroy()
    }

    private fun queueKey(player: Player): String? {
        val count = player.mediaItemCount
        if (count == 0) return null
        return (0 until count).joinToString(",") { player.getMediaItemAt(it).mediaId }
    }

    private fun queueSearchTracks(player: Player): List<SearchTrack> {
        val count = player.mediaItemCount
        if (count == 0) return emptyList()
        return (0 until count).map { i ->
            val item = player.getMediaItemAt(i)
            val md = item.mediaMetadata
            SearchTrack(
                id = extractTrackId(item.mediaId),
                title = md.title?.toString().orEmpty(),
                artist = md.artist?.toString(),
                album = md.albumTitle?.toString(),
            )
        }
    }

    private fun extractTrackId(mediaId: String): Long {
        return if (mediaId.startsWith("track:")) {
            mediaId.removePrefix("track:").substringBefore("|").toLongOrNull() ?: 0L
        } else {
            mediaId.toLongOrNull() ?: 0L
        }
    }

    companion object {
        const val JAMARR_SCHEME = "jamarr"

        // Server default STREAM_TOKEN_TTL_SECONDS=300. Cache for 240s so a
        // pre-warmed URL still has ~60s of validity when ExoPlayer opens it.
        const val STREAM_URL_TTL_MS = 240_000L

        fun trackUri(trackId: Long): Uri =
            Uri.parse("$JAMARR_SCHEME://track/$trackId")
    }
}
