package com.jamarr.android.cast

import android.content.Context
import android.net.Uri
import android.util.Log
import androidx.mediarouter.media.MediaRouteSelector
import androidx.mediarouter.media.MediaRouter
import com.google.android.gms.cast.CastMediaControlIntent
import com.google.android.gms.cast.MediaInfo
import com.google.android.gms.cast.MediaLoadRequestData
import com.google.android.gms.cast.MediaMetadata
import com.google.android.gms.cast.MediaQueueData
import com.google.android.gms.cast.MediaQueueItem
import com.google.android.gms.cast.MediaStatus
import com.google.android.gms.cast.framework.CastContext
import com.google.android.gms.cast.framework.CastSession
import com.google.android.gms.cast.framework.SessionManagerListener
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailability
import com.google.android.gms.common.images.WebImage
import com.jamarr.android.renderer.DeviceRendererController
import com.jamarr.android.renderer.DeviceRendererInfo
import com.jamarr.android.renderer.DeviceRendererPlaybackState
import com.jamarr.android.renderer.QueuedTrack
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext

private const val TAG = "CastDeviceController"

class CastDeviceController(private val appContext: Context) : DeviceRendererController {
    override val kind: String = "cast"

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val _renderers = MutableStateFlow<List<DeviceRendererInfo>>(emptyList())
    override val renderers: StateFlow<List<DeviceRendererInfo>> = _renderers.asStateFlow()

    private val _state = MutableStateFlow(DeviceRendererPlaybackState())
    override val state: StateFlow<DeviceRendererPlaybackState> = _state.asStateFlow()

    private var castContext: CastContext? = null
    private var mediaRouter: MediaRouter? = null
    private var currentSession: CastSession? = null
    private var started = false
    private var ignoreRemoteVolumeUntilMs = 0L

    private val selector = MediaRouteSelector.Builder()
        .addControlCategory(
            CastMediaControlIntent.categoryForCast(
                CastMediaControlIntent.DEFAULT_MEDIA_RECEIVER_APPLICATION_ID,
            ),
        )
        .build()

    private val routeCallback = object : MediaRouter.Callback() {
        override fun onRouteAdded(router: MediaRouter, route: MediaRouter.RouteInfo) {
            publishRoutes(router.routes)
        }

        override fun onRouteChanged(router: MediaRouter, route: MediaRouter.RouteInfo) {
            publishRoutes(router.routes)
        }

        override fun onRouteRemoved(router: MediaRouter, route: MediaRouter.RouteInfo) {
            publishRoutes(router.routes)
        }
    }

    private val sessionListener = object : SessionManagerListener<CastSession> {
        override fun onSessionStarted(session: CastSession, sessionId: String) = attachSession(session)
        override fun onSessionResumed(session: CastSession, wasSuspended: Boolean) = attachSession(session)
        override fun onSessionStarting(session: CastSession) = Unit
        override fun onSessionStartFailed(session: CastSession, error: Int) = setStatus("Cast session failed: $error")
        override fun onSessionEnding(session: CastSession) = Unit
        override fun onSessionEnded(session: CastSession, error: Int) = detachSession(error)
        override fun onSessionResuming(session: CastSession, sessionId: String) = Unit
        override fun onSessionResumeFailed(session: CastSession, error: Int) = setStatus("Cast resume failed: $error")
        override fun onSessionSuspended(session: CastSession, reason: Int) = setStatus("Cast session suspended")
    }

    private val remoteCallback = object : com.google.android.gms.cast.framework.media.RemoteMediaClient.Callback() {
        override fun onStatusUpdated() {
            updateFromRemote()
        }

        override fun onQueueStatusUpdated() {
            updateFromRemote()
        }
    }

    private val progressListener = com.google.android.gms.cast.framework.media.RemoteMediaClient.ProgressListener {
        progressMs,
        durationMs ->
        val current = _state.value
        _state.value = current.copy(
            positionSeconds = progressMs.coerceAtLeast(0L) / 1000.0,
            durationSeconds = if (durationMs > 0) durationMs / 1000.0 else current.durationSeconds,
        )
    }

    override fun start() {
        if (started) return
        started = true
        if (!isPlayServicesAvailable()) {
            _renderers.value = emptyList()
            setStatus("Google Play Services is required for Cast")
            return
        }
        runCatching {
            val context = appContext.applicationContext
            castContext = CastContext.getSharedInstance(context)
            mediaRouter = MediaRouter.getInstance(context).also { router ->
                router.addCallback(selector, routeCallback, MediaRouter.CALLBACK_FLAG_REQUEST_DISCOVERY)
                publishRoutes(router.routes)
            }
            castContext?.sessionManager?.addSessionManagerListener(sessionListener, CastSession::class.java)
            castContext?.sessionManager?.currentCastSession?.let { attachSession(it) }
        }.onFailure {
            Log.w(TAG, "Cast start failed", it)
            setStatus("Cast unavailable: ${it.message}")
        }
    }

