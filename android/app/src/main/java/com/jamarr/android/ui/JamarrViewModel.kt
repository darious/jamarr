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

    // Navigation restore
    var initialRestoreDone by mutableStateOf(false)
    var pendingSavedRoute by mutableStateOf<String?>(null)

    init {
        viewModelScope.launch {
            cookieJar.prime()
            clientId = settingsStore.getClientId()
            val saved = settingsStore.load()
            serverUrl = saved.serverUrl.ifBlank { BuildConfig.DEFAULT_SERVER_URL }
            if (saved.accessToken.isNotBlank()) {
                tokenHolder.set(saved.accessToken)
                status = "Welcome back."
                refreshHome()
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

        if (clientId.isNotBlank()) {
            apiClient.reportQueue(serverUrl, clientId, queue, startIndex)
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
            query = ""
            nowPlayingTrack = null
            nowPlayingArtworkUrl = null
            playbackQueue = emptyList()
            status = "Signed out."
        }
    }

    fun saveActiveTab(index: Int) {
        viewModelScope.launch { settingsStore.saveActiveTab(index) }
    }

    fun stopPlayback() {
        playbackController.stop()
        nowPlayingTrack = null
        nowPlayingArtworkUrl = null
        playbackQueue = emptyList()
        showNowPlaying = false
    }
}
