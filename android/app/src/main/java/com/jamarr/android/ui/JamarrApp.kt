package com.jamarr.android.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import com.jamarr.android.R
import com.jamarr.android.auth.SettingsStore
import com.jamarr.android.data.HomeAlbum
import com.jamarr.android.data.HomeArtist
import com.jamarr.android.data.HomeContent
import com.jamarr.android.data.JamarrApiClient
import com.jamarr.android.data.SearchTrack
import com.jamarr.android.playback.JamarrPlaybackController
import com.jamarr.android.playback.ResolvedTrack
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private val PageBackground = Color(0xff121113)
private val PanelBackground = Color(0xff1c1a1f)
private val PanelBackgroundAlt = Color(0xff252229)
private val Pink = Color(0xffff4f9a)
private val PinkSoft = Color(0xffffb1cf)
private val Muted = Color(0xffbfb5bf)
private val Subtle = Color(0xff8f8790)

@Composable
fun JamarrApp() {
    MaterialTheme(
        colorScheme = darkJamarrColorScheme(),
        shapes = jamarrShapes(),
    ) {
        Surface(
            modifier = Modifier.fillMaxSize(),
            color = PageBackground,
        ) {
            StageTwoHomeScreen()
        }
    }
}

@Composable
private fun StageTwoHomeScreen() {
    val context = LocalContext.current
    val apiClient = remember { JamarrApiClient() }
    val settingsStore = remember { SettingsStore(context.applicationContext) }
    val playbackController = remember { JamarrPlaybackController(context.applicationContext) }
    val scope = rememberCoroutineScope()

    var serverUrl by rememberSaveable { mutableStateOf("") }
    var username by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var accessToken by rememberSaveable { mutableStateOf("") }
    var query by rememberSaveable { mutableStateOf("") }
    var tracks by remember { mutableStateOf<List<SearchTrack>>(emptyList()) }
    var homeContent by remember { mutableStateOf(HomeContent()) }
    var nowPlaying by remember { mutableStateOf<SearchTrack?>(null) }
    var status by remember { mutableStateOf("Connect to Jamarr.") }
    var busy by remember { mutableStateOf(false) }
    var homeBusy by remember { mutableStateOf(false) }
    var isPlaying by remember { mutableStateOf(false) }

    fun refreshHome() {
        if (serverUrl.isBlank() || accessToken.isBlank()) return
        scope.launch {
            homeBusy = true
            runCatching {
                apiClient.home(serverUrl, accessToken)
            }.onSuccess {
                homeContent = it
                if (status == "Connect to Jamarr." || status == "Saved session loaded.") {
                    status = "Home loaded."
                }
            }.onFailure {
                status = it.message ?: "Failed to load home."
            }
            homeBusy = false
        }
    }

    fun searchTracks(searchQuery: String = query) {
        if (serverUrl.isBlank() || accessToken.isBlank() || searchQuery.trim().length < 2) return
        scope.launch {
            busy = true
            status = "Searching..."
            runCatching {
                settingsStore.saveServerUrl(apiClient.normalizeServerUrl(serverUrl))
                apiClient.search(serverUrl, accessToken, searchQuery.trim()).tracks
            }.onSuccess { result ->
                query = searchQuery
                tracks = result
                status = "${result.size} track result${if (result.size == 1) "" else "s"}."
            }.onFailure {
                status = it.message ?: "Search failed."
            }
            busy = false
        }
    }

    fun playQueue(queueTracks: List<SearchTrack>, selectedTrack: SearchTrack) {
        scope.launch {
            busy = true
            status = "Resolving stream queue..."
            runCatching {
                val startIndex = queueTracks.indexOfFirst { it.id == selectedTrack.id }.coerceAtLeast(0)
                val queue = queueTracks.map { queueTrack ->
                    ResolvedTrack(
                        track = queueTrack,
                        streamUrl = apiClient.streamUrl(serverUrl, accessToken, queueTrack.id),
                        artworkUrl = apiClient.artworkUrl(serverUrl, queueTrack.artSha1),
                    )
                }
                playbackController.playQueue(queue, startIndex)
            }.onSuccess {
                nowPlaying = selectedTrack
                status = "Playing ${selectedTrack.title}."
            }.onFailure {
                status = it.message ?: "Playback failed."
            }
            busy = false
        }
    }

    fun playAlbum(album: HomeAlbum) {
        scope.launch {
            busy = true
            status = "Loading ${album.album}..."
            runCatching {
                apiClient.albumTracks(serverUrl, accessToken, album.album, album.artistName)
            }.onSuccess { albumTracks ->
                if (albumTracks.isEmpty()) {
                    status = "No tracks found for ${album.album}."
                    busy = false
                } else {
                    tracks = albumTracks
                    playQueue(albumTracks, albumTracks.first())
                }
            }.onFailure {
                status = it.message ?: "Failed to load album."
                busy = false
            }
        }
    }

    LaunchedEffect(Unit) {
        val saved = settingsStore.load()
        serverUrl = saved.serverUrl
        accessToken = saved.accessToken
        if (saved.accessToken.isNotBlank()) {
            status = "Saved session loaded."
            delay(100)
            refreshHome()
        }
    }

    LaunchedEffect(playbackController, tracks) {
        while (true) {
            isPlaying = playbackController.isPlaying
            playbackController.currentMediaId?.toLongOrNull()?.let { trackId ->
                nowPlaying = tracks.firstOrNull { it.id == trackId } ?: nowPlaying
            }
            delay(500)
        }
    }

    DisposableEffect(playbackController) {
        onDispose {
            playbackController.release()
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .imePadding()
            .navigationBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp),
    ) {
        AppHeader(status = status, busy = busy || homeBusy)

        LoginPanel(
            serverUrl = serverUrl,
            username = username,
            password = password,
            hasToken = accessToken.isNotBlank(),
            busy = busy,
            onServerUrlChange = { serverUrl = it },
            onUsernameChange = { username = it },
            onPasswordChange = { password = it },
            onLogin = {
                scope.launch {
                    busy = true
                    status = "Logging in..."
                    runCatching {
                        val normalizedServerUrl = apiClient.normalizeServerUrl(serverUrl)
                        val response = apiClient.login(normalizedServerUrl, username, password)
                        settingsStore.saveServerUrl(normalizedServerUrl)
                        settingsStore.saveAccessToken(response.accessToken)
                        serverUrl = normalizedServerUrl
                        accessToken = response.accessToken
                        password = ""
                    }.onSuccess {
                        status = "Logged in."
                        refreshHome()
                    }.onFailure {
                        status = it.message ?: "Login failed."
                    }
                    busy = false
                }
            },
            onLogout = {
                scope.launch {
                    settingsStore.clearAccessToken()
                    accessToken = ""
                    tracks = emptyList()
                    homeContent = HomeContent()
                    nowPlaying = null
                    playbackController.stop()
                    status = "Logged out locally."
                }
            },
        )

        SearchPanel(
            query = query,
            canSearch = accessToken.isNotBlank() && serverUrl.isNotBlank() && !busy,
            busy = busy,
            onQueryChange = { query = it },
            onSearch = { searchTracks() },
        )

        NowPlayingPanel(
            track = nowPlaying,
            isPlaying = isPlaying,
            onToggle = { playbackController.togglePlayPause() },
            onPrevious = { playbackController.previous() },
            onSeekBackward = { playbackController.seekBackward() },
            onSeekForward = { playbackController.seekForward() },
            onNext = { playbackController.next() },
            onStop = {
                playbackController.stop()
                nowPlaying = null
                status = "Playback stopped."
            },
        )

        HomeSections(
            serverUrl = serverUrl,
            homeContent = homeContent,
            onAlbumClick = ::playAlbum,
            onArtistClick = { artist -> searchTracks(artist.name) },
        )

        SearchResults(
            tracks = tracks,
            enabled = accessToken.isNotBlank() && !busy,
            onTrackSelected = { track -> playQueue(tracks, track) },
        )
    }
}