    override fun stop() {
        mediaRouter?.removeCallback(routeCallback)
        castContext?.sessionManager?.removeSessionManagerListener(sessionListener, CastSession::class.java)
        currentSession?.remoteMediaClient?.unregisterCallback(remoteCallback)
        currentSession?.remoteMediaClient?.removeProgressListener(progressListener)
        mediaRouter = null
        currentSession = null
        started = false
        _renderers.value = emptyList()
        _state.value = DeviceRendererPlaybackState()
    }

    override fun search() {
        mediaRouter?.let { publishRoutes(it.routes) }
    }

    override fun selectRenderer(rendererId: String) {
        val nativeId = rendererId.removePrefix("cast:")
        val route = mediaRouter?.routes?.firstOrNull { routeRendererId(it) == "cast:$nativeId" } ?: return
        _state.value = _state.value.copy(activeRendererId = "cast:$nativeId", status = null)
        runCatching {
            mediaRouter?.selectRoute(route)
        }.onFailure {
            Log.w(TAG, "Cast select failed", it)
            setStatus("Cast connect failed: ${it.message}")
        }
    }

    override suspend fun playQueue(tracks: List<QueuedTrack>, startIndex: Int) {
        if (tracks.isEmpty()) return
        val idx = startIndex.coerceIn(0, tracks.lastIndex)
        _state.value = _state.value.copy(
            queue = tracks,
            currentIndex = idx,
            positionSeconds = 0.0,
            durationSeconds = tracks[idx].durationSeconds,
            isPlaying = true,
            transportState = "BUFFERING",
            status = null,
        )
        loadQueue(idx)
    }

    override suspend fun pause() {
        withRemote { pause() }
        _state.value = _state.value.copy(isPlaying = false, transportState = "PAUSED")
    }

    override suspend fun resume() {
        withRemote { play() }
        _state.value = _state.value.copy(isPlaying = true, transportState = "PLAYING")
    }

    override suspend fun stopPlayback() {
        withRemote { stop() }
        _state.value = _state.value.copy(
            queue = emptyList(),
            currentIndex = -1,
            positionSeconds = 0.0,
            isPlaying = false,
            transportState = "STOPPED",
        )
    }

    override suspend fun seek(seconds: Double) {
        withRemote { seek((seconds * 1000).toLong().coerceAtLeast(0L)) }
        _state.value = _state.value.copy(positionSeconds = seconds.coerceAtLeast(0.0))
    }

    override suspend fun setVolumePercent(percent: Int) {
        val bounded = percent.coerceIn(0, 100)
        withContext(Dispatchers.Main.immediate) {
            val route = currentRoute()
            if (route != null && route.volumeMax > 0) {
                val routeVolume = ((bounded / 100.0) * route.volumeMax).toInt()
                    .coerceIn(0, route.volumeMax)
                route.requestSetVolume(routeVolume)
            }
            runCatching { currentSession?.volume = bounded / 100.0 }
        }
        ignoreRemoteVolumeUntilMs = System.currentTimeMillis() + 2_500
        _state.value = _state.value.copy(volumePercent = bounded)
    }

    override suspend fun next() {
        val s = _state.value
        if (s.queue.isEmpty()) return
        val nextIdx = (s.currentIndex + 1).coerceAtMost(s.queue.lastIndex)
        if (nextIdx != s.currentIndex) jumpTo(nextIdx)
    }

    override suspend fun previous() {
        val s = _state.value
        if (s.queue.isEmpty()) return
        val prevIdx = (s.currentIndex - 1).coerceAtLeast(0)
        if (prevIdx != s.currentIndex) jumpTo(prevIdx)
    }

    override suspend fun jumpTo(index: Int) {
        val s = _state.value
        if (s.queue.isEmpty()) return
        val target = index.coerceIn(0, s.queue.lastIndex)
        _state.value = s.copy(
            currentIndex = target,
            positionSeconds = 0.0,
            durationSeconds = s.queue[target].durationSeconds,
            isPlaying = true,
            transportState = "BUFFERING",
        )
        loadQueue(target)
    }

    private fun attachSession(session: CastSession) {
        currentSession?.remoteMediaClient?.unregisterCallback(remoteCallback)
        currentSession?.remoteMediaClient?.removeProgressListener(progressListener)
        currentSession = session
        session.remoteMediaClient?.registerCallback(remoteCallback)
        session.remoteMediaClient?.addProgressListener(progressListener, 1000L)
        _state.value = _state.value.copy(
            volumePercent = currentRouteVolumePercent() ?: sessionVolumePercent(session),
            status = null,
        )
        updateFromRemote()
    }

    private fun detachSession(error: Int) {
        currentSession?.remoteMediaClient?.unregisterCallback(remoteCallback)
        currentSession?.remoteMediaClient?.removeProgressListener(progressListener)
        currentSession = null
        _state.value = _state.value.copy(isPlaying = false, transportState = "STOPPED")
        if (error != 0) setStatus("Cast session ended: $error")
    }

    private suspend fun loadQueue(startIndex: Int) {
        withRemote {
            val state = _state.value
            val items = state.queue.map { MediaQueueItem.Builder(mediaInfo(it)).build() }
            val queueData = MediaQueueData.Builder()
                .setItems(items)
                .setStartIndex(startIndex)
                .setRepeatMode(MediaStatus.REPEAT_MODE_REPEAT_OFF)
                .build()
            val request = MediaLoadRequestData.Builder()
                .setMediaInfo(mediaInfo(state.queue[startIndex]))
                .setQueueData(queueData)
                .setAutoplay(true)
                .build()
            load(request)
        }
    }

