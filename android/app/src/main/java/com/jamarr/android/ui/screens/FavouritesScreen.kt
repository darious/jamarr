package com.jamarr.android.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.jamarr.android.data.FavoriteArtist
import com.jamarr.android.data.FavoriteRelease
import com.jamarr.android.ui.components.AlbumArt
import com.jamarr.android.ui.components.ArtistArt
import com.jamarr.android.ui.components.HeartIcon
import com.jamarr.android.ui.components.RefreshIcon
import com.jamarr.android.ui.state.LocalJamarrContext
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrShapes
import com.jamarr.android.ui.theme.JamarrType

private enum class FavTab { Artists, Releases }
private enum class FavSort { Recent, Alpha }

@Composable
fun FavouritesScreen(
    onArtistClick: (mbid: String, name: String) -> Unit,
    onAlbumClick: (albumMbid: String, title: String, artist: String?) -> Unit,
    contentPadding: PaddingValues,
) {
    val ctx = LocalJamarrContext.current

    var artists by remember { mutableStateOf<List<FavoriteArtist>>(emptyList()) }
    var releases by remember { mutableStateOf<List<FavoriteRelease>>(emptyList()) }
    var tab by remember { mutableStateOf(FavTab.Artists) }
    var artistSort by remember { mutableStateOf(FavSort.Recent) }
    var releaseSort by remember { mutableStateOf(FavSort.Recent) }
    var error by remember { mutableStateOf<String?>(null) }
    var refreshTick by remember { mutableStateOf(0) }
    var isRefreshing by remember { mutableStateOf(false) }

    LaunchedEffect(ctx.serverUrl, ctx.accessToken, refreshTick) {
        if (refreshTick > 0) isRefreshing = true
        runCatching {
            artists = ctx.apiClient.favoriteArtists(ctx.serverUrl, ctx.accessToken)
            releases = ctx.apiClient.favoriteReleases(ctx.serverUrl, ctx.accessToken)
        }.onFailure { error = it.message }
        isRefreshing = false
    }

    val sortedArtists = remember(artists, artistSort) {
        when (artistSort) {
            FavSort.Recent -> artists
            FavSort.Alpha -> artists.sortedBy { it.name.lowercase() }
        }
    }
    val sortedReleases = remember(releases, releaseSort) {
        when (releaseSort) {
            FavSort.Recent -> releases
            FavSort.Alpha -> releases.sortedBy { it.title.lowercase() }
        }
    }

    Box(modifier = Modifier.fillMaxSize().background(JamarrColors.Bg)) {
        PullToRefreshBox(
            isRefreshing = isRefreshing,
            onRefresh = { refreshTick++ },
            modifier = Modifier.fillMaxSize(),
        ) {
            Column(modifier = Modifier.fillMaxSize()) {
            Header(
                artistCount = artists.size,
                releaseCount = releases.size,
            )
            SubTabs(selected = tab, onSelect = { tab = it })
            Spacer(Modifier.height(20.dp))
            val activeSort = if (tab == FavTab.Artists) artistSort else releaseSort
            SortToggle(
                selected = activeSort,
                onSelect = {
                    if (tab == FavTab.Artists) artistSort = it else releaseSort = it
                },
            )
            Spacer(Modifier.height(16.dp))
            when (tab) {
                FavTab.Artists -> ArtistsList(
                    items = sortedArtists,
                    contentPadding = contentPadding,
                    onClick = { onArtistClick(it.mbid, it.name) },
                    artworkUrl = { ctx.artworkUrl(it.artSha1, 200) },
                )
                FavTab.Releases -> ReleasesGrid(
                    items = sortedReleases,
                    contentPadding = contentPadding,
                    onClick = { onAlbumClick(it.albumMbid, it.title, it.artistName) },
                    artworkUrl = { ctx.artworkUrl(it.artSha1, 400) },
                )
            }
            if (error != null) {
                Text(
                    text = error.orEmpty(),
                    style = JamarrType.Body,
                    color = JamarrColors.Muted,
                    modifier = Modifier.padding(JamarrDims.ScreenPadding),
                )
            }
        }
    }
    }
}

@Composable
private fun Header(artistCount: Int, releaseCount: Int) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .statusBarsPadding()
            .padding(horizontal = JamarrDims.ScreenPadding, vertical = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                HeartIcon(tint = JamarrColors.Primary, filled = true, size = 20.dp)
                Spacer(Modifier.width(8.dp))
                Text(
                    text = "Favourites",
                    style = JamarrType.ScreenTitle,
                    color = JamarrColors.Text,
                )
            }
            Text(
                text = "$artistCount artists · $releaseCount releases",
                style = JamarrType.Caption,
                color = JamarrColors.Muted,
            )
        }
    }
}

@Composable
private fun SubTabs(selected: FavTab, onSelect: (FavTab) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = JamarrDims.ScreenPadding),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        SubTabButton(
            label = "Artists",
            selected = selected == FavTab.Artists,
            onClick = { onSelect(FavTab.Artists) },
            modifier = Modifier.weight(1f),
        )
        SubTabButton(
            label = "Releases",
            selected = selected == FavTab.Releases,
            onClick = { onSelect(FavTab.Releases) },
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun SubTabButton(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val borderColor = if (selected) JamarrColors.Primary else JamarrColors.Border
    val bg = if (selected) JamarrColors.PrimaryTint else JamarrColors.Card
    val textColor = if (selected) JamarrColors.Primary else JamarrColors.Muted
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(10.dp))
            .border(BorderStroke(1.dp, borderColor), RoundedCornerShape(10.dp))
            .background(bg)
            .clickable(onClick = onClick)
            .padding(vertical = 9.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = label,
            style = JamarrType.Body,
            color = textColor,
            fontWeight = if (selected) androidx.compose.ui.text.font.FontWeight.W600 else androidx.compose.ui.text.font.FontWeight.W500,
        )
    }
}

