package com.jamarr.android.cast

import android.content.Context
import android.util.Log
import androidx.mediarouter.media.MediaRouteSelector
import androidx.mediarouter.media.MediaRouter
import com.google.android.gms.cast.CastMediaControlIntent
import com.google.android.gms.cast.MediaLoadRequestData
import com.google.android.gms.cast.MediaQueueData
import com.google.android.gms.cast.MediaQueueItem
import com.google.android.gms.cast.MediaStatus
import com.google.android.gms.cast.framework.CastContext
import com.google.android.gms.cast.framework.CastSession
import com.google.android.gms.cast.framework.SessionManagerListener
import com.google.android.gms.cast.framework.media.MediaQueue
import com.google.android.gms.cast.framework.media.RemoteMediaClient
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailability
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
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private const val TAG = "CastDeviceController"

// How long a load/jump of ours may take before receiver statuses that still
// describe the old queue are believed again.
private const val LOAD_EXPECTATION_MS = 15_000L

// Queue items fetched per status update while rebuilding a long queue.
private const val FETCH_BATCH = 20

class CastDeviceController(private val appContext: Context) : DeviceRendererController {
    override val kind: String = "cast"

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val _renderers = MutableStateFlow<List<DeviceRendererInfo>>(emptyList())
    override val renderers: StateFlow<List<DeviceRendererInfo>> = _renderers.asStateFlow()

    private val _state = MutableStateFlow(DeviceRendererPlaybackState())
    override val state: StateFlow<DeviceRendererPlaybackState> = _state.asStateFlow()

    /**
     * Set when a Cast session that was already running Jamarr's queue was
     * found and adopted without the user picking the device (app restart,
     * reconnect): the app should switch to it rather than play locally.
     */
    private val _resumedRendererId = MutableStateFlow<String?>(null)
    val resumedRendererId: StateFlow<String?> = _resumedRendererId.asStateFlow()

    /** The Jamarr server's URL, stamped on items so other servers' queues are left alone. */
    var serverUrlProvider: () -> String? = { null }
    private val serverUrl: String? get() = serverUrlProvider()?.takeIf { it.isNotBlank() }

    /** Looks up tracks the receiver names by id but carries no details for. */
    var trackResolver: (suspend (List<Long>) -> List<QueuedTrack>)? = null

    private var castContext: CastContext? = null
    private var mediaRouter: MediaRouter? = null
    private var currentSession: CastSession? = null
    private var attachedQueue: MediaQueue? = null
    private var started = false
    private var ignoreRemoteVolumeUntilMs = 0L

    // Passive: an existing session was attached (restart, resume); its media
    // is inspected and adopted, never replaced. Explicit: the user picked the
    // device, so the next play may replace what it is doing.
    private var explicitRendererId: String? = null
    private var passiveAttach = false
    private var leaving = false
    private var expectation: LoadExpectation? = null
    private var lastNotOurs: ReceiverOwnership? = null

    // Receiver queue items seen so far, by itemId: MediaQueue only caches a
    // window, so a long queue is rebuilt from what was fetched over time.
    private val itemCache = mutableMapOf<Int, ReceiverItem>()
    private val resolvedTracks = mutableMapOf<Long, QueuedTrack>()
    private val resolving = mutableSetOf<Long>()

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
        override fun onSessionStarted(session: CastSession, sessionId: String) =
            attachSession(session, passive = explicitRendererId == null)

        override fun onSessionResumed(session: CastSession, wasSuspended: Boolean) =
            attachSession(session, passive = explicitRendererId == null)