@Composable
private fun AppHeader(status: String, busy: Boolean) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Image(
            painter = painterResource(id = R.drawable.jamarr_logo),
            contentDescription = "Jamarr",
            modifier = Modifier
                .size(54.dp)
                .clip(RoundedCornerShape(8.dp)),
        )
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "Jamarr",
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
                color = PinkSoft,
            )
            Text(
                text = status,
                style = MaterialTheme.typography.bodyMedium,
                color = Muted,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
        if (busy) {
            CircularProgressIndicator(color = Pink)
        }
    }
}

@Composable
private fun LoginPanel(
    serverUrl: String,
    username: String,
    password: String,
    hasToken: Boolean,
    busy: Boolean,
    onServerUrlChange: (String) -> Unit,
    onUsernameChange: (String) -> Unit,
    onPasswordChange: (String) -> Unit,
    onLogin: () -> Unit,
    onLogout: () -> Unit,
) {
    Card(
        colors = CardDefaults.cardColors(containerColor = PanelBackground),
        shape = RoundedCornerShape(8.dp),
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            OutlinedTextField(
                value = serverUrl,
                onValueChange = onServerUrlChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("Server URL") },
                placeholder = { Text("http://192.168.1.20:8000") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(
                    capitalization = KeyboardCapitalization.None,
                    keyboardType = KeyboardType.Uri,
                ),
            )
            if (!hasToken) {
                OutlinedTextField(
                    value = username,
                    onValueChange = onUsernameChange,
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("Username") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None),
                )
                OutlinedTextField(
                    value = password,
                    onValueChange = onPasswordChange,
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("Password") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(
                        capitalization = KeyboardCapitalization.None,
                        keyboardType = KeyboardType.Password,
                    ),
                    visualTransformation = PasswordVisualTransformation(),
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(
                    enabled = !busy &&
                        serverUrl.isNotBlank() &&
                        (hasToken || username.isNotBlank() && password.isNotBlank()),
                    onClick = if (hasToken) ({}) else onLogin,
                ) {
                    Text(if (hasToken) "Connected" else "Log in")
                }
                OutlinedButton(
                    enabled = !busy && hasToken,
                    onClick = onLogout,
                ) {
                    Text("Forget")
                }
            }
        }
    }
}