    private fun updateFromRemote() {
        val session = currentSession ?: return
        val client = session.remoteMediaClient ?: return
        val mediaStatus = client.mediaStatus
        val playerState = mediaStatus?.playerState
        val activeIndex = mediaStatus?.queueItems?.indexOfFirst { it.itemId == mediaStatus.currentItemId }
            ?.takeIf { it >= 0 }
            ?: _state.value.currentIndex
        val transport = when (playerState) {
            MediaStatus.PLAYER_STATE_PLAYING, MediaStatus.PLAYER_STATE_BUFFERING -> "PLAYING"
            MediaStatus.PLAYER_STATE_PAUSED -> "PAUSED"
            MediaStatus.PLAYER_STATE_IDLE -> "IDLE"
            else -> _state.value.transportState
        }
        val current = _state.value
        val idleFinished = playerState == MediaStatus.PLAYER_STATE_IDLE &&
            mediaStatus?.idleReason == MediaStatus.IDLE_REASON_FINISHED
        if (idleFinished && activeIndex >= current.queue.lastIndex) {
            _state.value = current.copy(isPlaying = false, transportState = "STOPPED")
            return
        }
        _state.value = current.copy(
            currentIndex = activeIndex,
            positionSeconds = client.approximateStreamPosition.coerceAtLeast(0L) / 1000.0,
            durationSeconds = client.streamDuration.takeIf { it > 0 }?.let { it / 1000.0 } ?: current.durationSeconds,
            isPlaying = playerState == MediaStatus.PLAYER_STATE_PLAYING || playerState == MediaStatus.PLAYER_STATE_BUFFERING,
            transportState = transport,
            volumePercent = remoteVolumePercent(session, current.volumePercent),
        )
    }

    private fun remoteVolumePercent(session: CastSession, currentVolume: Int): Int {
        if (System.currentTimeMillis() < ignoreRemoteVolumeUntilMs) return currentVolume
        return currentRouteVolumePercent() ?: sessionVolumePercent(session)
    }

    private fun sessionVolumePercent(session: CastSession): Int =
        runCatching { (session.volume * 100).toInt().coerceIn(0, 100) }.getOrDefault(_state.value.volumePercent)

    private fun currentRouteVolumePercent(): Int? {
        val route = currentRoute() ?: return null
        val max = route.volumeMax
        if (max <= 0) return null
        return ((route.volume.toDouble() / max.toDouble()) * 100).toInt().coerceIn(0, 100)
    }

    private fun currentRoute(): MediaRouter.RouteInfo? {
        val active = _state.value.activeRendererId ?: return null
        return mediaRouter?.routes?.firstOrNull { routeRendererId(it) == active }
    }

    private suspend fun <T> withRemote(block: com.google.android.gms.cast.framework.media.RemoteMediaClient.() -> T?): T? =
        withContext(Dispatchers.Main.immediate) {
            val client = currentSession?.remoteMediaClient ?: run {
                setStatus("No active Cast session")
                return@withContext null
            }
            block(client)
        }

    private fun publishRoutes(routes: List<MediaRouter.RouteInfo>) {
        val list = routes
            .filter { it.matchesSelector(selector) && !it.isDefault }
            .map { route ->
                DeviceRendererInfo(
                    rendererId = routeRendererId(route),
                    kind = kind,
                    name = route.name,
                    modelName = route.description?.toString(),
                    status = route.connectionState.takeIf { it != MediaRouter.RouteInfo.CONNECTION_STATE_DISCONNECTED }
                        ?.let { "Connecting" },
                )
            }
            .distinctBy { it.rendererId }
            .sortedBy { it.name.lowercase() }
        _renderers.value = list
    }

    private fun mediaInfo(track: QueuedTrack): MediaInfo {
        val metadata = MediaMetadata(MediaMetadata.MEDIA_TYPE_MUSIC_TRACK).apply {
            putString(MediaMetadata.KEY_TITLE, track.title)
            putString(MediaMetadata.KEY_ARTIST, track.artist)
            putString(MediaMetadata.KEY_ALBUM_TITLE, track.album)
            track.artUrl?.let { addImage(WebImage(Uri.parse(it))) }
        }
        return MediaInfo.Builder(track.streamUrl)
            .setStreamType(MediaInfo.STREAM_TYPE_BUFFERED)
            .setContentType(track.mime)
            .setMetadata(metadata)
            .build()
    }

    private fun routeRendererId(route: MediaRouter.RouteInfo): String =
        "cast:${route.id.ifBlank { route.name.toString() }}"

    private fun isPlayServicesAvailable(): Boolean =
        GoogleApiAvailability.getInstance()
            .isGooglePlayServicesAvailable(appContext.applicationContext) == ConnectionResult.SUCCESS

    private fun setStatus(message: String) {
        _state.value = _state.value.copy(status = message)
    }
}
