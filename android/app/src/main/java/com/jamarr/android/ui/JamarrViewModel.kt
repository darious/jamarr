package com.jamarr.android.ui

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jamarr.android.BuildConfig
import com.jamarr.android.JamarrApplication
import com.jamarr.android.auth.SettingsStore
import com.jamarr.android.data.HomeContent
import com.jamarr.android.data.JamarrApiClient
import com.jamarr.android.data.PlayerStateResponse
import com.jamarr.android.data.Renderer
import com.jamarr.android.data.SearchResponse
import com.jamarr.android.data.SearchTrack
import com.jamarr.android.playback.JamarrPlaybackController
import com.jamarr.android.playback.ResolvedTrack
import com.jamarr.android.cast.CastDeviceController
import com.jamarr.android.renderer.DeviceRendererController
import com.jamarr.android.renderer.DeviceRendererInfo
import com.jamarr.android.renderer.QueuedTrack
import com.jamarr.android.ui.nav.JamarrTab
import com.jamarr.android.ui.nav.Routes
import com.jamarr.android.ui.nav.route
import com.jamarr.android.upnp.UpnpDeviceController
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

class JamarrViewModel(application: Application) : AndroidViewModel(application) {
    private val app = application as JamarrApplication
    private val settingsStore = SettingsStore(application)
    val tokenHolder = app.tokenHolder
    private val cookieJar = app.cookieJar
    val apiClient = JamarrApiClient(
        tokenHolder = tokenHolder,
        cookieJar = cookieJar,
        onTokenRefreshed = { newToken -> settingsStore.saveAccessToken(newToken) },
        onRefreshFailed = {
            settingsStore.clearAccessToken()
        },
        onForceLogout = {
            settingsStore.clearAccessToken()
            cookieJar.clear()
        },
    )
    val playbackController = JamarrPlaybackController(application)
    val upnpController = UpnpDeviceController(application)
    val castController = CastDeviceController(application)

    // Auth state
    var serverUrl by mutableStateOf(BuildConfig.DEFAULT_SERVER_URL)
    var username by mutableStateOf("")
    var password by mutableStateOf("")
    var status by mutableStateOf("Connect to Jamarr.")
    var busy by mutableStateOf(false)

    // Content state
    var homeContent by mutableStateOf(HomeContent())
    var query by mutableStateOf("")
    var searchResults by mutableStateOf(SearchResponse())

    // Playback state
    var nowPlayingTrack by mutableStateOf<SearchTrack?>(null)
    var nowPlayingArtworkUrl by mutableStateOf<String?>(null)
    var isPlaying by mutableStateOf(false)
    var playbackPosition by mutableStateOf(0L)
    var playbackDuration by mutableStateOf(0L)
    var playbackQueue by mutableStateOf<List<ResolvedTrack>>(emptyList())
    var originalQualityLabel by mutableStateOf("Original")
    var playbackQualityLabel by mutableStateOf("Original")
    var shuffleEnabled by mutableStateOf(false)
    var repeatMode by mutableStateOf(0)
    var showNowPlaying by mutableStateOf(false)
    var clientId by mutableStateOf("")

    // Renderer / remote playback state
    var renderers by mutableStateOf<List<Renderer>>(emptyList())
    var deviceRenderers by mutableStateOf<List<DeviceRendererInfo>>(emptyList())
    var activeRendererUdn by mutableStateOf("")
    var showRendererPicker by mutableStateOf(false)
    var remoteVolume by mutableStateOf(0)
    var useDeviceUpnp by mutableStateOf(false)
    var activeRendererSource by mutableStateOf(RendererSource.SERVER)
    val isRemoteMode: Boolean get() = activeRendererUdn.isNotBlank() && !activeRendererUdn.startsWith("local:")
    val isDeviceRenderer: Boolean get() = isRemoteMode && activeRendererSource == RendererSource.DEVICE
    val isDeviceUpnp: Boolean get() = isDeviceRenderer && activeRendererUdn.startsWith("upnp:")
    val isDeviceCast: Boolean get() = isDeviceRenderer && activeRendererUdn.startsWith("cast:")
    val activeRendererName: String get() {
        if (!isRemoteMode) return "This Device"
        return when (activeRendererSource) {
            RendererSource.DEVICE -> deviceRenderers.find { it.rendererId == activeRendererUdn }?.name ?: "Network Renderer"
            RendererSource.SERVER -> renderers.find { it.activeKey == activeRendererUdn || it.udn == activeRendererUdn }?.name ?: "Network Renderer"
        }
    }

