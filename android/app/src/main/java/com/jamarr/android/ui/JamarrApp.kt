package com.jamarr.android.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.jamarr.android.auth.SettingsStore
import com.jamarr.android.auth.TokenHolder
import com.jamarr.android.data.HomeAlbum
import com.jamarr.android.data.HomeArtist
import com.jamarr.android.data.HomeContent
import com.jamarr.android.data.JamarrApiClient
import com.jamarr.android.data.JamarrCookieJar
import com.jamarr.android.data.SearchResponse
import com.jamarr.android.data.SearchTrack
import com.jamarr.android.playback.JamarrPlaybackController
import com.jamarr.android.playback.ResolvedTrack
import com.jamarr.android.ui.components.MiniPlayer
import com.jamarr.android.ui.nav.BottomNavBar
import com.jamarr.android.ui.nav.JamarrTab
import com.jamarr.android.ui.nav.Routes
import com.jamarr.android.ui.nav.isRootRoute
import com.jamarr.android.ui.nav.route
import com.jamarr.android.ui.nav.routeToTab
import com.jamarr.android.ui.screens.AlbumDetailScreen
import com.jamarr.android.ui.screens.ArtistDetailScreen
import com.jamarr.android.ui.screens.ChartsScreen
import com.jamarr.android.ui.screens.HistoryScreen
import com.jamarr.android.ui.screens.HomeScreen
import com.jamarr.android.ui.screens.LoginScreen
import com.jamarr.android.ui.screens.NowPlayingSheet
import com.jamarr.android.ui.screens.PlaylistDetailScreen
import com.jamarr.android.ui.screens.PlaylistsScreen
import com.jamarr.android.ui.state.JamarrAppContext
import com.jamarr.android.ui.state.LocalJamarrContext
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrTheme
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private const val DEFAULT_SERVER_URL = "https://jamarr.darious.co.uk"

@Composable
fun JamarrApp() {
    JamarrTheme {
        Surface(
            modifier = Modifier.fillMaxSize(),
            color = JamarrColors.Bg,
        ) {
            JamarrRoot()
        }
    }
}