@Composable
private fun SortToggle(selected: FavSort, onSelect: (FavSort) -> Unit) {
    Row(
        modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        SortPill(
            label = "Recently Favourited",
            selected = selected == FavSort.Recent,
            onClick = { onSelect(FavSort.Recent) },
        )
        SortPill(
            label = "A–Z",
            selected = selected == FavSort.Alpha,
            onClick = { onSelect(FavSort.Alpha) },
        )
    }
}

@Composable
private fun SortPill(label: String, selected: Boolean, onClick: () -> Unit) {
    val borderColor = if (selected) JamarrColors.Primary else JamarrColors.Border
    val bg = if (selected) JamarrColors.PrimaryTint else JamarrColors.Card
    val textColor = if (selected) JamarrColors.Primary else JamarrColors.Muted
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .border(BorderStroke(1.dp, borderColor), RoundedCornerShape(8.dp))
            .background(bg)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        Text(
            text = label,
            style = JamarrType.Caption,
            color = textColor,
            fontWeight = androidx.compose.ui.text.font.FontWeight.W600,
        )
    }
}

@Composable
private fun ArtistsList(
    items: List<FavoriteArtist>,
    contentPadding: PaddingValues,
    onClick: (FavoriteArtist) -> Unit,
    artworkUrl: (FavoriteArtist) -> String?,
) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(
            start = JamarrDims.ScreenPadding,
            end = JamarrDims.ScreenPadding,
            bottom = contentPadding.calculateBottomPadding() + 16.dp,
        ),
    ) {
        items(items, key = { it.mbid }) { artist ->
            ArtistFavCard(
                artist = artist,
                artworkUrl = artworkUrl(artist),
                onClick = { onClick(artist) },
            )
            Spacer(Modifier.height(8.dp))
        }
    }
}

@Composable
private fun ArtistFavCard(
    artist: FavoriteArtist,
    artworkUrl: String?,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .border(BorderStroke(1.dp, JamarrColors.Border), RoundedCornerShape(12.dp))
            .background(JamarrColors.Card)
            .clickable(onClick = onClick)
            .padding(10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        ArtistArt(
            name = artist.name,
            imageUrl = artworkUrl,
            size = 52.dp,
        )
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = artist.name,
                style = JamarrType.CardTitle,
                color = JamarrColors.Text,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = formatPlays(artist.listens),
                style = JamarrType.Caption,
                color = JamarrColors.Muted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(Modifier.width(8.dp))
        HeartIcon(tint = JamarrColors.Primary, filled = true, size = 18.dp)
    }
}

@Composable
private fun ReleasesGrid(
    items: List<FavoriteRelease>,
    contentPadding: PaddingValues,
    onClick: (FavoriteRelease) -> Unit,
    artworkUrl: (FavoriteRelease) -> String?,
) {
    LazyVerticalGrid(
        columns = GridCells.Fixed(2),
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(
            start = JamarrDims.ScreenPadding,
            end = JamarrDims.ScreenPadding,
            bottom = contentPadding.calculateBottomPadding() + 16.dp,
        ),
        horizontalArrangement = Arrangement.spacedBy(14.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        items(items, key = { it.albumMbid }) { release ->
            ReleaseFavCell(
                release = release,
                artworkUrl = artworkUrl(release),
                onClick = { onClick(release) },
            )
        }
    }
}

@Composable
private fun ReleaseFavCell(
    release: FavoriteRelease,
    artworkUrl: String?,
    onClick: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(1f)
                .clip(RoundedCornerShape(10.dp)),
        ) {
            AlbumArt(
                title = release.title,
                seedName = release.title + (release.artistName ?: ""),
                artworkUrl = artworkUrl,
                modifier = Modifier.fillMaxSize(),
            )
            Box(
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(6.dp)
                    .size(26.dp)
                    .clip(RoundedCornerShape(13.dp))
                    .background(Color(0x99000000)),
                contentAlignment = Alignment.Center,
            ) {
                HeartIcon(tint = JamarrColors.Primary, filled = true, size = 13.dp)
            }
        }
        Text(
            text = release.title,
            style = JamarrType.CardTitleSmall,
            color = JamarrColors.Text,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = listOfNotNull(release.artistName, formatYear(release.year))
                .joinToString(" · ")
                .ifBlank { "Unknown" },
            style = JamarrType.Caption,
            color = JamarrColors.Muted,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

private fun formatPlays(count: Int): String = when {
    count <= 0 -> "No plays yet"
    count == 1 -> "1 play"
    count >= 1_000_000 -> "${"%.1f".format(count / 1_000_000.0)}M plays"
    count >= 1_000 -> "${"%.1f".format(count / 1_000.0)}K plays"
    else -> "$count plays"
}

private fun formatYear(value: String?): String? {
    if (value.isNullOrBlank()) return null
    return value.take(4).takeIf { it.length == 4 && it.all(Char::isDigit) }
}