    // Navigation restore
    var initialRestoreDone by mutableStateOf(false)
    var pendingSavedRoute by mutableStateOf<String?>(null)

    init {
        viewModelScope.launch {
            cookieJar.prime()
            clientId = settingsStore.getClientId()
            activeRendererUdn = "local:$clientId"
            val saved = settingsStore.load()
            serverUrl = saved.serverUrl.ifBlank { BuildConfig.DEFAULT_SERVER_URL }
            useDeviceUpnp = saved.useDeviceUpnp
            if (useDeviceUpnp) startDeviceControllers()
            if (saved.accessToken.isNotBlank()) {
                tokenHolder.set(saved.accessToken)
                status = "Welcome back."
                refreshHome()
                loadCachedRenderers()
                if (!initialRestoreDone) {
                    initialRestoreDone = true
                    val savedRoute = JamarrTab.fromIndex(saved.activeTabIndex).route()
                    if (savedRoute != Routes.HOME) {
                        pendingSavedRoute = savedRoute
                    }
                }
            }
        }

        viewModelScope.launch {
            upnpController.renderers.collectLatest { updateDeviceRenderers() }
        }

        viewModelScope.launch {
            castController.renderers.collectLatest { updateDeviceRenderers() }
        }

        // Periodic progress + index reporter for device-upnp mode.
        // Drives server-side history logging (threshold: 30s or 20%).
        viewModelScope.launch {
            var lastIndex = -1
            var lastReport = 0L
            while (true) {
                if (isDeviceRenderer && clientId.isNotBlank()) {
                    val st = activeDeviceController()?.state?.value
                    if (st == null) {
                        delay(1000)
                        continue
                    }
                    if (st.currentIndex >= 0 && st.currentIndex != lastIndex) {
                        lastIndex = st.currentIndex
                        runCatching { apiClient.reportIndex(serverUrl, clientId, st.currentIndex) }
                    }
                    val now = System.currentTimeMillis()
                    if (st.isPlaying && now - lastReport >= 5000) {
                        lastReport = now
                        runCatching {
                            apiClient.reportProgress(
                                serverUrl, clientId,
                                positionSeconds = st.positionSeconds,
                                isPlaying = true,
                            )
                        }
                    }
                }
                delay(1000)
            }
        }

        viewModelScope.launch {
            upnpController.state.collectLatest { st ->
                if (isDeviceUpnp) applyDevicePlaybackState(st)
            }
        }

        viewModelScope.launch {
            castController.state.collectLatest { st ->
                if (isDeviceCast) applyDevicePlaybackState(st)
            }
        }

        viewModelScope.launch {
            while (true) {
                if (isRemoteMode) {
                    delay(500)
                    continue
                }
                isPlaying = playbackController.isPlaying
                playbackPosition = playbackController.currentPosition
                playbackDuration = playbackController.duration
                originalQualityLabel = playbackController.originalQualityLabel
                playbackQualityLabel = playbackController.streamQualityLabel
                shuffleEnabled = playbackController.shuffleEnabled
                repeatMode = playbackController.repeatMode
                val controllerCount = playbackController.mediaItemCount
                if (controllerCount > 0) {
                    val snapshot = playbackController.currentQueueSnapshot()
                    if (snapshot != playbackQueue) playbackQueue = snapshot
                } else if (playbackQueue.isNotEmpty()) {
                    playbackQueue = emptyList()
                }
                val mediaId = playbackController.currentMediaId
                if (mediaId != null && mediaId != nowPlayingTrack?.id?.toString()) {
                    val current = playbackQueue.find { it.track.id.toString() == mediaId }
                    if (current != null) {
                        nowPlayingTrack = current.track
                        nowPlayingArtworkUrl = current.artworkUrl
                    } else {
                        val item = playbackController.currentMediaItem
                        val md = item?.mediaMetadata
                        if (md != null) {
                            nowPlayingTrack = SearchTrack(
                                id = mediaId.toLongOrNull() ?: 0L,
                                title = md.title?.toString().orEmpty(),
                                artist = md.artist?.toString(),
                                album = md.albumTitle?.toString(),
                            )
                            nowPlayingArtworkUrl = md.artworkUri?.toString()
                        }
                    }
                }
                delay(500)
            }
        }

        // Remote playback state polling — runs while in remote mode.
        // Server's is_playing/position drive UI; do not gate on local isPlaying
        // (UPnP renderer takes ~3s to reach PLAYING after Play command).
        viewModelScope.launch {
            while (true) {
                if (isRemoteMode && !isDeviceRenderer) {
                    refreshServerPlaybackState()
                }
                delay(2000)
            }
        }

        // Local ticker: interpolate progress between remote polls for smooth UI.
        viewModelScope.launch {
            val tick = 250L
            while (true) {
                if (isRemoteMode && isPlaying) {
                    val dur = playbackDuration
                    val next = playbackPosition + tick
                    playbackPosition = if (dur > 0) next.coerceAtMost(dur) else next
                }
                delay(tick)
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        playbackController.release()
        upnpController.stop()
        castController.stop()
    }

    private fun startDeviceControllers() {
        upnpController.start()
        castController.start()
    }

    private fun updateDeviceRenderers() {
        deviceRenderers = (upnpController.renderers.value + castController.renderers.value)
            .sortedWith(compareBy<DeviceRendererInfo> { it.kind }.thenBy { it.name.lowercase() })
    }

    private fun activeDeviceController(): DeviceRendererController? =
        when {
            activeRendererUdn.startsWith("upnp:") -> upnpController
            activeRendererUdn.startsWith("cast:") -> castController
            else -> null
        }

    private fun applyDevicePlaybackState(st: com.jamarr.android.renderer.DeviceRendererPlaybackState) {
        playbackPosition = (st.positionSeconds * 1000).toLong()
        val durMs = (st.durationSeconds * 1000).toLong()
        if (durMs > 0) playbackDuration = durMs
        isPlaying = st.isPlaying
        remoteVolume = st.volumePercent
        st.status?.let { status = it }
        val q = st.queue.map { qt ->
            ResolvedTrack(
                track = SearchTrack(
                    id = qt.id,
                    title = qt.title,
                    artist = qt.artist,
                    album = qt.album,
                    durationSeconds = qt.durationSeconds,
                ),
                streamUrl = qt.streamUrl,
                artworkUrl = qt.artUrl,
            )
        }
        if (q != playbackQueue) playbackQueue = q
        val cur = q.getOrNull(st.currentIndex)
        if (cur != null && cur.track.id != nowPlayingTrack?.id) {
            nowPlayingTrack = cur.track
            nowPlayingArtworkUrl = cur.artworkUrl
        }
    }

    private suspend fun refreshServerPlaybackState() {
        runCatching {
            apiClient.getPlayerState(serverUrl, clientId)
        }.onSuccess { state ->
            applyServerPlaybackState(state)
        }.onFailure {
            status = "Remote poll: ${it.message}"
        }
    }

    private fun applyServerPlaybackState(state: PlayerStateResponse) {
        val active = state.rendererId ?: state.renderer
        if (active.isNotBlank()) {
            activeRendererUdn = active
            activeRendererSource = RendererSource.SERVER
        }

        playbackPosition = (state.positionSeconds * 1000).toLong()
        remoteVolume = state.volume ?: remoteVolume
        isPlaying = state.isPlaying

        val q = state.queue.map { t ->
            ResolvedTrack(
                track = SearchTrack(
                    id = t.id,
                    title = t.title,
                    artist = t.artist,
                    album = t.album,
                    artSha1 = t.artSha1,
                    durationSeconds = t.durationSeconds,
                    mbReleaseId = t.mbReleaseId,
                ),
                streamUrl = "",
                artworkUrl = t.artSha1?.let { apiClient.artworkUrl(serverUrl, it) },
            )
        }
        if (q != playbackQueue) playbackQueue = q

        val currentTrack = q.getOrNull(state.currentIndex)
        if (currentTrack != null) {
            val dur = ((currentTrack.track.durationSeconds ?: 0.0) * 1000).toLong()
            if (dur > 0) playbackDuration = dur
            if (currentTrack.track.id != nowPlayingTrack?.id) {
                nowPlayingTrack = currentTrack.track
                nowPlayingArtworkUrl = currentTrack.artworkUrl
            }
        } else if (q.isEmpty()) {
            nowPlayingTrack = null
            nowPlayingArtworkUrl = null
            playbackDuration = 0L
            playbackPosition = 0L
        }
    }

    fun refreshHome() {
        val token = tokenHolder.get()
        if (serverUrl.isBlank() || token.isBlank()) return
        viewModelScope.launch {
            runCatching { apiClient.home(serverUrl, token) }
                .onSuccess { homeContent = it }
                .onFailure { status = it.message ?: "Failed to load home." }
        }
    }

    fun runSearch() {
        val token = tokenHolder.get()
        if (serverUrl.isBlank() || token.isBlank() || query.trim().length < 2) return
        viewModelScope.launch {
            runCatching { apiClient.search(serverUrl, token, query.trim()) }
                .onSuccess { searchResults = it }
                .onFailure { status = it.message ?: "Search failed." }
        }
    }

    suspend fun playTracks(queue: List<SearchTrack>, startIndex: Int) {
        if (queue.isEmpty()) return

        if (isDeviceRenderer) {
            playbackController.clearQueue()
            // Tell server the queue (under local renderer state) so server-side history
            // logging picks up our progress reports.
            if (clientId.isNotBlank()) {
                runCatching { apiClient.reportQueue(serverUrl, clientId, queue, startIndex) }
            }
            val token = tokenHolder.get()
            val startIdx = startIndex.coerceIn(0, queue.lastIndex)
            val rendererKind = activeDeviceController()?.kind
            val tracks = queue.map { t ->
                QueuedTrack(
                    id = t.id,
                    title = t.title,
                    artist = t.artist ?: "Unknown Artist",
                    album = t.album ?: "Unknown Album",
                    mime = guessMime(t),
                    durationSeconds = t.durationSeconds ?: 0.0,
                    streamUrl = apiClient.streamUrl(serverUrl, token, t.id, rendererKind),
                    artUrl = t.artSha1?.let { apiClient.artworkUrl(serverUrl, it, maxSize = 600) },
                )
            }
            val startTrack = queue[startIdx]
            nowPlayingTrack = startTrack
            nowPlayingArtworkUrl = startTrack.artSha1?.let { apiClient.artworkUrl(serverUrl, it) }
            isPlaying = true
            playbackPosition = 0L
            playbackDuration = ((startTrack.durationSeconds ?: 0.0) * 1000).toLong()
            activeDeviceController()?.playQueue(tracks, startIdx)
            return
        }

        if (clientId.isNotBlank()) {
            apiClient.reportQueue(serverUrl, clientId, queue, startIndex)
        }

        if (isRemoteMode) {
            playbackController.clearQueue()
            val startTrack = queue[startIndex.coerceIn(0, queue.lastIndex)]
            nowPlayingTrack = startTrack
            nowPlayingArtworkUrl = startTrack.artSha1?.let { apiClient.artworkUrl(serverUrl, it) }
            isPlaying = true
            playbackPosition = 0L
            playbackDuration = ((startTrack.durationSeconds ?: 0.0) * 1000).toLong()
            if (clientId.isNotBlank()) {
                apiClient.remotePlay(serverUrl, clientId, startTrack.id)
                refreshServerPlaybackState()
            }
        } else {
            val resolved = queue.map { queueTrack ->
                ResolvedTrack(
                    track = queueTrack,
                    streamUrl = "",
                    artworkUrl = apiClient.artworkUrl(serverUrl, queueTrack.artSha1),
                )
            }
            playbackQueue = resolved
            playbackController.playQueue(resolved, startIndex.coerceIn(0, resolved.lastIndex))
            val startTrack = resolved[startIndex.coerceIn(0, resolved.lastIndex)]
            nowPlayingTrack = startTrack.track
            nowPlayingArtworkUrl = startTrack.artworkUrl
        }
    }

    fun playTrack(track: SearchTrack, queue: List<SearchTrack> = listOf(track)) {
        viewModelScope.launch {
            busy = true
            val startIndex = queue.indexOfFirst { it.id == track.id }.coerceAtLeast(0)
            runCatching { playTracks(queue, startIndex) }
                .onFailure { status = it.message ?: "Playback failed." }
            busy = false
        }
    }

    fun playQueueFromUi(queue: List<SearchTrack>, startIndex: Int) {
        viewModelScope.launch {
            runCatching { playTracks(queue, startIndex) }
                .onFailure { status = it.message ?: "Playback failed." }
        }
    }

    fun login() {
        viewModelScope.launch {
            busy = true
            status = "Logging in…"
            runCatching {
                val normalized = apiClient.normalizeServerUrl(serverUrl)
                val response = apiClient.login(normalized, username, password)
                settingsStore.saveServerUrl(normalized)
                settingsStore.saveAccessToken(response.accessToken)
                serverUrl = normalized
                tokenHolder.set(response.accessToken)
                password = ""
            }
                .onSuccess {
                    status = "Signed in."
                    refreshHome()
                }
                .onFailure { status = it.message ?: "Login failed." }
            busy = false
        }
    }

    fun logout() {
        viewModelScope.launch {
            runCatching { apiClient.logout(serverUrl) }
            settingsStore.clearAccessToken()
            cookieJar.clear()
            tokenHolder.clear()
            playbackController.stop()
            homeContent = HomeContent()
            searchResults = SearchResponse()
            renderers = emptyList()
            activeRendererUdn = ""
            query = ""
            nowPlayingTrack = null
            nowPlayingArtworkUrl = null
            playbackQueue = emptyList()
            isPlaying = false
            status = "Signed out."
        }
    }

    fun saveActiveTab(index: Int) {
        viewModelScope.launch { settingsStore.saveActiveTab(index) }
    }

    fun stopPlayback() {
        when {
            isDeviceRenderer -> viewModelScope.launch { runCatching { activeDeviceController()?.stopPlayback() } }
            isRemoteMode -> viewModelScope.launch {
                runCatching { apiClient.remoteClearQueue(serverUrl, clientId) }
                    .onSuccess { refreshServerPlaybackState() }
            }
            else -> playbackController.stop()
        }
        nowPlayingTrack = null
        nowPlayingArtworkUrl = null
        playbackQueue = emptyList()
        isPlaying = false
        playbackPosition = 0L
        showNowPlaying = false
    }

    fun togglePlayPause() {
        when {
            isDeviceRenderer -> viewModelScope.launch {
                val controller = activeDeviceController() ?: return@launch
                if (isPlaying) runCatching { controller.pause() }.onSuccess { isPlaying = false }
                else runCatching { controller.resume() }.onSuccess { isPlaying = true }
            }
            isRemoteMode -> viewModelScope.launch {
                if (isPlaying) {
                    runCatching { apiClient.remotePause(serverUrl, clientId) }
                        .onSuccess {
                            isPlaying = false
                            refreshServerPlaybackState()
                        }
                } else {
                    runCatching { apiClient.remoteResume(serverUrl, clientId) }
                        .onSuccess {
                            isPlaying = true
                            refreshServerPlaybackState()
                        }
                }
            }
            else -> playbackController.togglePlayPause()
        }
    }

    fun seekTo(positionMs: Long) {
        when {
            isDeviceRenderer -> viewModelScope.launch {
                runCatching { activeDeviceController()?.seek(positionMs / 1000.0) }
            }
            isRemoteMode -> viewModelScope.launch {
                runCatching { apiClient.remoteSeek(serverUrl, clientId, positionMs / 1000.0) }
                    .onSuccess {
                        playbackPosition = positionMs.coerceAtLeast(0L)
                        refreshServerPlaybackState()
                    }
            }
            else -> playbackController.seekTo(positionMs)
        }
    }

    fun skipNext() {
        when {
            isDeviceRenderer -> viewModelScope.launch { runCatching { activeDeviceController()?.next() } }
            isRemoteMode -> {
                val queue = playbackQueue
                if (queue.isEmpty()) return
                val currentIndex = queue.indexOfFirst { it.track.id == nowPlayingTrack?.id }.coerceAtLeast(0)
                val nextIndex = (currentIndex + 1).coerceAtMost(queue.lastIndex)
                if (nextIndex != currentIndex) {
                    viewModelScope.launch {
                        runCatching { apiClient.reportIndex(serverUrl, clientId, nextIndex) }
                            .onSuccess { refreshServerPlaybackState() }
                    }
                }
            }
            else -> playbackController.next()
        }
    }

    fun skipPrevious() {
        when {
            isDeviceRenderer -> viewModelScope.launch { runCatching { activeDeviceController()?.previous() } }
            isRemoteMode -> {
                val queue = playbackQueue
                if (queue.isEmpty()) return
                val currentIndex = queue.indexOfFirst { it.track.id == nowPlayingTrack?.id }.coerceAtLeast(0)
                val prevIndex = (currentIndex - 1).coerceAtLeast(0)
                if (prevIndex != currentIndex) {
                    viewModelScope.launch {
                        runCatching { apiClient.reportIndex(serverUrl, clientId, prevIndex) }
                            .onSuccess { refreshServerPlaybackState() }
                    }
                }
            }
            else -> playbackController.previous()
        }
    }

    fun playQueueItem(index: Int) {
        when {
            isDeviceRenderer -> viewModelScope.launch { runCatching { activeDeviceController()?.jumpTo(index) } }
            isRemoteMode -> viewModelScope.launch {
                runCatching { apiClient.reportIndex(serverUrl, clientId, index) }
                    .onSuccess { refreshServerPlaybackState() }
            }
            else -> playbackController.playQueueItem(index)
        }
    }

    fun toggleShuffle() {
        if (!isRemoteMode) {
            playbackController.toggleShuffle()
        }
    }

    fun cycleRepeatMode() {
        if (!isRemoteMode) {
            playbackController.cycleRepeatMode()
        }
    }

    fun refreshRenderers() {
        if (useDeviceUpnp) {
            upnpController.search()
            castController.search()
        } else {
            viewModelScope.launch {
                runCatching { apiClient.getRenderers(serverUrl, refresh = true) }
                    .onSuccess { renderers = it }
                    .onFailure { status = "Renderer scan: ${it.message}" }
            }
        }
    }

    private fun loadCachedRenderers() {
        viewModelScope.launch {
            runCatching { apiClient.getRenderers(serverUrl, refresh = false) }
                .onSuccess { renderers = it }
                .onFailure { status = "Renderer load: ${it.message}" }
        }
    }

    fun setRenderer(udn: String, source: RendererSource = RendererSource.SERVER) {
        when (source) {
            RendererSource.DEVICE -> {
                val rendererId = if (udn.contains(":")) udn else "upnp:$udn"
                val controller = when {
                    rendererId.startsWith("cast:") -> castController
                    rendererId.startsWith("upnp:") -> upnpController
                    else -> null
                }
                controller?.selectRenderer(rendererId)
                activeRendererUdn = rendererId
                activeRendererSource = RendererSource.DEVICE
                remoteVolume = 0
                showRendererPicker = false
                // Pin server's active renderer to local so history/scrobble path runs
                // off this client's progress reports (server-side UPnP monitor would conflict).
                viewModelScope.launch {
                    runCatching { apiClient.setRenderer(serverUrl, clientId, "local:$clientId") }
                }
            }
            RendererSource.SERVER -> {
                viewModelScope.launch {
                    runCatching { apiClient.setRenderer(serverUrl, clientId, udn) }
                        .onSuccess {
                            activeRendererUdn = udn
                            activeRendererSource = RendererSource.SERVER
                            remoteVolume = 0
                            showRendererPicker = false
                            refreshServerPlaybackState()
                        }
                        .onFailure { status = it.message ?: "Failed to set renderer" }
                }
            }
        }
    }

    fun selectLocalRenderer() {
        activeRendererUdn = "local:$clientId"
        activeRendererSource = RendererSource.SERVER
        showRendererPicker = false
        viewModelScope.launch {
            runCatching { apiClient.setRenderer(serverUrl, clientId, "local:$clientId") }
        }
    }

    fun toggleUseDeviceUpnp(enabled: Boolean) {
        useDeviceUpnp = enabled
        viewModelScope.launch { settingsStore.saveUseDeviceUpnp(enabled) }
        if (enabled) {
            startDeviceControllers()
        } else {
            upnpController.stop()
            castController.stop()
            if (isDeviceRenderer) {
                activeRendererUdn = "local:$clientId"
                activeRendererSource = RendererSource.SERVER
            }
        }
    }

    fun changeRemoteVolume(percent: Int) {
        viewModelScope.launch {
            remoteVolume = percent.coerceIn(0, 100)
            if (isDeviceRenderer) {
                runCatching { activeDeviceController()?.setVolumePercent(percent) }
                    .onFailure { status = "Volume: ${it.message}" }
            } else {
                runCatching { apiClient.remoteVolume(serverUrl, clientId, percent) }
                    .onSuccess { refreshServerPlaybackState() }
                    .onFailure { status = "Volume: ${it.message}" }
            }
        }
    }

    private fun guessMime(t: SearchTrack): String {
        // SearchTrack doesn't carry MIME; default flac (server transcodes if needed via DLNA fallback).
        return "audio/flac"
    }
}

enum class RendererSource { SERVER, DEVICE }