@Composable
private fun SearchPanel(
    query: String,
    canSearch: Boolean,
    busy: Boolean,
    onQueryChange: (String) -> Unit,
    onSearch: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        OutlinedTextField(
            value = query,
            onValueChange = onQueryChange,
            modifier = Modifier.weight(1f),
            label = { Text("Search tracks") },
            singleLine = true,
        )
        Button(
            enabled = canSearch && !busy && query.trim().length >= 2,
            onClick = onSearch,
        ) {
            Text("Search")
        }
    }
}

@Composable
private fun NowPlayingPanel(
    track: SearchTrack?,
    isPlaying: Boolean,
    onToggle: () -> Unit,
    onPrevious: () -> Unit,
    onSeekBackward: () -> Unit,
    onSeekForward: () -> Unit,
    onNext: () -> Unit,
    onStop: () -> Unit,
) {
    Card(
        colors = CardDefaults.cardColors(containerColor = PanelBackgroundAlt),
        shape = RoundedCornerShape(8.dp),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = track?.title ?: "Nothing playing",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                color = Color.White,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = track?.let { listOfNotNull(it.artist, it.album).joinToString(" - ") }.orEmpty(),
                style = MaterialTheme.typography.bodyMedium,
                color = Muted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = track != null,
                        onClick = onPrevious,
                    ) {
                        Text("Prev")
                    }
                    Button(
                        modifier = Modifier.weight(1f),
                        enabled = track != null,
                        onClick = onToggle,
                    ) {
                        Text(if (isPlaying) "Pause" else "Play")
                    }
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = track != null,
                        onClick = onNext,
                    ) {
                        Text("Next")
                    }
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = track != null,
                        onClick = onSeekBackward,
                    ) {
                        Text("-10s")
                    }
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = track != null,
                        onClick = onSeekForward,
                    ) {
                        Text("+30s")
                    }
                    TextButton(
                        modifier = Modifier.weight(1f),
                        enabled = track != null,
                        onClick = onStop,
                    ) {
                        Text("Stop")
                    }
                }
            }
        }
    }
}

@Composable
private fun HomeSections(
    serverUrl: String,
    homeContent: HomeContent,
    onAlbumClick: (HomeAlbum) -> Unit,
    onArtistClick: (HomeArtist) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(20.dp)) {
        AlbumSection("New Releases", serverUrl, homeContent.newReleases, onAlbumClick)
        AlbumSection("Recently Added", serverUrl, homeContent.recentlyAddedAlbums, onAlbumClick)
        AlbumSection("Recently Played Albums", serverUrl, homeContent.recentlyPlayedAlbums, onAlbumClick)
        ArtistSection("Newly Added Artists", serverUrl, homeContent.discoverArtists, onArtistClick)
        ArtistSection("Recently Played Artists", serverUrl, homeContent.recentlyPlayedArtists, onArtistClick)
    }
}

@Composable
private fun AlbumSection(
    title: String,
    serverUrl: String,
    albums: List<HomeAlbum>,
    onAlbumClick: (HomeAlbum) -> Unit,
) {
    if (albums.isEmpty()) return

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        SectionTitle(title)
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            albums.forEach { album ->
                AlbumArtworkCard(
                    album = album,
                    artworkUrl = JamarrApiClient().artworkUrl(serverUrl, album.artSha1, 400),
                    onClick = { onAlbumClick(album) },
                )
            }
            Spacer(modifier = Modifier.width(1.dp))
        }
    }
}

