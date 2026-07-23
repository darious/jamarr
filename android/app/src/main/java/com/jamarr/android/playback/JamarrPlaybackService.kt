package com.jamarr.android.playback

import android.app.PendingIntent
import android.content.Intent
import android.net.Uri
import android.util.Log
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
import com.jamarr.android.JamarrApplication
import com.jamarr.android.MainActivity
import com.jamarr.android.auth.SettingsStore
import com.jamarr.android.auth.TokenHolder
import com.jamarr.android.data.JamarrApiClient
import com.jamarr.android.data.SearchTrack
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout

@OptIn(markerClass = [UnstableApi::class])
class JamarrPlaybackService : MediaLibraryService() {
    private var librarySession: MediaLibrarySession? = null

    // Report/telemetry work runs here. Without a handler an uncaught throw in a
    // root coroutine reaches the thread's default handler and kills the process,
    // so any API failure during playback would crash the app.
    private val serviceExceptionHandler = CoroutineExceptionHandler { _, throwable ->
        Log.w(TAG, "Playback service coroutine failed", throwable)
    }
    private val serviceScope =
        CoroutineScope(SupervisorJob() + Dispatchers.IO + serviceExceptionHandler)
    private val serverUrl = AtomicReference("")

    // Resolved /api/stream/<id>?token=<jwt> URLs. The stream token expires
    // (default 300s server-side) so cached URLs must not outlive the token,
    // otherwise ExoPlayer reopens with a stale token and gets 401.
    private data class CachedStreamUrl(
        val url: String,
        val quality: String,
        val qualityLabel: String,
        val originalQualityLabel: String,
        val expiresAtMs: Long,
    )
    private val streamUrlCache = ConcurrentHashMap<String, CachedStreamUrl>()
    private val activeQuality = AtomicReference("original")
    private val adaptiveQualityPolicy = AdaptiveStreamQualityPolicy()
    private val downgradeInFlight = AtomicBoolean(false)
    private lateinit var settingsStore: SettingsStore
    private lateinit var tokenHolder: TokenHolder
    private lateinit var apiClient: JamarrApiClient
    private lateinit var libraryProvider: JamarrLibraryProvider

