package com.jamarr.android.playback

import android.app.PendingIntent
import android.content.Intent
import android.net.ConnectivityManager
import android.net.Uri
import android.util.Log
import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.Player
import androidx.media3.common.Timeline
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.datasource.ResolvingDataSource
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.MediaLibraryService
import androidx.media3.session.MediaSession
import com.google.common.util.concurrent.ListenableFuture
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
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.guava.future
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
        val source: StreamSource? = null,
    )
    private val streamUrlCache = ConcurrentHashMap<String, CachedStreamUrl>()

    // Quality labels shown by the now-playing UI, keyed the same way as the
    // media cache. Unlike streamUrlCache these never expire: once a track plays
    // from disk the resolver stops running, so the labels have to survive
    // independently of the stream token.
    private data class StreamLabels(
        val quality: String,
        val qualityLabel: String,
        val originalQualityLabel: String,
    )
    private val streamLabels = ConcurrentHashMap<String, StreamLabels>()
    private val activeQuality = AtomicReference("original")
    private val adaptiveQualityPolicy = AdaptiveStreamQualityPolicy()
    private val downgradeInFlight = AtomicBoolean(false)

    // Settings are read off the main thread, so everything that needs a server
    // URL or token waits on this instead of blocking service creation. The car
    // connects by starting the service, which makes onCreate an ANR-sensitive
    // path.
    private val settingsLoaded = CompletableDeferred<Unit>()
    private lateinit var settingsStore: SettingsStore
    private lateinit var tokenHolder: TokenHolder
    private lateinit var apiClient: JamarrApiClient
    private lateinit var libraryProvider: JamarrLibraryProvider
    private lateinit var mediaCache: JamarrMediaCache
    private lateinit var prefetcher: StreamPrefetcher
    private lateinit var connectivityManager: ConnectivityManager
    private val wifiOnlyTransfers = AtomicBoolean(false)

    override fun onCreate() {
        super.onCreate()

        val app = applicationContext as JamarrApplication
        tokenHolder = app.tokenHolder
        mediaCache = app.mediaCache
        val cookieJar = app.cookieJar
        settingsStore = SettingsStore(applicationContext)
        connectivityManager = getSystemService(ConnectivityManager::class.java)

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

        // Built before anything can reach it: the coroutines below run as soon
        // as they are launched, and a lateinit read from one of them would race
        // service creation.
        libraryProvider = JamarrLibraryProvider(
            apiClient = apiClient,
            credentials = {
                settingsLoaded.await()
                JamarrLibraryProvider.Credentials(serverUrl.get(), tokenHolder.get())
            },
            scope = serviceScope,
        )

        // DataStore reads are suspend functions; doing them with runBlocking
        // would block the main thread on the same path the car uses to start
        // the service. Everything that needs them awaits settingsLoaded.
        val clientId = AtomicReference("")
        serviceScope.launch {
            val saved = settingsStore.load()
            serverUrl.set(saved.serverUrl)
            tokenHolder.set(saved.accessToken)
            cookieJar.prime()
            clientId.set(settingsStore.getClientId())
            settingsLoaded.complete(Unit)
        }

        serviceScope.launch {
            settingsLoaded.await()
            var lastSessionKey = sessionKey(serverUrl.get(), tokenHolder.get())
            settingsStore.observeSession().collectLatest { session ->
                serverUrl.set(session.serverUrl)
                val key = sessionKey(session.serverUrl, session.accessToken)
                if (key != lastSessionKey) {
                    lastSessionKey = key
                    // Browsers cache what they subscribed to, so a sign-in on
                    // the phone is invisible in the car until we say otherwise.
                    libraryProvider.onSessionChanged()
                }
            }
        }

        val httpFactory = DefaultHttpDataSource.Factory()
        val resolvingFactory = ResolvingDataSource.Factory(httpFactory) { spec ->
            resolveDataSpec(spec)
        }

        // Cache layers sit ABOVE the resolver on purpose. They then see the
        // stable jamarr://track/{id} URI rather than the signed, rotating
        // /api/stream/{id}?token=… URL, so the cache never fragments per token,
        // and a cache hit skips the resolve (and therefore the network) whole.
        val cacheKeyFactory = JamarrCacheKeyFactory { activeQuality.get() }
        val prefetchFactory = CacheDataSource.Factory()
            .setCache(mediaCache.prefetchCache)
            .setUpstreamDataSourceFactory(resolvingFactory)
            .setCacheKeyFactory(cacheKeyFactory)
            .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)
        // Downloads are read-only during playback; only the download manager
        // writes that cache. Passing a null sink factory disables writes.
        val playbackFactory = CacheDataSource.Factory()
            .setCache(mediaCache.downloadCache)
            .setUpstreamDataSourceFactory(prefetchFactory)
            .setCacheKeyFactory(cacheKeyFactory)
            .setCacheWriteDataSinkFactory(null)
            .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)

        val mediaSourceFactory = DefaultMediaSourceFactory(this)
            .setDataSourceFactory(playbackFactory)

        prefetcher = StreamPrefetcher(
            scope = serviceScope,
            dataSourceFactory = prefetchFactory,
            mediaCache = mediaCache,
            qualityProvider = { activeQuality.get() },
            // Read fresh each time: both the setting and the active network can
            // change while a queue is playing.
            networkAllows = {
                PrefetchPolicy.allowsNetwork(
                    wifiOnly = wifiOnlyTransfers.get(),
                    metered = connectivityManager.isActiveNetworkMetered,
                )
            },
        )

        // Started only after the prefetcher exists — the first emission is
        // immediate and would otherwise touch a lateinit field.
        serviceScope.launch {
            settingsStore.observeWifiOnlyTransfers().collect { enabled ->
                wifiOnlyTransfers.set(enabled)
                if (enabled && connectivityManager.isActiveNetworkMetered) prefetcher.cancel()
            }
        }

        // The prefetcher covers upcoming tracks; the in-progress track is
        // covered by holding a long buffer. The byte cap matters as much as the
        // duration: the default audio target (~13 MB) would cut a lossless
        // stream well short of maxBufferMs.
        val loadControl = DefaultLoadControl.Builder()
            .setBufferDurationsMs(
                /* minBufferMs= */ 50_000,
                /* maxBufferMs= */ 300_000,
                /* bufferForPlaybackMs= */ 2_500,
                /* bufferForPlaybackAfterRebufferMs= */ 5_000,
            )
            .setTargetBufferBytes(TARGET_BUFFER_BYTES)
            .setPrioritizeTimeOverSizeThresholds(true)
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
                if (playbackState == Player.STATE_READY) {
                    schedulePrefetch(player)
                }
            }

            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
                applyStreamLabels(mediaItem)
                schedulePrefetch(player)
            }

            override fun onTimelineChanged(timeline: Timeline, reason: Int) {
                schedulePrefetch(player)
            }
        })

        serviceScope.launch(Dispatchers.Main) {
            settingsLoaded.await()
            var lastProgressReport = 0L
            var lastReportedQueueKey: String? = null
            var lastReportedMediaId: String? = null
            var lastPrewarmedQueueKey: String? = null
            var lastResumeSnapshot = 0L
            var wasPlaying = false
            var nextReportAttemptMs = 0L
            while (true) {
                val url = serverUrl.get()
                val token = tokenHolder.get()
                val id = clientId.get()
                // Snapshot while playing, and once more on pause so the stored
                // position is where the user actually stopped. A paused queue
                // then costs no further writes.
                val playing = player.isPlaying
                val dueForSnapshot =
                    playing && System.currentTimeMillis() - lastResumeSnapshot >= RESUME_SNAPSHOT_INTERVAL_MS
                if (player.mediaItemCount > 0 && (dueForSnapshot || (wasPlaying && !playing))) {
                    lastResumeSnapshot = System.currentTimeMillis()
                    saveResumeQueue(player)
                }
                wasPlaying = playing
                if (url.isNotBlank() && id.isNotBlank() && token.isNotBlank() && !authFailed.get()) {
                    val qKey = queueKey(player)
                    val canReport = System.currentTimeMillis() >= nextReportAttemptMs
                    if (qKey != null && qKey != lastReportedQueueKey && canReport) {
                        val tracks = queueSearchTracks(player)
                        // Reporting is best-effort telemetry: swallow failures so a
                        // dead server or expired session can't take the app down,
                        // and only advance the marker on success so it retries.
                        val ok = tracks.isEmpty() || runCatching {
                            apiClient.reportQueue(url, id, tracks, player.currentMediaItemIndex)
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
                                        val entry = CachedStreamUrl(
                                            url = response.url,
                                            quality = response.streamQuality,
                                            qualityLabel = response.streamQualityLabel,
                                            originalQualityLabel = response.originalQualityLabel,
                                            expiresAtMs = System.currentTimeMillis() + STREAM_URL_TTL_MS,
                                            source = StreamSource(
                                                response.sourceSampleRateHz,
                                                response.sourceBitDepth,
                                            ),
                                        )
                                        streamUrlCache[cacheKey(tid, response.streamQuality)] = entry
                                        rememberStreamLabels(tid, entry)
                                    }
                                }
                            }
                        }
                    }
                    val mediaId = player.currentMediaItem?.mediaId
                    if (mediaId != null && mediaId != lastReportedMediaId && canReport) {
                        val ok = runCatching {
                            apiClient.reportIndex(url, id, player.currentMediaItemIndex)
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
                            url, id,
                            positionSeconds = player.currentPosition / 1000.0,
                            isPlaying = true,
                        )
                    }
                }
                // Idle sessions do not need 500 ms granularity; the tick only
                // has work to do while something is actually playing.
                delay(if (player.isPlaying) ACTIVE_TICK_MS else IDLE_TICK_MS)
            }
        }

        val sessionIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

        librarySession = MediaLibrarySession.Builder(this, player, sessionCallback())
            .setSessionActivity(sessionIntent)
            .build()
        libraryProvider.session = librarySession
    }

    /**
     * Session callback: the library tree comes from [JamarrLibraryProvider],
     * connection filtering and resumption are the service's business because
     * they need the player and the settings store.
     */
    private fun sessionCallback(): MediaLibrarySession.Callback {
        val library = libraryProvider.callback
        // Forwarded explicitly rather than with `by`: every method on this
        // interface is a Java default, and Kotlin's delegation does not
        // generate overrides for those — the defaults would win and answer
        // every browse request with ERROR_NOT_SUPPORTED.
        return object : MediaLibrarySession.Callback {

            override fun onGetLibraryRoot(
                session: MediaLibrarySession,
                browser: MediaSession.ControllerInfo,
                params: MediaLibraryService.LibraryParams?,
            ) = library.onGetLibraryRoot(session, browser, params)

            override fun onGetItem(
                session: MediaLibrarySession,
                browser: MediaSession.ControllerInfo,
                mediaId: String,
            ) = library.onGetItem(session, browser, mediaId)

            override fun onGetChildren(
                session: MediaLibrarySession,
                browser: MediaSession.ControllerInfo,
                parentId: String,
                page: Int,
                pageSize: Int,
                params: MediaLibraryService.LibraryParams?,
            ) = library.onGetChildren(session, browser, parentId, page, pageSize, params)

            override fun onSubscribe(
                session: MediaLibrarySession,
                browser: MediaSession.ControllerInfo,
                parentId: String,
                params: MediaLibraryService.LibraryParams?,
            ) = library.onSubscribe(session, browser, parentId, params)

            override fun onAddMediaItems(
                mediaSession: MediaSession,
                controller: MediaSession.ControllerInfo,
                mediaItems: List<MediaItem>,
            ) = library.onAddMediaItems(mediaSession, controller, mediaItems)

            override fun onSetMediaItems(
                mediaSession: MediaSession,
                controller: MediaSession.ControllerInfo,
                mediaItems: List<MediaItem>,
                startIndex: Int,
                startPositionMs: Long,
            ) = library.onSetMediaItems(mediaSession, controller, mediaItems, startIndex, startPositionMs)

            override fun onConnect(
                session: MediaSession,
                controller: MediaSession.ControllerInfo,
            ): MediaSession.ConnectionResult {
                val caller = ControllerAccess.Caller(
                    packageName = controller.packageName,
                    uid = controller.uid,
                    trusted = controller.isTrusted,
                    packageNameVerified = controller.isPackageNameVerified,
                )
                val allowed = ControllerAccess.isAllowed(
                    caller = caller,
                    selfPackage = packageName,
                    selfUid = android.os.Process.myUid(),
                )
                if (!allowed) {
                    Log.w(TAG, "Rejected media session connection from ${controller.packageName}")
                    return MediaSession.ConnectionResult.reject()
                }
                return MediaSession.ConnectionResult.AcceptedResultBuilder(session).build()
            }

            /**
             * Restores the last queue when the car (or a media button) asks to
             * resume. Failing the future is how media3 is told there is nothing
             * to resume.
             */
            override fun onPlaybackResumption(
                mediaSession: MediaSession,
                controller: MediaSession.ControllerInfo,
            ): ListenableFuture<MediaSession.MediaItemsWithStartPosition> = serviceScope.future {
                val queue = ResumeQueue.decode(settingsStore.loadResumeQueue())
                    ?: throw UnsupportedOperationException("No queue to resume")
                MediaSession.MediaItemsWithStartPosition(
                    queue.tracks.map { resumeMediaItem(it) },
                    queue.index,
                    queue.positionMs,
                )
            }
        }
    }

    private fun resumeMediaItem(track: ResumeTrack): MediaItem {
        val metadata = MediaMetadata.Builder()
            .setTitle(track.title)
            .setArtist(track.artist)
            .setAlbumTitle(track.album)
            .setIsBrowsable(false)
            .setIsPlayable(true)
            .setMediaType(MediaMetadata.MEDIA_TYPE_MUSIC)
        if (track.durationMs > 0L) metadata.setDurationMs(track.durationMs)
        track.artUri?.takeIf { it.isNotBlank() }?.let { metadata.setArtworkUri(Uri.parse(it)) }
        val builder = MediaItem.Builder()
            .setMediaId(track.mediaId)
            .setMediaMetadata(metadata.build())
        val trackId = extractTrackId(track.mediaId)
        if (trackId > 0L) builder.setUri(trackUri(trackId))
        return builder.build()
    }

    /** Must run on the application thread — [Player] state is not thread safe. */
    private fun saveResumeQueue(player: Player) {
        val tracks = (0 until player.mediaItemCount).map { index ->
            val item = player.getMediaItemAt(index)
            val md = item.mediaMetadata
            ResumeTrack(
                mediaId = item.mediaId,
                title = md.title?.toString().orEmpty(),
                artist = md.artist?.toString(),
                album = md.albumTitle?.toString(),
                artUri = md.artworkUri?.toString(),
                durationMs = md.durationMs ?: -1L,
            )
        }
        val snapshot = ResumeQueue(
            tracks = tracks,
            index = player.currentMediaItemIndex.coerceAtLeast(0),
            positionMs = player.currentPosition.coerceAtLeast(0L),
        )
        serviceScope.launch {
            runCatching { settingsStore.saveResumeQueue(ResumeQueue.encode(snapshot)) }
                .onFailure { Log.w(TAG, "Failed to persist resume queue", it) }
        }
    }

    private fun sessionKey(serverUrl: String, accessToken: String): String =
        "$serverUrl|${accessToken.isNotBlank()}"

    private fun resolveDataSpec(spec: DataSpec): DataSpec {
        val uri = spec.uri
        if (uri.scheme != JAMARR_SCHEME) return spec
        val trackId = uri.lastPathSegment?.toLongOrNull()
            ?: throw IOException("Missing track id in $uri")
        // Resumption can start playback before settings finish loading; wait
        // briefly on the loader thread rather than fail the open outright.
        runBlocking {
            runCatching { withTimeout(SETTINGS_WAIT_MS) { settingsLoaded.await() } }
        }
        val server = serverUrl.get()
        if (server.isBlank()) throw IOException("Jamarr server URL not set")

        val now = System.currentTimeMillis()
        val quality = activeQuality.get()
        streamUrlCache[cacheKey(trackId, quality)]?.let { cached ->
            if (cached.expiresAtMs > now) {
                rememberStreamLabels(trackId, cached)
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
            source = StreamSource(response.sourceSampleRateHz, response.sourceBitDepth),
        )
        streamUrlCache[cacheKey(trackId, response.streamQuality)] = cached
        rememberStreamLabels(trackId, cached)
        return spec.withUri(Uri.parse(response.url))
    }

    /**
     * Schedules read-ahead for the track after the current one.
     *
     * Must run on the application thread; [Player] state is not thread-safe.
     */
    private fun schedulePrefetch(player: Player) {
        val nextIndex = player.nextMediaItemIndex
        if (nextIndex == C.INDEX_UNSET) {
            prefetcher.prefetch(emptyList())
            return
        }
        val trackId = extractTrackId(player.getMediaItemAt(nextIndex).mediaId)
        prefetcher.prefetch(if (trackId > 0L) listOf(trackId) else emptyList())
    }

    private fun isStreamUrlFresh(trackId: Long, quality: String): Boolean {
        val cached = streamUrlCache[cacheKey(trackId, quality)] ?: return false
        return cached.expiresAtMs > System.currentTimeMillis()
    }

    private fun cacheKey(trackId: Long, quality: String): String = "$trackId:$quality"

    private fun rememberStreamLabels(trackId: Long, cached: CachedStreamUrl) {
        streamLabels[cacheKey(trackId, cached.quality)] = StreamLabels(
            quality = cached.quality,
            qualityLabel = cached.qualityLabel,
            originalQualityLabel = cached.originalQualityLabel,
        )
    }

    /**
     * Publishes the quality labels for the item that just became current.
     *
     * These used to be set inside the resolver, which no longer works: a track
     * served from cache never reaches the resolver, and the resolver now also
     * runs for prefetched tracks that are not the current one.
     */
    private fun applyStreamLabels(mediaItem: MediaItem?) {
        val quality = activeQuality.get()
        val trackId = mediaItem?.mediaId?.let { extractTrackId(it) } ?: 0L
        val known = if (trackId > 0L) streamLabels[cacheKey(trackId, quality)] else null
        currentStreamQuality.set(known?.quality ?: quality)
        currentStreamQualityLabel.set(known?.qualityLabel ?: qualityLabel(quality))
        currentOriginalQualityLabel.set(known?.originalQualityLabel ?: qualityLabel(quality))
    }

    private fun recordBufferingEvent(player: ExoPlayer) {
        // Buffering on a fully cached track is a disk/decoder stall, not a slow
        // network, so it must not push the adaptive policy down the ladder.
        val trackId = player.currentMediaItem?.mediaId?.let { extractTrackId(it) } ?: 0L
        if (trackId > 0L && mediaCache.isFullyCached(trackId, activeQuality.get())) return

        val now = System.currentTimeMillis()
        val source = streamUrlCache[cacheKey(trackId, activeQuality.get())]?.source
        val next = adaptiveQualityPolicy.recordBufferingEvent(activeQuality.get(), now, source)
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
        // Cache keys carry the quality, so any read-ahead at the old quality is
        // now worthless.
        prefetcher.cancel()
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
        prefetcher.cancel()
        // The caches deliberately outlive the service: they are process-scoped
        // singletons on JamarrApplication and SimpleCache cannot be reopened on
        // the same directory while another instance holds it.
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

        // Reporting granularity while playing, and while parked on a paused or
        // empty queue — where the tick has nothing to do but still costs wakeups.
        const val ACTIVE_TICK_MS = 500L
        const val IDLE_TICK_MS = 5_000L

        // How often the queue is written down for playback resumption.
        const val RESUME_SNAPSHOT_INTERVAL_MS = 10_000L

        // Upper bound on blocking a loader thread for the initial settings read.
        const val SETTINGS_WAIT_MS = 5_000L

        // Server default STREAM_TOKEN_TTL_SECONDS=300. Cache for 240s so a
        // pre-warmed URL still has ~60s of validity when ExoPlayer opens it.
        const val STREAM_URL_TTL_MS = 240_000L

        // DefaultLoadControl's audio default (~13 MB) would stop a lossless
        // stream far short of maxBufferMs; 48 MB covers a full FLAC track.
        const val TARGET_BUFFER_BYTES = 48 * 1024 * 1024

        val currentStreamQuality = AtomicReference("original")
        val currentStreamQualityLabel = AtomicReference("Original")
        val currentOriginalQualityLabel = AtomicReference("Original")

        fun trackUri(trackId: Long): Uri =
            Uri.parse("$JAMARR_SCHEME://track/$trackId")

        fun nextLowerQuality(current: String): String = StreamQualityLadder.nextLower(current)

        fun qualityLabel(quality: String): String = StreamQualityLadder.label(quality)
    }
}