@Composable
private fun ArtistSection(
    title: String,
    serverUrl: String,
    artists: List<HomeArtist>,
    onArtistClick: (HomeArtist) -> Unit,
) {
    if (artists.isEmpty()) return

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        SectionTitle(title)
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            artists.forEach { artist ->
                ArtistArtworkCard(
                    artist = artist,
                    artworkUrl = JamarrApiClient().artworkUrl(serverUrl, artist.artSha1, 400) ?: artist.imageUrl,
                    onClick = { onArtistClick(artist) },
                )
            }
            Spacer(modifier = Modifier.width(1.dp))
        }
    }
}

@Composable
private fun SectionTitle(title: String) {
    Text(
        text = title,
        style = MaterialTheme.typography.titleLarge,
        fontWeight = FontWeight.Bold,
        color = PinkSoft,
    )
}

@Composable
private fun AlbumArtworkCard(
    album: HomeAlbum,
    artworkUrl: String?,
    onClick: () -> Unit,
) {
    Column(modifier = Modifier.width(148.dp)) {
        Card(
            onClick = onClick,
            shape = RoundedCornerShape(8.dp),
            colors = CardDefaults.cardColors(containerColor = PanelBackgroundAlt),
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(1f),
            ) {
                ArtworkImage(
                    url = artworkUrl,
                    contentDescription = album.album,
                    modifier = Modifier.fillMaxSize(),
                )
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .background(
                            Brush.verticalGradient(
                                colors = listOf(Color.Transparent, Color(0xcc000000)),
                            ),
                        ),
                )
                Text(
                    text = "Play",
                    color = Color.White,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier
                        .align(Alignment.BottomStart)
                        .padding(10.dp),
                )
            }
        }
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = album.album,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            color = Color.White,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            text = album.artistName,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            color = Muted,
            style = MaterialTheme.typography.bodySmall,
        )
        Text(
            text = album.year ?: "",
            maxLines = 1,
            color = Subtle,
            style = MaterialTheme.typography.labelSmall,
        )
    }
}

@Composable
private fun ArtistArtworkCard(
    artist: HomeArtist,
    artworkUrl: String?,
    onClick: () -> Unit,
) {
    Column(
        modifier = Modifier.width(132.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Card(
            onClick = onClick,
            shape = CircleShape,
            colors = CardDefaults.cardColors(containerColor = PanelBackgroundAlt),
        ) {
            ArtworkImage(
                url = artworkUrl,
                contentDescription = artist.name,
                modifier = Modifier
                    .size(132.dp)
                    .clip(CircleShape),
            )
        }
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = artist.name,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            color = Color.White,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

@Composable
private fun ArtworkImage(
    url: String?,
    contentDescription: String,
    modifier: Modifier = Modifier,
) {
    if (url.isNullOrBlank()) {
        Box(
            modifier = modifier.background(PanelBackgroundAlt),
            contentAlignment = Alignment.Center,
        ) {
            Image(
                painter = painterResource(id = R.drawable.jamarr_logo),
                contentDescription = contentDescription,
                modifier = Modifier.size(52.dp),
                alpha = 0.7f,
            )
        }
        return
    }

    AsyncImage(
        model = url,
        contentDescription = contentDescription,
        contentScale = ContentScale.Crop,
        modifier = modifier,
    )
}

@Composable
private fun SearchResults(
    tracks: List<SearchTrack>,
    enabled: Boolean,
    onTrackSelected: (SearchTrack) -> Unit,
) {
    if (tracks.isEmpty()) return

    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        SectionTitle("Tracks")
        tracks.forEach { track ->
            Card(
                onClick = { if (enabled) onTrackSelected(track) },
                enabled = enabled,
                shape = RoundedCornerShape(8.dp),
                colors = CardDefaults.cardColors(containerColor = PanelBackground),
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(14.dp),
                ) {
                    Text(
                        text = track.title,
                        style = MaterialTheme.typography.titleMedium,
                        color = Color.White,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Spacer(modifier = Modifier.height(3.dp))
                    Text(
                        text = listOfNotNull(track.artist, track.album, track.durationSeconds?.formatDuration())
                            .joinToString(" - "),
                        style = MaterialTheme.typography.bodyMedium,
                        color = Muted,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
    }
}

private fun Double.formatDuration(): String {
    val totalSeconds = toInt()
    val minutes = totalSeconds / 60
    val seconds = totalSeconds % 60
    return "%d:%02d".format(minutes, seconds)
}
