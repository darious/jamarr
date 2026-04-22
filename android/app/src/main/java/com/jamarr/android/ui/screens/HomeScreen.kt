package com.jamarr.android.ui.screens

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.sp
import com.jamarr.android.R
import com.jamarr.android.data.HomeAlbum
import com.jamarr.android.data.HomeArtist
import com.jamarr.android.data.HomeContent
import com.jamarr.android.data.SearchAlbum
import com.jamarr.android.data.SearchArtist
import com.jamarr.android.data.SearchResponse
import com.jamarr.android.data.SearchTrack
import com.jamarr.android.ui.components.AlbumArt
import com.jamarr.android.ui.components.ArtistArt
import com.jamarr.android.ui.components.CloseIcon
import com.jamarr.android.ui.components.SearchIcon
import com.jamarr.android.ui.state.LocalJamarrContext
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrShapes
import com.jamarr.android.ui.theme.JamarrType
import kotlinx.coroutines.delay

@Composable
fun HomeScreen(
    greetingInitial: String,
    serverUrl: String,
    homeContent: HomeContent,
    searchResults: SearchResponse,
    searchQuery: String,
    onSearchQueryChange: (String) -> Unit,
    onSearchSubmit: () -> Unit,
    onAlbumClick: (HomeAlbum) -> Unit,
    onArtistClick: (HomeArtist) -> Unit,
    onTrackClick: (SearchTrack) -> Unit,
    onSearchArtistClick: (mbid: String?, name: String) -> Unit,
    onSearchAlbumClick: (mbid: String?, title: String, artist: String) -> Unit,
    onLogout: () -> Unit,
    artworkUrlForAlbum: (HomeAlbum) -> String?,
    artworkUrlForArtist: (HomeArtist) -> String?,
    contentPadding: PaddingValues,
) {
    val isSearching = searchQuery.trim().isNotEmpty()
    val showAccountSheet = remember { mutableStateOf(false) }

    LaunchedEffect(searchQuery) {
        if (searchQuery.trim().length >= 2) {
            delay(250)
            onSearchSubmit()
        }
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .background(JamarrColors.Bg),
        contentPadding = PaddingValues(
            top = contentPadding.calculateTopPadding(),
            bottom = contentPadding.calculateBottomPadding() + 16.dp,
        ),
        verticalArrangement = Arrangement.spacedBy(JamarrDims.SectionGap),
    ) {
        item {
            Column(
                modifier = Modifier
                    .statusBarsPadding()
                    .padding(horizontal = JamarrDims.ScreenPadding)
                    .padding(top = 4.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                HeaderRow(
                    greetingInitial = greetingInitial,
                    onAvatarClick = { showAccountSheet.value = true },
                )
                SearchBar(
                    query = searchQuery,
                    onQueryChange = onSearchQueryChange,
                )
            }
        }

        if (isSearching) {
            searchResultsSection(
                results = searchResults,
                onArtistClick = onSearchArtistClick,
                onAlbumClick = onSearchAlbumClick,
                onTrackClick = onTrackClick,
            )
            return@LazyColumn
        }

        if (homeContent.newReleases.isNotEmpty()) {
            item {
                AlbumRowSection(
                    title = "New Releases",
                    albums = homeContent.newReleases,
                    artSize = 130.dp,
                    onAlbumClick = onAlbumClick,
                    artworkUrl = artworkUrlForAlbum,
                )
            }
        }
        if (homeContent.recentlyAddedAlbums.isNotEmpty()) {
            item {
                AlbumRowSection(
                    title = "Recently Added",
                    albums = homeContent.recentlyAddedAlbums,
                    artSize = 100.dp,
                    onAlbumClick = onAlbumClick,
                    artworkUrl = artworkUrlForAlbum,
                )
            }
        }
        if (homeContent.recentlyPlayedAlbums.isNotEmpty()) {
            item {
                AlbumRowSection(
                    title = "Recently Played",
                    albums = homeContent.recentlyPlayedAlbums,
                    artSize = 100.dp,
                    onAlbumClick = onAlbumClick,
                    artworkUrl = artworkUrlForAlbum,
                )
            }
        }
        if (homeContent.discoverArtists.isNotEmpty()) {
            item {
                ArtistRowSection(
                    title = "Newly Added Artists",
                    artists = homeContent.discoverArtists,
                    onArtistClick = onArtistClick,
                    artworkUrl = artworkUrlForArtist,
                )
            }
        }
        if (homeContent.recentlyPlayedArtists.isNotEmpty()) {
            item {
                ArtistRowSection(
                    title = "Recently Played Artists",
                    artists = homeContent.recentlyPlayedArtists,
                    onArtistClick = onArtistClick,
                    artworkUrl = artworkUrlForArtist,
                )
            }
        }
    }

    if (showAccountSheet.value) {
        AccountDialog(
            serverUrl = serverUrl,
            onDismiss = { showAccountSheet.value = false },
            onLogout = {
                showAccountSheet.value = false
                onLogout()
            },
        )
    }
}

@Composable
private fun HeaderRow(greetingInitial: String, onAvatarClick: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "Good evening",
                style = JamarrType.ScreenTitle,
                color = JamarrColors.Text,
            )
            Text(
                text = "What would you like to hear?",
                style = JamarrType.Body,
                color = JamarrColors.Muted,
            )
        }
        Image(
            painter = painterResource(id = R.drawable.jamarr_logo),
            contentDescription = "Menu",
            modifier = Modifier
                .size(36.dp)
                .clip(CircleShape)
                .clickable(onClick = onAvatarClick),
        )
    }
}