@Composable
private fun JamarrRoot() {
    val context = LocalContext.current
    val settingsStore = remember { SettingsStore(context.applicationContext) }
    val tokenHolder = remember { TokenHolder() }
    val cookieJar = remember { JamarrCookieJar(settingsStore) }
    val apiClient = remember {
        JamarrApiClient(
            tokenHolder = tokenHolder,
            cookieJar = cookieJar,
            onTokenRefreshed = { newToken -> settingsStore.saveAccessToken(newToken) },
            onRefreshFailed = {
                settingsStore.clearAccessToken()
                cookieJar.clear()
            },
        )
    }
    val playbackController = remember { JamarrPlaybackController(context.applicationContext) }
    val scope = rememberCoroutineScope()

    var serverUrl by rememberSaveable { mutableStateOf(DEFAULT_SERVER_URL) }
    var username by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    val accessToken by tokenHolder.token.collectAsState()
    var status by rememberSaveable { mutableStateOf("Connect to Jamarr.") }
    var busy by remember { mutableStateOf(false) }

    var homeContent by remember { mutableStateOf(HomeContent()) }
    var query by rememberSaveable { mutableStateOf("") }
    var searchResults by remember { mutableStateOf(SearchResponse()) }

    var nowPlayingTrack by remember { mutableStateOf<SearchTrack?>(null) }
    var nowPlayingArtworkUrl by remember { mutableStateOf<String?>(null) }
    var isPlaying by remember { mutableStateOf(false) }
    var playbackPosition by remember { mutableStateOf(0L) }
    var playbackDuration by remember { mutableStateOf(0L) }
    var playbackQueue by remember { mutableStateOf<List<ResolvedTrack>>(emptyList()) }
    var shuffleEnabled by remember { mutableStateOf(false) }
    var repeatMode by remember { mutableStateOf(0) }
    var showNowPlaying by remember { mutableStateOf(false) }
    var clientId by remember { mutableStateOf("") }

    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route

    fun refreshHome() {
        val token = tokenHolder.get()
        if (serverUrl.isBlank() || token.isBlank()) return
        scope.launch {
            runCatching { apiClient.home(serverUrl, token) }
                .onSuccess { homeContent = it }
                .onFailure { status = it.message ?: "Failed to load home." }
        }
    }

    fun runSearch() {
        val token = tokenHolder.get()
        if (serverUrl.isBlank() || token.isBlank() || query.trim().length < 2) return
        scope.launch {
            runCatching { apiClient.search(serverUrl, token, query.trim()) }
                .onSuccess { searchResults = it }
                .onFailure { status = it.message ?: "Search failed." }
        }
    }

    suspend fun playTracks(queue: List<SearchTrack>, startIndex: Int) {
        if (queue.isEmpty()) return
        val token = tokenHolder.get()
        val resolved = queue.map { queueTrack ->
            ResolvedTrack(
                track = queueTrack,
                streamUrl = apiClient.streamUrl(serverUrl, token, queueTrack.id),
                artworkUrl = apiClient.artworkUrl(serverUrl, queueTrack.artSha1),
            )
        }
        playbackQueue = resolved
        playbackController.playQueue(resolved, startIndex.coerceIn(0, resolved.lastIndex))
        val startTrack = resolved[startIndex.coerceIn(0, resolved.lastIndex)]
        nowPlayingTrack = startTrack.track
        nowPlayingArtworkUrl = startTrack.artworkUrl

        // Report queue to server for history/scrobbling
        if (clientId.isNotBlank()) {
            apiClient.reportQueue(serverUrl, clientId, queue, startIndex)
        }
    }

    fun playTrack(track: SearchTrack, queue: List<SearchTrack> = listOf(track)) {
        scope.launch {
            busy = true
            val startIndex = queue.indexOfFirst { it.id == track.id }.coerceAtLeast(0)
            runCatching { playTracks(queue, startIndex) }
                .onFailure { status = it.message ?: "Playback failed." }
            busy = false
        }
    }

    LaunchedEffect(Unit) {
        cookieJar.prime()
        clientId = settingsStore.getClientId()
        val saved = settingsStore.load()
        serverUrl = saved.serverUrl.ifBlank { DEFAULT_SERVER_URL }
        if (saved.accessToken.isNotBlank()) {
            tokenHolder.set(saved.accessToken)
            status = "Welcome back."
            refreshHome()
            val saved_route = JamarrTab.fromIndex(saved.activeTabIndex).route()
            if (saved_route != Routes.HOME) {
                navController.navigate(saved_route) {
                    popUpTo(Routes.HOME) { inclusive = false }
                    launchSingleTop = true
                }
            }
        }
    }

    LaunchedEffect(currentRoute) {
        routeToTab(currentRoute)?.let { tab ->
            settingsStore.saveActiveTab(tab.ordinal)
        }
    }

    LaunchedEffect(playbackController) {
        var lastProgressReport = 0L
        var lastReportedMediaId: String? = null
        while (true) {
            isPlaying = playbackController.isPlaying
            playbackPosition = playbackController.currentPosition
            playbackDuration = playbackController.duration
            shuffleEnabled = playbackController.shuffleEnabled
            repeatMode = playbackController.repeatMode
            val mediaId = playbackController.currentMediaId
            if (mediaId != null && mediaId != nowPlayingTrack?.id?.toString()) {
                val current = playbackQueue.find { it.track.id.toString() == mediaId }
                if (current != null) {
                    nowPlayingTrack = current.track
                    nowPlayingArtworkUrl = current.artworkUrl
                }
                // Track changed — report new index to server
                if (clientId.isNotBlank() && mediaId != lastReportedMediaId) {
                    lastReportedMediaId = mediaId
                    val newIndex = playbackQueue.indexOfFirst { it.track.id.toString() == mediaId }
                    if (newIndex >= 0) {
                        apiClient.reportIndex(serverUrl, clientId, newIndex)
                    }
                }
            }
            // Report progress every ~5 seconds
            val now = System.currentTimeMillis()
            if (playbackController.isPlaying && clientId.isNotBlank() && now - lastProgressReport >= 5000) {
                lastProgressReport = now
                apiClient.reportProgress(
                    serverUrl, clientId,
                    positionSeconds = playbackPosition / 1000.0,
                    isPlaying = true,
                )
            }
            delay(500)
        }
    }

    DisposableEffect(playbackController) {
        onDispose { playbackController.release() }
    }

    if (accessToken.isBlank()) {
        LoginScreen(
            serverUrl = serverUrl,
            username = username,
            password = password,
            busy = busy,
            status = status,
            onServerUrlChange = { serverUrl = it },
            onUsernameChange = { username = it },
            onPasswordChange = { password = it },
            onSubmit = {
                scope.launch {
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
            },
        )
        return
    }

    val ctx = JamarrAppContext(
        apiClient = apiClient,
        playbackController = playbackController,
        serverUrl = serverUrl,
        accessToken = accessToken,
    )

    CompositionLocalProvider(LocalJamarrContext provides ctx) {
        Box(modifier = Modifier.fillMaxSize().background(JamarrColors.Bg)) {
            val atRoot = isRootRoute(currentRoute)
            val activeTab = routeToTab(currentRoute) ?: JamarrTab.Home
            val navBarHeight = if (atRoot) JamarrDims.BottomNavHeight else 0.dp
            val miniHeight = if (nowPlayingTrack != null) JamarrDims.MiniPlayerHeight else 0.dp
            val contentPadding = PaddingValues(bottom = navBarHeight + miniHeight)

            NavHost(
                navController = navController,
                startDestination = Routes.HOME,
                modifier = Modifier.fillMaxSize(),
            ) {
                composable(Routes.HOME) {
                    HomeScreen(
                        greetingInitial = username.firstOrNull()?.toString().orEmpty(),
                        serverUrl = serverUrl,
                        homeContent = homeContent,
                        searchResults = searchResults,
                        searchQuery = query,
                        onSearchQueryChange = {
                            query = it
                            if (it.isBlank()) searchResults = SearchResponse()
                        },
                        onSearchSubmit = ::runSearch,
                        onAlbumClick = { album ->
                            navController.navigate(
                                Routes.album(
                                    albumMbid = album.albumMbid ?: album.mbReleaseId ?: album.mbid,
                                    album = album.album,
                                    artist = album.artistName,
                                    artistMbid = album.artistMbid,
                                    artSha1 = album.artSha1,
                                ),
                            )
                        },
                        onArtistClick = { artist ->
                            navController.navigate(
                                Routes.artist(
                                    mbid = artist.mbid,
                                    name = artist.name,
                                    artSha1 = artist.artSha1,
                                ),
                            )
                        },
                        onTrackClick = { track ->
                            playTrack(track, searchResults.tracks.ifEmpty { listOf(track) })
                        },
                        onSearchArtistClick = { artistMbid, artistName ->
                            navController.navigate(Routes.artist(mbid = artistMbid, name = artistName))
                        },
                        onSearchAlbumClick = { albumMbid, albumTitle, artistName ->
                            navController.navigate(
                                Routes.album(
                                    albumMbid = albumMbid,
                                    album = albumTitle,
                                    artist = artistName,
                                ),
                            )
                        },
                        onLogout = {
                            scope.launch {
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
                        },
                        artworkUrlForAlbum = { album -> apiClient.artworkUrl(serverUrl, album.artSha1, 400) },
                        artworkUrlForArtist = { artist ->
                            apiClient.artworkUrl(serverUrl, artist.artSha1, 400) ?: artist.imageUrl
                        },
                        contentPadding = contentPadding,
                    )
                }

                composable(Routes.PLAYLISTS) {
                    PlaylistsScreen(
                        onPlaylistClick = { id -> navController.navigate(Routes.playlist(id)) },
                        contentPadding = contentPadding,
                    )
                }

                composable(Routes.CHARTS) {
                    ChartsScreen(
                        onAlbumClick = { chart ->
                            navController.navigate(
                                Routes.album(
                                    albumMbid = chart.localAlbumMbid ?: chart.releaseMbid ?: chart.releaseGroupMbid,
                                    album = chart.localTitle ?: chart.title,
                                    artist = chart.localArtist ?: chart.artist,
                                    artistMbid = chart.artistMbid,
                                ),
                            )
                        },
                        contentPadding = contentPadding,
                    )
                }

                composable(Routes.HISTORY) {
                    HistoryScreen(
                        onArtistClick = { mbid, name ->
                            navController.navigate(Routes.artist(mbid = mbid, name = name))
                        },
                        onAlbumClick = { albumMbid, title, artist ->
                            navController.navigate(
                                Routes.album(albumMbid = albumMbid, album = title, artist = artist),
                            )
                        },
                        onTrackClick = { trackId ->
                            scope.launch {
                                runCatching {
                                    playTracks(
                                        queue = listOf(
                                            SearchTrack(id = trackId, title = ""),
                                        ),
                                        startIndex = 0,
                                    )
                                }
                            }
                        },
                        contentPadding = contentPadding,
                    )
                }

                composable(
                    route = Routes.ARTIST,
                    arguments = listOf(
                        navArgument("mbid") { type = NavType.StringType; defaultValue = "" },
                        navArgument("name") { type = NavType.StringType; defaultValue = "" },
                        navArgument("artSha1") { type = NavType.StringType; defaultValue = "" },
                    ),
                ) { entry ->
                    val mbid = entry.arguments?.getString("mbid").orEmpty()
                    val name = entry.arguments?.getString("name").orEmpty()
                    val artSha1 = entry.arguments?.getString("artSha1").orEmpty()
                    ArtistDetailScreen(
                        initialMbid = mbid.ifBlank { null },
                        initialName = name.ifBlank { null },
                        initialArtSha1 = artSha1.ifBlank { null },
                        onBack = { navController.popBackStack() },
                        onAlbumClick = { album ->
                            navController.navigate(
                                Routes.album(
                                    albumMbid = album.albumMbid ?: album.mbReleaseId,
                                    album = album.album,
                                    artist = album.artistName,
                                    artSha1 = album.artSha1,
                                ),
                            )
                        },
                        onSimilarArtistClick = { mbidSimilar, similarName ->
                            navController.navigate(Routes.artist(mbid = mbidSimilar, name = similarName))
                        },
                        onPlayTrack = { track, queue -> playTrack(track, queue) },
                        contentPadding = contentPadding,
                    )
                }

                composable(
                    route = Routes.ALBUM,
                    arguments = listOf(
                        navArgument("mbid") { type = NavType.StringType; defaultValue = "" },
                        navArgument("album") { type = NavType.StringType; defaultValue = "" },
                        navArgument("artist") { type = NavType.StringType; defaultValue = "" },
                        navArgument("artistMbid") { type = NavType.StringType; defaultValue = "" },
                        navArgument("artSha1") { type = NavType.StringType; defaultValue = "" },
                    ),
                ) { entry ->
                    val albumMbid = entry.arguments?.getString("mbid")?.takeIf { it.isNotBlank() }
                    val album = entry.arguments?.getString("album")?.takeIf { it.isNotBlank() }
                    val artist = entry.arguments?.getString("artist")?.takeIf { it.isNotBlank() }
                    val artistMbid = entry.arguments?.getString("artistMbid")?.takeIf { it.isNotBlank() }
                    val artSha1 = entry.arguments?.getString("artSha1")?.takeIf { it.isNotBlank() }
                    AlbumDetailScreen(
                        albumMbid = albumMbid,
                        albumTitle = album,
                        artistName = artist,
                        artistMbid = artistMbid,
                        fallbackArtSha1 = artSha1,
                        onBack = { navController.popBackStack() },
                        onArtistClick = {
                            navController.navigate(Routes.artist(mbid = artistMbid, name = artist))
                        },
                        onPlayTracks = { queue, startIndex ->
                            scope.launch {
                                runCatching { playTracks(queue, startIndex) }
                                    .onFailure { status = it.message ?: "Playback failed." }
                            }
                        },
                        contentPadding = contentPadding,
                    )
                }

                composable(
                    route = Routes.PLAYLIST,
                    arguments = listOf(navArgument("id") { type = NavType.LongType }),
                ) { entry ->
                    val id = entry.arguments?.getLong("id") ?: 0L
                    PlaylistDetailScreen(
                        playlistId = id,
                        onBack = { navController.popBackStack() },
                        onPlayTracks = { queue, startIndex ->
                            scope.launch {
                                runCatching { playTracks(queue, startIndex) }
                                    .onFailure { status = it.message ?: "Playback failed." }
                            }
                        },
                        contentPadding = contentPadding,
                    )
                }
            }

            Column(modifier = Modifier.align(Alignment.BottomCenter)) {
                val track = nowPlayingTrack
                if (track != null) {
                    MiniPlayer(
                        title = track.title,
                        artist = track.artist,
                        isPlaying = isPlaying,
                        artworkUrl = nowPlayingArtworkUrl,
                        seedName = (track.album ?: track.title),
                        progressMs = playbackPosition,
                        durationMs = playbackDuration,
                        onToggle = { playbackController.togglePlayPause() },
                        onPrevious = { playbackController.previous() },
                        onNext = { playbackController.next() },
                        onStop = {
                            playbackController.stop()
                            nowPlayingTrack = null
                            nowPlayingArtworkUrl = null
                            playbackQueue = emptyList()
                            showNowPlaying = false
                        },
                        onSeek = { playbackController.seekTo(it) },
                        onClick = { showNowPlaying = true },
                    )
                }
                if (atRoot) {
                    BottomNavBar(
                        selected = activeTab,
                        onSelect = { tab ->
                            navController.navigate(tab.route()) {
                                popUpTo(Routes.HOME) { saveState = true }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                    )
                }
            }

            // Now Playing full-screen overlay
            val npTrack = nowPlayingTrack
            if (npTrack != null) {
                NowPlayingSheet(
                    visible = showNowPlaying,
                    track = npTrack,
                    artworkUrl = nowPlayingArtworkUrl,
                    isPlaying = isPlaying,
                    progressMs = playbackPosition,
                    durationMs = playbackDuration,
                    shuffleEnabled = shuffleEnabled,
                    repeatMode = repeatMode,
                    queue = playbackQueue,
                    onDismiss = { showNowPlaying = false },
                    onToggle = { playbackController.togglePlayPause() },
                    onPrevious = { playbackController.previous() },
                    onNext = { playbackController.next() },
                    onSeek = { playbackController.seekTo(it) },
                    onShuffle = { playbackController.toggleShuffle() },
                    onRepeat = { playbackController.cycleRepeatMode() },
                    onQueueItemClick = { index ->
                        playbackController.playQueueItem(index)
                    },
                    onArtistClick = { artistName ->
                        showNowPlaying = false
                        navController.navigate(Routes.artist(mbid = null, name = artistName))
                    },
                )
            }
        }
    }
}
