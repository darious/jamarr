package com.jamarr.android.ui

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jamarr.android.BuildConfig
import com.jamarr.android.auth.SettingsStore
import com.jamarr.android.auth.TokenHolder
import com.jamarr.android.data.HomeContent
import com.jamarr.android.data.JamarrApiClient
import com.jamarr.android.data.JamarrCookieJar
import com.jamarr.android.data.PlayerStateResponse
import com.jamarr.android.data.Renderer
import com.jamarr.android.data.SearchResponse
import com.jamarr.android.data.SearchTrack
import com.jamarr.android.playback.JamarrPlaybackController
import com.jamarr.android.playback.ResolvedTrack
import com.jamarr.android.ui.nav.JamarrTab
import com.jamarr.android.ui.nav.Routes
import com.jamarr.android.ui.nav.route
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class JamarrViewModel(application: Application) : AndroidViewModel(application) {
    private val settingsStore = SettingsStore(application)
    val tokenHolder = TokenHolder()
    private val cookieJar = JamarrCookieJar(settingsStore)
    val apiClient = JamarrApiClient(
        tokenHolder = tokenHolder,
        cookieJar = cookieJar,
        onTokenRefreshed = { newToken -> settingsStore.saveAccessToken(newToken) },
        onRefreshFailed = {
            settingsStore.clearAccessToken()
            cookieJar.clear()
        },
    )
    val playbackController = JamarrPlaybackController(application)

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
    var shuffleEnabled by mutableStateOf(false)
    var repeatMode by mutableStateOf(0)
    var showNowPlaying by mutableStateOf(false)
    var clientId by mutableStateOf("")

    // Renderer / remote playback state
    var renderers by mutableStateOf<List<Renderer>>(emptyList())
    var activeRendererUdn by mutableStateOf("")
    var showRendererPicker by mutableStateOf(false)
    val isRemoteMode: Boolean get() = activeRendererUdn.isNotBlank() && !activeRendererUdn.startsWith("local:")
    val activeRendererName: String get() {
        if (!isRemoteMode) return "This Device"
        return renderers.find { it.udn == activeRendererUdn }?.name ?: "Network Renderer"
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
            while (true) {
                isPlaying = playbackController.isPlaying
                playbackPosition = playbackController.currentPosition
                playbackDuration = playbackController.duration
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

        // Remote playback state polling
        viewModelScope.launch {
            while (true) {
                if (isRemoteMode && isPlaying) {
                    runCatching {
                        val state = apiClient.getPlayerState(serverUrl, clientId)
                        playbackPosition = (state.positionSeconds * 1000).toLong()
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
                        if (currentTrack != null && currentTrack.track.id != nowPlayingTrack?.id) {
                            nowPlayingTrack = currentTrack.track
                            nowPlayingArtworkUrl = currentTrack.artworkUrl
                        }
                        if (currentTrack != null) {
                            playbackDuration = ((currentTrack.track.durationSeconds ?: 0.0) * 1000).toLong()
                        }
                    }
                }
                delay(1000)
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        playbackController.release()
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
        if (isRemoteMode) {
            viewModelScope.launch {
                runCatching { apiClient.remoteClearQueue(serverUrl, clientId) }
            }
        } else {
            playbackController.stop()
        }
        nowPlayingTrack = null
        nowPlayingArtworkUrl = null
        playbackQueue = emptyList()
        isPlaying = false
        playbackPosition = 0L
        showNowPlaying = false
    }

    fun togglePlayPause() {
        if (isRemoteMode) {
            viewModelScope.launch {
                if (isPlaying) {
                    runCatching { apiClient.remotePause(serverUrl, clientId) }
                        .onSuccess { isPlaying = false }
                } else {
                    runCatching { apiClient.remoteResume(serverUrl, clientId) }
                        .onSuccess { isPlaying = true }
                }
            }
        } else {
            playbackController.togglePlayPause()
        }
    }

    fun seekTo(positionMs: Long) {
        if (isRemoteMode) {
            viewModelScope.launch {
                runCatching { apiClient.remoteSeek(serverUrl, clientId, positionMs / 1000.0) }
            }
        } else {
            playbackController.seekTo(positionMs)
        }
    }

    fun skipNext() {
        if (isRemoteMode) {
            val queue = playbackQueue
            if (queue.isEmpty()) return
            val currentIndex = queue.indexOfFirst { it.track.id == nowPlayingTrack?.id }.coerceAtLeast(0)
            val nextIndex = (currentIndex + 1).coerceAtMost(queue.lastIndex)
            if (nextIndex != currentIndex) {
                viewModelScope.launch {
                    runCatching { apiClient.reportIndex(serverUrl, clientId, nextIndex) }
                }
            }
        } else {
            playbackController.next()
        }
    }

    fun skipPrevious() {
        if (isRemoteMode) {
            val queue = playbackQueue
            if (queue.isEmpty()) return
            val currentIndex = queue.indexOfFirst { it.track.id == nowPlayingTrack?.id }.coerceAtLeast(0)
            val prevIndex = (currentIndex - 1).coerceAtLeast(0)
            if (prevIndex != currentIndex) {
                viewModelScope.launch {
                    runCatching { apiClient.reportIndex(serverUrl, clientId, prevIndex) }
                }
            }
        } else {
            playbackController.previous()
        }
    }

    fun playQueueItem(index: Int) {
        if (isRemoteMode) {
            viewModelScope.launch {
                runCatching { apiClient.reportIndex(serverUrl, clientId, index) }
            }
        } else {
            playbackController.playQueueItem(index)
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
        viewModelScope.launch {
            runCatching { apiClient.getRenderers(serverUrl, refresh = true) }
                .onSuccess { renderers = it }
                .onFailure { status = "Renderer scan: ${it.message}" }
        }
    }

    private fun loadCachedRenderers() {
        viewModelScope.launch {
            runCatching { apiClient.getRenderers(serverUrl, refresh = false) }
                .onSuccess { renderers = it }
        }
    }

    fun setRenderer(udn: String) {
        viewModelScope.launch {
            runCatching { apiClient.setRenderer(serverUrl, clientId, udn) }
                .onSuccess {
                    activeRendererUdn = udn
                    showRendererPicker = false
                }
                .onFailure { status = it.message ?: "Failed to set renderer" }
        }
    }
}