@Composable
private fun SearchBar(
    query: String,
    onQueryChange: (String) -> Unit,
) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(JamarrShapes.Card)
            .background(JamarrColors.Card)
            .padding(horizontal = 12.dp, vertical = 10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            SearchIcon(tint = JamarrColors.Muted)
            Spacer(Modifier.width(12.dp))
            Box(modifier = Modifier.weight(1f)) {
                if (query.isEmpty()) {
                    Text(
                        text = "Search albums, artists…",
                        style = JamarrType.Body,
                        color = JamarrColors.Muted,
                    )
                }
                BasicTextField(
                    value = query,
                    onValueChange = onQueryChange,
                    singleLine = true,
                    textStyle = JamarrType.Body.copy(color = JamarrColors.Text),
                    cursorBrush = SolidColor(JamarrColors.Primary),
                    keyboardOptions = KeyboardOptions(
                        capitalization = KeyboardCapitalization.None,
                        imeAction = ImeAction.Search,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            if (query.isNotEmpty()) {
                Spacer(Modifier.width(8.dp))
                Box(
                    modifier = Modifier
                        .size(20.dp)
                        .clip(CircleShape)
                        .clickable { onQueryChange("") },
                    contentAlignment = Alignment.Center,
                ) {
                    CloseIcon(tint = JamarrColors.Muted)
                }
            }
        }
    }
}

@Composable
private fun SectionHeader(title: String) {
    Text(
        text = title,
        style = JamarrType.SectionHeader,
        color = JamarrColors.Text,
        modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding),
    )
}

@Composable
private fun AlbumRowSection(
    title: String,
    albums: List<HomeAlbum>,
    artSize: Dp,
    onAlbumClick: (HomeAlbum) -> Unit,
    artworkUrl: (HomeAlbum) -> String?,
) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        SectionHeader(title)
        LazyRow(
            contentPadding = PaddingValues(horizontal = JamarrDims.ScreenPadding),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            items(albums, key = { it.album + it.artistName }) { album ->
                AlbumCard(
                    album = album,
                    artSize = artSize,
                    artworkUrl = artworkUrl(album),
                    onClick = { onAlbumClick(album) },
                )
            }
        }
    }
}