        override fun onSessionStarting(session: CastSession) = Unit
        override fun onSessionStartFailed(session: CastSession, error: Int) = setStatus("Cast session failed: $error")
        override fun onSessionEnding(session: CastSession) = Unit
        override fun onSessionEnded(session: CastSession, error: Int) = detachSession(error)
        override fun onSessionResuming(session: CastSession, sessionId: String) = Unit
        override fun onSessionResumeFailed(session: CastSession, error: Int) = setStatus("Cast resume failed: $error")
        override fun onSessionSuspended(session: CastSession, reason: Int) = setStatus("Cast session suspended")
    }

    private val remoteCallback = object : RemoteMediaClient.Callback() {
        override fun onStatusUpdated() {
            updateFromRemote()
        }

        override fun onQueueStatusUpdated() {
            updateFromRemote()
        }
    }

    private val queueCallback = object : MediaQueue.Callback() {
        override fun mediaQueueChanged() = updateFromRemote()
        override fun itemsReloaded() {
            itemCache.clear()
            updateFromRemote()
        }

        override fun itemsInsertedInRange(insertIndex: Int, insertCount: Int) = updateFromRemote()
        override fun itemsUpdatedAtIndexes(indexes: IntArray) = updateFromRemote()
        override fun itemsRemovedAtIndexes(indexes: IntArray) = updateFromRemote()
    }

    private val progressListener = RemoteMediaClient.ProgressListener { progressMs, durationMs ->
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
            // A session that outlived the app process: inspect it, don't replace it.
            castContext?.sessionManager?.currentCastSession?.let { attachSession(it, passive = true) }
        }.onFailure {
            Log.w(TAG, "Cast start failed", it)
            setStatus("Cast unavailable: ${it.message}")
        }
    }

    override fun stop() {
        mediaRouter?.removeCallback(routeCallback)
        castContext?.sessionManager?.removeSessionManagerListener(sessionListener, CastSession::class.java)
        unregisterRemote()
        mediaRouter = null
        currentSession = null
        started = false
        _renderers.value = emptyList()
        _state.value = DeviceRendererPlaybackState()
        _resumedRendererId.value = null
    }

    override fun search() {
        mediaRouter?.let { publishRoutes(it.routes) }
    }

    override fun selectRenderer(rendererId: String) {
        val nativeId = rendererId.removePrefix("cast:")
        val route = mediaRouter?.routes?.firstOrNull { routeRendererId(it) == "cast:$nativeId" } ?: return
        explicitRendererId = "cast:$nativeId"
        _state.value = _state.value.copy(activeRendererId = "cast:$nativeId", status = null)
        if (currentSession != null && mediaRouter?.selectedRoute?.let(this::routeRendererId) == "cast:$nativeId") {
            // Already connected (e.g. adopted on startup): just look again.
            updateFromRemote()
            return
        }
        runCatching {
            mediaRouter?.selectRoute(route)
        }.onFailure {
            Log.w(TAG, "Cast select failed", it)
            setStatus("Cast connect failed: ${it.message}")
        }
    }

    /**
     * Leave the receiver without stopping it: whatever plays there carries
     * on, and the session can be resumed later. Distinct from [stopPlayback],
     * the user's explicit Stop.
     */
    override fun disconnect() {
        if (currentSession == null) return
        leaving = true
        unregisterRemote()
        currentSession = null
        explicitRendererId = null
        expectation = null
        _resumedRendererId.value = null
        _state.value = DeviceRendererPlaybackState()
        runCatching { castContext?.sessionManager?.endCurrentSession(false) }
            .onFailure { Log.w(TAG, "Cast leave failed", it) }
    }

    override suspend fun playQueue(tracks: List<QueuedTrack>, startIndex: Int) {
        if (tracks.isEmpty()) return
        val idx = startIndex.coerceIn(0, tracks.lastIndex)
        val plan = withContext(Dispatchers.Main.immediate) {
            currentSession?.remoteMediaClient?.let { client ->
                CastQueueReconciler.planPlay(tracks.map { it.id }, idx, receiverQueue(client))
            }
        }
        _state.value = _state.value.copy(
            queue = tracks,
            currentIndex = idx,
            positionSeconds = 0.0,
            durationSeconds = tracks[idx].durationSeconds,
            isPlaying = true,
            transportState = "BUFFERING",
            status = null,
        )
        lastNotOurs = null
        when (plan) {
            is PlayPlan.JumpTo -> jumpToItem(plan.itemId, idx)
            is PlayPlan.Load -> {
                if (plan.replacing == ReceiverOwnership.FOREIGN || plan.replacing == ReceiverOwnership.JAMARR_SERVER) {
                    Log.i(TAG, "Replacing ${plan.replacing} media on the receiver at the user's request")
                }
                loadQueue(idx)
            }
            null -> loadQueue(idx)
        }
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
        // The user's Stop: stop the receiver's media (not just leave it).
        expectation = null
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
        val plan = withContext(Dispatchers.Main.immediate) {
            currentSession?.remoteMediaClient?.let { client ->
                CastQueueReconciler.planPlay(s.queue.map { it.id }, target, receiverQueue(client))
            }
        }
        _state.value = s.copy(
            currentIndex = target,
            positionSeconds = 0.0,
            durationSeconds = s.queue[target].durationSeconds,
            isPlaying = true,
            transportState = "BUFFERING",
        )
        if (plan is PlayPlan.JumpTo) jumpToItem(plan.itemId, target) else loadQueue(target)
    }

    private fun attachSession(session: CastSession, passive: Boolean) {
        unregisterRemote()
        currentSession = session
        leaving = false
        passiveAttach = passive
        lastNotOurs = null
        itemCache.clear()
        val client = session.remoteMediaClient
        client?.registerCallback(remoteCallback)
        client?.addProgressListener(progressListener, 1000L)
        attachedQueue = client?.mediaQueue?.also { it.registerCallback(queueCallback) }
        val rendererId = explicitRendererId ?: selectedRouteRendererId()
        _state.value = _state.value.copy(
            activeRendererId = rendererId ?: _state.value.activeRendererId,
            volumePercent = currentRouteVolumePercent() ?: sessionVolumePercent(session),
            status = null,
        )
        updateFromRemote()
    }

    private fun detachSession(error: Int) {
        unregisterRemote()
        currentSession = null
        expectation = null
        passiveAttach = false
        _resumedRendererId.value = null
        if (leaving) {
            leaving = false
            return
        }
        _state.value = _state.value.copy(isPlaying = false, transportState = "STOPPED")
        if (error != 0) setStatus("Cast session ended: $error")
    }

    private fun unregisterRemote() {
        currentSession?.remoteMediaClient?.unregisterCallback(remoteCallback)
        currentSession?.remoteMediaClient?.removeProgressListener(progressListener)
        attachedQueue?.unregisterCallback(queueCallback)
        attachedQueue = null
    }

    private suspend fun loadQueue(startIndex: Int) {
        withRemote {
            val state = _state.value
            val items = state.queue.map { MediaQueueItem.Builder(CastMediaItems.mediaInfo(it, serverUrl)).build() }
            val queueData = MediaQueueData.Builder()
                .setItems(items)
                .setStartIndex(startIndex)
                .setRepeatMode(MediaStatus.REPEAT_MODE_REPEAT_OFF)
                .build()
            val request = MediaLoadRequestData.Builder()
                .setMediaInfo(CastMediaItems.mediaInfo(state.queue[startIndex], serverUrl))
                .setQueueData(queueData)
                .setAutoplay(true)
                .build()
            expect(state.queue, startIndex)
            itemCache.clear()
            load(request)
        }
    }

    private suspend fun jumpToItem(itemId: Int, index: Int) {
        withRemote {
            expect(_state.value.queue, index)
            queueJumpToItem(itemId, 0L, null)
        }
    }

    private fun expect(queue: List<QueuedTrack>, index: Int) {
        val current = queue.getOrNull(index) ?: return
        expectation = LoadExpectation(
            trackIds = queue.map { it.id },
            currentTrackId = current.id,
            untilMs = System.currentTimeMillis() + LOAD_EXPECTATION_MS,
        )
    }

    /** The receiver's queue as Jamarr tracks, fetching unseen items as needed. */
    private fun receiverQueue(client: RemoteMediaClient): ReceiverQueue {
        val status = client.mediaStatus
        val queue = client.mediaQueue
        val itemIds = queue.itemIds.toList()
        status?.queueItems?.forEach { item ->
            CastMediaItems.receiverItem(item.itemId, item.media)?.let { itemCache[item.itemId] = it }
        }
        itemIds.forEachIndexed { index, id ->
            if (id !in itemCache) {
                queue.getItemAtIndex(index, false)?.let { item ->
                    CastMediaItems.receiverItem(item.itemId, item.media)?.let { itemCache[id] = it }
                }
            }
        }
        if (itemIds.isNotEmpty()) itemCache.keys.retainAll(itemIds.toSet())
        val currentItemId = status?.currentItemId?.takeIf { it != MediaQueueItem.INVALID_ITEM_ID }
        val snapshot = ReceiverSnapshot(
            itemIds = itemIds,
            items = itemCache.toMap(),
            currentItemId = currentItemId,
            currentMedia = CastMediaItems.receiverItem(currentItemId ?: 0, status?.mediaInfo),
        )
        val rebuilt = CastQueueReconciler.reconstruct(snapshot, _state.value.queue, serverUrl, resolvedTracks)
        // Ask for the items not seen yet; the queue callback brings them.
        rebuilt.missingItemIds.take(FETCH_BATCH).forEach { id ->
            val index = queue.indexOfItemWithId(id)
            if (index >= 0) queue.getItemAtIndex(index, true)
        }
        resolveMetadata(rebuilt.needsMetadata)
        return rebuilt
    }

    private fun resolveMetadata(trackIds: List<Long>) {
        val resolver = trackResolver ?: return
        val wanted = trackIds.filter { it !in resolvedTracks && it !in resolving }
        if (wanted.isEmpty()) return
        resolving += wanted
        scope.launch {
            runCatching { resolver(wanted) }
                .onSuccess { tracks -> tracks.forEach { resolvedTracks[it.id] = it } }
                .onFailure { Log.w(TAG, "Track lookup failed", it) }
            resolving -= wanted.toSet()
            updateFromRemote()
        }
    }

    private fun updateFromRemote() {
        val session = currentSession ?: return
        val client = session.remoteMediaClient ?: return
        val mediaStatus = client.mediaStatus
        val playerState = mediaStatus?.playerState
        val receiver = receiverQueue(client)
        val now = System.currentTimeMillis()
        expectation?.let { if (now >= it.untilMs) expectation = null }
        val before = _state.value
        when (val sync = CastQueueReconciler.sync(receiver, before.queue, before.currentIndex, expectation, now)) {
            is QueueSync.NotOurs -> {
                if (lastNotOurs != sync.ownership) {
                    lastNotOurs = sync.ownership
                    _state.value = before.copy(
                        isPlaying = false,
                        transportState = "STOPPED",
                        status = if (sync.ownership == ReceiverOwnership.JAMARR_SERVER) {
                            "The Jamarr server is playing on this device"
                        } else {
                            "Another app is playing on this device"
                        },
                    )
                }
                passiveAttach = false
                return
            }
            is QueueSync.Adopt -> {
                if (sync.expectationMet) expectation = null
                lastNotOurs = null
                _state.value = before.copy(
                    queue = sync.tracks,
                    currentIndex = sync.currentIndex,
                    durationSeconds = sync.tracks.getOrNull(sync.currentIndex)?.durationSeconds
                        ?: before.durationSeconds,
                )
                if (sync.queueChanged) {
                    Log.i(TAG, "Adopted the receiver's queue (${sync.tracks.size} tracks)")
                }
                if (passiveAttach) {
                    passiveAttach = false
                    _resumedRendererId.value = _state.value.activeRendererId
                }
            }
            QueueSync.Keep -> Unit
        }
        val transport = when (playerState) {
            MediaStatus.PLAYER_STATE_PLAYING, MediaStatus.PLAYER_STATE_BUFFERING -> "PLAYING"
            MediaStatus.PLAYER_STATE_PAUSED -> "PAUSED"
            MediaStatus.PLAYER_STATE_IDLE -> "IDLE"
            else -> _state.value.transportState
        }
        val current = _state.value
        if (expectation != null) {
            // Our load is still landing; the status is about the old media.
            return
        }
        val activeIndex = current.currentIndex
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

    private fun selectedRouteRendererId(): String? =
        mediaRouter?.selectedRoute
            ?.takeIf { it.matchesSelector(selector) && !it.isDefault }
            ?.let(this::routeRendererId)

    private suspend fun <T> withRemote(block: RemoteMediaClient.() -> T?): T? =
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

    private fun routeRendererId(route: MediaRouter.RouteInfo): String =
        "cast:${route.id.ifBlank { route.name.toString() }}"

    private fun isPlayServicesAvailable(): Boolean =
        GoogleApiAvailability.getInstance()
            .isGooglePlayServicesAvailable(appContext.applicationContext) == ConnectionResult.SUCCESS

    private fun setStatus(message: String) {
        _state.value = _state.value.copy(status = message)
    }
}
