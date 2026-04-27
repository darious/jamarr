package com.jamarr.android.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.jamarr.android.data.SearchResponse
import com.jamarr.android.data.SearchTrack
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
import com.jamarr.android.ui.screens.FavouritesScreen
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
    val vm: JamarrViewModel = viewModel()
    val accessToken by vm.tokenHolder.token.collectAsState()

    if (accessToken.isBlank()) {
        LoginScreen(
            serverUrl = vm.serverUrl,
            username = vm.username,
            password = vm.password,
            busy = vm.busy,
            status = vm.status,
            onServerUrlChange = { vm.serverUrl = it },
            onUsernameChange = { vm.username = it },
            onPasswordChange = { vm.password = it },
            onSubmit = { vm.login() },
        )
        return
    }

    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route

    // Persist active tab and refresh home on return
    LaunchedEffect(currentRoute) {
        routeToTab(currentRoute)?.let { tab ->
            vm.saveActiveTab(tab.ordinal)
        }
        if (currentRoute == Routes.HOME) {
            vm.refreshHome()
        }
    }

    // Restore saved tab once NavHost has attached its graph
    LaunchedEffect(currentRoute, vm.pendingSavedRoute) {
        val target = vm.pendingSavedRoute ?: return@LaunchedEffect
        if (currentRoute == null) return@LaunchedEffect
        vm.pendingSavedRoute = null
        if (currentRoute != target) {
            navController.navigate(target) {
                popUpTo(Routes.HOME) { inclusive = false }
                launchSingleTop = true
            }
        }
    }

    val ctx = JamarrAppContext(
        apiClient = vm.apiClient,
        playbackController = vm.playbackController,
        serverUrl = vm.serverUrl,
        accessToken = accessToken,
    )

    CompositionLocalProvider(LocalJamarrContext provides ctx) {
        Box(modifier = Modifier.fillMaxSize().background(JamarrColors.Bg)) {
            val atRoot = isRootRoute(currentRoute)
            val activeTab = routeToTab(currentRoute) ?: JamarrTab.Home
            val navBarHeight = if (atRoot) JamarrDims.BottomNavHeight else 0.dp
            val miniHeight = if (vm.nowPlayingTrack != null) JamarrDims.MiniPlayerHeight else 0.dp
            val contentPadding = PaddingValues(bottom = navBarHeight + miniHeight)

            NavHost(
                navController = navController,
                startDestination = Routes.HOME,
                modifier = Modifier.fillMaxSize(),
            ) {
                composable(Routes.HOME) {
                    HomeScreen(
                        greetingInitial = vm.username.firstOrNull()?.toString().orEmpty(),
                        serverUrl = vm.serverUrl,
                        homeContent = vm.homeContent,
                        searchResults = vm.searchResults,
                        searchQuery = vm.query,
                        onSearchQueryChange = {
                            vm.query = it
                            if (it.isBlank()) vm.searchResults = SearchResponse()
                        },
                        onSearchSubmit = vm::runSearch,
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
                            vm.playTrack(track, vm.searchResults.tracks.ifEmpty { listOf(track) })
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
                        onLogout = { vm.logout() },
                        artworkUrlForAlbum = { album -> vm.apiClient.artworkUrl(vm.serverUrl, album.artSha1, 400) },
                        artworkUrlForArtist = { artist ->
                            vm.apiClient.artworkUrl(vm.serverUrl, artist.artSha1, 400) ?: artist.imageUrl
                        },
                        contentPadding = contentPadding,
                        onRefresh = { vm.refreshHome() },
                    )
                }

                composable(Routes.FAVOURITES) {
                    FavouritesScreen(
                        onArtistClick = { mbid, name ->
                            navController.navigate(Routes.artist(mbid = mbid, name = name))
                        },
                        onAlbumClick = { albumMbid, title, artist ->
                            navController.navigate(
                                Routes.album(albumMbid = albumMbid, album = title, artist = artist),
                            )
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
                            vm.playTrack(SearchTrack(id = trackId, title = ""))
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
                        onPlayTrack = { track, queue -> vm.playTrack(track, queue) },
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
                            vm.playQueueFromUi(queue, startIndex)
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
                            vm.playQueueFromUi(queue, startIndex)
                        },
                        contentPadding = contentPadding,
                    )
                }
            }

            Column(modifier = Modifier.align(Alignment.BottomCenter)) {
                val track = vm.nowPlayingTrack
                if (track != null) {
                    MiniPlayer(
                        title = track.title,
                        artist = track.artist,
                        isPlaying = vm.isPlaying,
                        artworkUrl = vm.nowPlayingArtworkUrl,
                        seedName = (track.album ?: track.title),
                        progressMs = vm.playbackPosition,
                        durationMs = vm.playbackDuration,
                        shuffleEnabled = vm.shuffleEnabled,
                        repeatMode = vm.repeatMode,
                        onToggle = { vm.playbackController.togglePlayPause() },
                        onPrevious = { vm.playbackController.previous() },
                        onNext = { vm.playbackController.next() },
                        onStop = { vm.stopPlayback() },
                        onSeek = { vm.playbackController.seekTo(it) },
                        onClick = { vm.showNowPlaying = true },
                    )
                }
                if (atRoot) {
                    BottomNavBar(
                        selected = activeTab,
                        onSelect = { tab ->
                            navController.navigate(tab.route()) {
                                popUpTo(Routes.HOME) { inclusive = false }
                                launchSingleTop = true
                            }
                        },
                        onReselect = { tab ->
                            if (tab == JamarrTab.Home) {
                                vm.query = ""
                            }
                        },
                    )
                }
            }

            // Now Playing full-screen overlay
            val npTrack = vm.nowPlayingTrack
            if (npTrack != null) {
                NowPlayingSheet(
                    visible = vm.showNowPlaying,
                    track = npTrack,
                    artworkUrl = vm.nowPlayingArtworkUrl,
                    isPlaying = vm.isPlaying,
                    progressMs = vm.playbackPosition,
                    durationMs = vm.playbackDuration,
                    shuffleEnabled = vm.shuffleEnabled,
                    repeatMode = vm.repeatMode,
                    queue = vm.playbackQueue,
                    onDismiss = { vm.showNowPlaying = false },
                    onToggle = { vm.playbackController.togglePlayPause() },
                    onPrevious = { vm.playbackController.previous() },
                    onNext = { vm.playbackController.next() },
                    onSeek = { vm.playbackController.seekTo(it) },
                    onShuffle = { vm.playbackController.toggleShuffle() },
                    onRepeat = { vm.playbackController.cycleRepeatMode() },
                    onQueueItemClick = { index ->
                        vm.playbackController.playQueueItem(index)
                    },
                    onArtistClick = { artistName ->
                        vm.showNowPlaying = false
                        navController.navigate(Routes.artist(mbid = null, name = artistName))
                    },
                )
            }
        }
    }
}