@Composable
private fun AlbumCard(
    album: HomeAlbum,
    artSize: Dp,
    artworkUrl: String?,
    onClick: () -> Unit,
) {
    Column(
        modifier = Modifier
            .width(artSize)
            .clickable(onClick = onClick),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Box(
            modifier = Modifier
                .size(artSize)
                .clip(JamarrShapes.AlbumArt),
        ) {
            AlbumArt(
                title = album.album,
                seedName = album.album + album.artistName,
                artworkUrl = artworkUrl,
                modifier = Modifier.fillMaxSize(),
            )
        }
        Text(
            text = album.album,
            style = JamarrType.CardTitleSmall,
            color = JamarrColors.Text,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = album.artistName,
            style = JamarrType.Caption,
            color = JamarrColors.Muted,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun ArtistRowSection(
    title: String,
    artists: List<HomeArtist>,
    onArtistClick: (HomeArtist) -> Unit,
    artworkUrl: (HomeArtist) -> String?,
) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        SectionHeader(title)
        LazyRow(
            contentPadding = PaddingValues(horizontal = JamarrDims.ScreenPadding),
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            items(artists, key = { it.mbid ?: it.name }) { artist ->
                ArtistTile(
                    artist = artist,
                    artworkUrl = artworkUrl(artist),
                    onClick = { onArtistClick(artist) },
                )
            }
        }
    }
}

@Composable
private fun ArtistTile(
    artist: HomeArtist,
    artworkUrl: String?,
    onClick: () -> Unit,
) {
    Column(
        modifier = Modifier
            .width(96.dp)
            .clickable(onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        ArtistArt(name = artist.name, imageUrl = artworkUrl, size = 88.dp)
        Text(
            text = artist.name,
            style = JamarrType.CardTitleSmall,
            color = JamarrColors.Text,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

private fun LazyListScope.searchResultsSection(
    results: SearchResponse,
    onArtistClick: (mbid: String?, name: String) -> Unit,
    onAlbumClick: (mbid: String?, title: String, artist: String) -> Unit,
    onTrackClick: (SearchTrack) -> Unit,
) {
    val empty = results.artists.isEmpty() && results.albums.isEmpty() && results.tracks.isEmpty()
    if (empty) {
        item {
            Text(
                text = "No results yet. Keep typing…",
                style = JamarrType.Body,
                color = JamarrColors.Muted,
                modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding),
            )
        }
        return
    }

    if (results.artists.isNotEmpty()) {
        item {
            Text(
                text = "Artists",
                style = JamarrType.SectionHeader,
                color = JamarrColors.Text,
                modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding),
            )
        }
        items(results.artists, key = { "artist-${it.mbid ?: it.name}" }) { artist ->
            SearchArtistRow(artist) { onArtistClick(artist.mbid, artist.name) }
        }
    }
    if (results.albums.isNotEmpty()) {
        item {
            Text(
                text = "Albums",
                style = JamarrType.SectionHeader,
                color = JamarrColors.Text,
                modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding),
            )
        }
        items(results.albums, key = { "album-${it.mbid ?: (it.title + it.artist)}" }) { album ->
            SearchAlbumRow(album) { onAlbumClick(album.mbid, album.title, album.artist) }
        }
    }
    if (results.tracks.isNotEmpty()) {
        item {
            Text(
                text = "Tracks",
                style = JamarrType.SectionHeader,
                color = JamarrColors.Text,
                modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding),
            )
        }
        items(results.tracks, key = { "track-${it.id}" }) { track ->
            SearchTrackRow(track) { onTrackClick(track) }
        }
    }
}

@Composable
private fun SearchArtistRow(artist: SearchArtist, onClick: () -> Unit) {
    val ctx = LocalJamarrContext.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = JamarrDims.ScreenPadding, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        ArtistArt(
            name = artist.name,
            imageUrl = ctx.artworkUrl(artist.artSha1, 200) ?: artist.imageUrl,
            size = 44.dp,
        )
        Spacer(Modifier.width(12.dp))
        Text(
            text = artist.name,
            style = JamarrType.CardTitleSmall,
            color = JamarrColors.Text,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun SearchAlbumRow(album: SearchAlbum, onClick: () -> Unit) {
    val ctx = LocalJamarrContext.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = JamarrDims.ScreenPadding, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(44.dp)
                .clip(JamarrShapes.AlbumArt),
        ) {
            AlbumArt(
                title = album.title,
                seedName = album.title + album.artist,
                artworkUrl = ctx.artworkUrl(album.artSha1, 200),
                modifier = Modifier.fillMaxSize(),
            )
        }
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = album.title,
                style = JamarrType.CardTitleSmall,
                color = JamarrColors.Text,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = album.artist,
                style = JamarrType.CaptionSmall,
                color = JamarrColors.Muted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun SearchTrackRow(track: SearchTrack, onClick: () -> Unit) {
    val ctx = LocalJamarrContext.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = JamarrDims.ScreenPadding, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(44.dp)
                .clip(JamarrShapes.AlbumArt),
        ) {
            AlbumArt(
                title = track.title,
                seedName = track.album ?: track.title,
                artworkUrl = ctx.artworkUrl(track.artSha1, 200),
                modifier = Modifier.fillMaxSize(),
            )
        }
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = track.title,
                style = JamarrType.CardTitleSmall,
                color = JamarrColors.Text,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = listOfNotNull(track.artist, track.album).joinToString(" · "),
                style = JamarrType.CaptionSmall,
                color = JamarrColors.Muted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun AccountDialog(
    serverUrl: String,
    onDismiss: () -> Unit,
    onLogout: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = JamarrColors.Surface,
        titleContentColor = JamarrColors.Text,
        textContentColor = JamarrColors.Muted,
        title = { Text("Account", style = JamarrType.SectionHeader, color = JamarrColors.Text) },
        text = {
            Text(
                text = if (serverUrl.isNotBlank()) "Signed in to $serverUrl" else "Signed in",
                style = JamarrType.Body,
                color = JamarrColors.Muted,
            )
        },
        confirmButton = {
            TextButton(
                onClick = onLogout,
                colors = ButtonDefaults.textButtonColors(contentColor = JamarrColors.Primary),
            ) { Text("Log out") }
        },
        dismissButton = {
            TextButton(
                onClick = onDismiss,
                colors = ButtonDefaults.textButtonColors(contentColor = JamarrColors.Muted),
            ) { Text("Cancel") }
        },
    )
}