    override fun onCreate() {
        super.onCreate()

        val app = applicationContext as JamarrApplication
        tokenHolder = app.tokenHolder
        val cookieJar = app.cookieJar
        settingsStore = SettingsStore(applicationContext)

        val authFailed = AtomicBoolean(false)

        apiClient = JamarrApiClient(
            tokenHolder = tokenHolder,
            cookieJar = cookieJar,
            onTokenRefreshed = { token -> settingsStore.saveAccessToken(token) },
            onRefreshFailed = {
                settingsStore.clearAccessToken()
                authFailed.set(true)
            },
            onForceLogout = {
                settingsStore.clearAccessToken()
                cookieJar.clear()
                authFailed.set(true)
            },
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

        player.addListener(object : Player.Listener {
            override fun onPlaybackStateChanged(playbackState: Int) {
                if (playbackState == Player.STATE_BUFFERING && player.playWhenReady) {
                    recordBufferingEvent(player)
                }
            }
        })

        serviceScope.launch(Dispatchers.Main) {
            var lastProgressReport = 0L
            var lastReportedQueueKey: String? = null
            var lastReportedMediaId: String? = null
            var lastPrewarmedQueueKey: String? = null
            var nextReportAttemptMs = 0L
            while (true) {
                val url = serverUrl.get()
                val token = tokenHolder.get()
                if (url.isNotBlank() && clientId.isNotBlank() && token.isNotBlank() && !authFailed.get()) {
                    val qKey = queueKey(player)
                    val canReport = System.currentTimeMillis() >= nextReportAttemptMs
                    if (qKey != null && qKey != lastReportedQueueKey && canReport) {
                        val tracks = queueSearchTracks(player)
                        // Reporting is best-effort telemetry: swallow failures so a
                        // dead server or expired session can't take the app down,
                        // and only advance the marker on success so it retries.
                        val ok = tracks.isEmpty() || runCatching {
                            apiClient.reportQueue(url, clientId, tracks, player.currentMediaItemIndex)
                        }.onFailure { Log.w(TAG, "reportQueue failed", it) }.isSuccess
                        if (ok) {
                            lastReportedQueueKey = qKey
                        } else {
                            nextReportAttemptMs = System.currentTimeMillis() + REPORT_RETRY_BACKOFF_MS
                        }
                    }
                    if (qKey != null && qKey != lastPrewarmedQueueKey) {
                        lastPrewarmedQueueKey = qKey
                        for (i in 0 until player.mediaItemCount) {
                            val tid = extractTrackId(player.getMediaItemAt(i).mediaId)
                            if (tid > 0L && !isStreamUrlFresh(tid, activeQuality.get())) {
                                serviceScope.launch(Dispatchers.IO) {
                                    runCatching {
                                        withTimeout(5000) {
                                            apiClient.streamUrlInfo(url, token, tid, quality = activeQuality.get())
                                        }
                                    }.onSuccess { response ->
                                        streamUrlCache[cacheKey(tid, response.streamQuality)] = CachedStreamUrl(
                                            url = response.url,
                                            quality = response.streamQuality,
                                            qualityLabel = response.streamQualityLabel,
                                            originalQualityLabel = response.originalQualityLabel,
                                            expiresAtMs = System.currentTimeMillis() + STREAM_URL_TTL_MS,
                                        )
                                    }
                                }
                            }
                        }
                    }
                    val mediaId = player.currentMediaItem?.mediaId
                    if (mediaId != null && mediaId != lastReportedMediaId && canReport) {
                        val ok = runCatching {
                            apiClient.reportIndex(url, clientId, player.currentMediaItemIndex)
                        }.onFailure { Log.w(TAG, "reportIndex failed", it) }.isSuccess
                        if (ok) {
                            lastReportedMediaId = mediaId
                        } else {
                            nextReportAttemptMs = System.currentTimeMillis() + REPORT_RETRY_BACKOFF_MS
                        }
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
        val quality = activeQuality.get()
        streamUrlCache[cacheKey(trackId, quality)]?.let { cached ->
            if (cached.expiresAtMs > now) {
                updateCurrentStreamLabels(cached)
                return spec.withUri(Uri.parse(cached.url))
            }
            streamUrlCache.remove(cacheKey(trackId, quality))
        }

        // ResolvingDataSource.Resolver may only throw IOException; anything else
        // (timeout, API error) escapes the loader as an unexpected error.
        val response = try {
            runBlocking {
                withTimeout(5000) {
                    apiClient.streamUrlInfo(server, tokenHolder.get(), trackId, quality = quality)
                }
            }
        } catch (e: IOException) {
            throw e
        } catch (e: Exception) {
            throw IOException("Failed to resolve stream URL for track $trackId", e)
        }
        val cached = CachedStreamUrl(
            url = response.url,
            quality = response.streamQuality,
            qualityLabel = response.streamQualityLabel,
            originalQualityLabel = response.originalQualityLabel,
            expiresAtMs = System.currentTimeMillis() + STREAM_URL_TTL_MS,
        )
        streamUrlCache[cacheKey(trackId, response.streamQuality)] = cached
        updateCurrentStreamLabels(cached)
        return spec.withUri(Uri.parse(response.url))
    }

    private fun isStreamUrlFresh(trackId: Long, quality: String): Boolean {
        val cached = streamUrlCache[cacheKey(trackId, quality)] ?: return false
        return cached.expiresAtMs > System.currentTimeMillis()
    }

    private fun cacheKey(trackId: Long, quality: String): String = "$trackId:$quality"

    private fun updateCurrentStreamLabels(cached: CachedStreamUrl) {
        currentStreamQuality.set(cached.quality)
        currentStreamQualityLabel.set(cached.qualityLabel)
        currentOriginalQualityLabel.set(cached.originalQualityLabel)
    }

    private fun recordBufferingEvent(player: ExoPlayer) {
        val now = System.currentTimeMillis()
        val next = adaptiveQualityPolicy.recordBufferingEvent(activeQuality.get(), now)
        if (next != null) {
            downgradeForBuffering(player, next)
        }
    }

    private fun downgradeForBuffering(player: ExoPlayer, next: String) {
        if (!downgradeInFlight.compareAndSet(false, true)) return
        val current = activeQuality.get()
        if (next == current) {
            downgradeInFlight.set(false)
            return
        }
        serviceScope.launch(Dispatchers.Main) {
            try {
                val position = player.currentPosition.coerceAtLeast(0L)
                val index = player.currentMediaItemIndex.coerceAtLeast(0)
                val items = (0 until player.mediaItemCount).map { player.getMediaItemAt(it) }
                activeQuality.set(next)
                currentStreamQuality.set(next)
                currentStreamQualityLabel.set(qualityLabel(next))
                if (items.isNotEmpty()) {
                    player.setMediaItems(items, index.coerceIn(items.indices), position)
                    player.prepare()
                    player.play()
                }
                adaptiveQualityPolicy.reset()
            } finally {
                downgradeInFlight.set(false)
            }
        }
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
        private const val TAG = "JamarrPlaybackService"
        const val JAMARR_SCHEME = "jamarr"

        // Back off after a failed queue/index report so an unreachable server
        // isn't retried on every 500ms tick.
        const val REPORT_RETRY_BACKOFF_MS = 5_000L

        // Server default STREAM_TOKEN_TTL_SECONDS=300. Cache for 240s so a
        // pre-warmed URL still has ~60s of validity when ExoPlayer opens it.
        const val STREAM_URL_TTL_MS = 240_000L

        val currentStreamQuality = AtomicReference("original")
        val currentStreamQualityLabel = AtomicReference("Original")
        val currentOriginalQualityLabel = AtomicReference("Original")

        fun trackUri(trackId: Long): Uri =
            Uri.parse("$JAMARR_SCHEME://track/$trackId")

        fun nextLowerQuality(current: String): String = StreamQualityLadder.nextLower(current)

        fun qualityLabel(quality: String): String = StreamQualityLadder.label(quality)
    }
}
