package com.jamarr.android.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.foundation.rememberScrollState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import kotlinx.coroutines.launch
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import com.jamarr.android.data.AlbumDetail
import com.jamarr.android.data.ArtistDetail
import com.jamarr.android.data.ArtistTrackEntry
import com.jamarr.android.data.SearchTrack
import com.jamarr.android.data.SimilarArtist
import com.jamarr.android.ui.components.AlbumArt
import com.jamarr.android.ui.components.ArtistArt
import com.jamarr.android.ui.components.HeartIcon
import com.jamarr.android.ui.components.PlayIcon
import com.jamarr.android.ui.components.TrackRow
import com.jamarr.android.ui.components.formatDuration
import com.jamarr.android.ui.components.seedColor
import com.jamarr.android.ui.state.LocalJamarrContext
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrShapes
import com.jamarr.android.ui.theme.JamarrType

private enum class TopTracksTab(val label: String) {
    MostScrobbled("Most Scrobbled"),
    MostListened("Most Listened"),
    Singles("Singles"),
}

private enum class DiscographyTab(val label: String) {
    Albums("Albums"),
    Compilations("Compilations"),
    Live("Live"),
    EPs("EPs"),
    Singles("Singles"),
    AppearsOn("Appears On"),
}

private fun AlbumDetail.matchesDiscoTab(tab: DiscographyTab): Boolean {
    // "Appears On" is determined by the API's type field, not release_type
    if (tab == DiscographyTab.AppearsOn) return type == "appears_on"
    // Non-AppearsOn tabs should exclude appears_on albums
    if (type == "appears_on") return false
    val rt = (releaseType ?: "album").lowercase().trim()
    return when (tab) {
        DiscographyTab.Albums -> rt == "album" || rt == "other" || rt.isBlank()
        DiscographyTab.Compilations -> rt == "compilation"
        DiscographyTab.Live -> rt == "live"
        DiscographyTab.EPs -> rt == "ep"
        DiscographyTab.Singles -> rt == "single"
        DiscographyTab.AppearsOn -> false
    }
}

@Composable
fun ArtistDetailScreen(
    initialMbid: String?,
    initialName: String?,
    initialArtSha1: String? = null,
    onBack: () -> Unit,
    onAlbumClick: (AlbumDetail) -> Unit,
    onSimilarArtistClick: (mbid: String?, name: String) -> Unit,
    onPlayTrack: (SearchTrack, List<SearchTrack>) -> Unit,
    contentPadding: PaddingValues,
) {
    val ctx = LocalJamarrContext.current
    val scope = rememberCoroutineScope()
    val detail = remember { mutableStateOf<ArtistDetail?>(null) }
    val albums = remember { mutableStateOf<List<AlbumDetail>>(emptyList()) }
    val tab = remember { mutableStateOf(TopTracksTab.MostScrobbled) }
    val discoTab = remember { mutableStateOf(DiscographyTab.Albums) }
    val errorState = remember { mutableStateOf<String?>(null) }
    val isFavorite = remember { mutableStateOf(false) }

    LaunchedEffect(initialMbid, initialName) {
        errorState.value = null
        runCatching {
            ctx.apiClient.artistDetail(
                serverUrl = ctx.serverUrl,
                accessToken = ctx.accessToken,
                mbid = initialMbid,
                name = initialName,
            )
        }.onSuccess {
            detail.value = it
            isFavorite.value = it?.isFavorite == true
        }.onFailure { errorState.value = it.message }
    }

    val resolvedMbid = detail.value?.mbid ?: initialMbid
    LaunchedEffect(resolvedMbid) {
        if (resolvedMbid.isNullOrBlank()) {
            albums.value = emptyList()
            return@LaunchedEffect
        }
        runCatching { ctx.apiClient.artistAlbums(ctx.serverUrl, ctx.accessToken, resolvedMbid) }
            .onSuccess { albums.value = it }
    }

    val artistName = detail.value?.name ?: initialName ?: "Artist"

    Box(modifier = Modifier.fillMaxSize().background(JamarrColors.Bg)) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                bottom = contentPadding.calculateBottomPadding() + 16.dp,
            ),
        ) {
            item {
                val artImageUrl = ctx.artworkUrl(detail.value?.artSha1 ?: initialArtSha1, 800)
                    ?: detail.value?.imageUrl
                ArtistHero(
                    name = artistName,
                    artImageUrl = artImageUrl,
                    genres = detail.value?.genres?.take(2)?.joinToString(" · ") { it.name },
                    listens = detail.value?.listens ?: 0,
                    onBack = onBack,
                    canFavorite = !resolvedMbid.isNullOrBlank(),
                    isFavorite = isFavorite.value,
                    onToggleFavorite = {
                        val mbid = resolvedMbid ?: return@ArtistHero
                        val desired = !isFavorite.value
                        isFavorite.value = desired
                        scope.launch {
                            runCatching {
                                ctx.apiClient.setArtistFavorite(
                                    serverUrl = ctx.serverUrl,
                                    accessToken = ctx.accessToken,
                                    artistMbid = mbid,
                                    favorite = desired,
                                )
                            }.onFailure { isFavorite.value = !desired }
                        }
                    },
                )
            }

            val bio = detail.value?.bio
            if (!bio.isNullOrBlank()) {
                item {
                    Text(
                        text = bio,
                        style = JamarrType.Body,
                        color = JamarrColors.Muted,
                        maxLines = 4,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.padding(
                            horizontal = JamarrDims.ScreenPadding,
                            vertical = 12.dp,
                        ),
                    )
                }
            }

            val links = detail.value.collectLinks()
            if (links.isNotEmpty()) {
                item {
                    LinksRow(links)
                }
            }

            val topList = when (tab.value) {
                TopTracksTab.MostScrobbled -> detail.value?.topTracks.orEmpty()
                TopTracksTab.MostListened -> detail.value?.mostListened.orEmpty()
                TopTracksTab.Singles -> detail.value?.singles.orEmpty()
            }.take(6)
            val resolvedQueue = topList.mapNotNull { it.toSearchTrack(artistName) }
            item {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = JamarrDims.ScreenPadding, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = "Top Tracks",
                        style = JamarrType.SectionHeader,
                        color = JamarrColors.Text,
                        modifier = Modifier.weight(1f),
                    )
                    if (resolvedQueue.isNotEmpty()) {
                        Row(
                            modifier = Modifier
                                .clip(RoundedCornerShape(24.dp))
                                .background(JamarrColors.Primary)
                                .clickable { onPlayTrack(resolvedQueue.first(), resolvedQueue) }
                                .padding(horizontal = 14.dp, vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            PlayIcon(tint = Color.White, size = 14.dp)
                            Spacer(Modifier.width(6.dp))
                            Text(
                                text = "Play",
                                style = JamarrType.Caption,
                                color = Color.White,
                            )
                        }
                    }
                }
            }
            item {
                PillTabs(
                    tabs = TopTracksTab.entries.map { it.label },
                    selectedIndex = tab.value.ordinal,
                    onSelect = { idx -> tab.value = TopTracksTab.entries[idx] },
                    modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding),
                )
            }
            items(topList.withIndex().toList(), key = { (i, _) -> "top-${tab.value}-$i" }) { (i, entry) ->
                val track = entry.toSearchTrack(artistName)
                TrackRow(
                    number = i + 1,
                    title = entry.displayTitle,
                    subtitle = entry.album ?: "—",
                    duration = entry.plays?.let { "$it plays" } ?: formatDuration(entry.durationSeconds),
                    active = track != null && ctx.playbackController.currentMediaId?.toLongOrNull() == track.id,
                    onClick = {
                        if (track != null) {
                            onPlayTrack(track, resolvedQueue)
                        }
                    },
                )
            }

            val availableTabs = DiscographyTab.entries.filter { tab ->
                albums.value.any { it.matchesDiscoTab(tab) }
            }
            if (availableTabs.isNotEmpty()) {
                item {
                    Text(
                        text = "Discography",
                        style = JamarrType.SectionHeader,
                        color = JamarrColors.Text,
                        modifier = Modifier.padding(
                            horizontal = JamarrDims.ScreenPadding,
                            vertical = 12.dp,
                        ),
                    )
                }
                item {
                    val selectedTab = if (discoTab.value in availableTabs) discoTab.value else availableTabs.first()
                    if (selectedTab != discoTab.value) discoTab.value = selectedTab
                    PillTabs(
                        tabs = availableTabs.map { it.label },
                        selectedIndex = availableTabs.indexOf(discoTab.value),
                        onSelect = { idx -> discoTab.value = availableTabs[idx] },
                        modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding),
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                }
                val filteredAlbums = albums.value.filter { it.matchesDiscoTab(discoTab.value) }
                items(filteredAlbums, key = { "disco-${discoTab.value}-${it.albumMbid ?: it.album}" }) { album ->
                    DiscographyRow(album = album, onClick = { onAlbumClick(album) })
                }
            }

            val similar = detail.value?.similarArtists.orEmpty()
            if (similar.isNotEmpty()) {
                item {
                    Text(
                        text = "Similar Artists",
                        style = JamarrType.SectionHeader,
                        color = JamarrColors.Text,
                        modifier = Modifier.padding(
                            horizontal = JamarrDims.ScreenPadding,
                            vertical = 12.dp,
                        ),
                    )
                }
                item {
                    LazyRow(
                        contentPadding = PaddingValues(horizontal = JamarrDims.ScreenPadding),
                        horizontalArrangement = Arrangement.spacedBy(14.dp),
                    ) {
                        items(similar, key = { it.mbid ?: it.name }) { sim ->
                            SimilarArtistTile(sim) { onSimilarArtistClick(sim.mbid, sim.name) }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ArtistHero(
    name: String,
    artImageUrl: String?,
    genres: String?,
    listens: Int,
    onBack: () -> Unit,
    canFavorite: Boolean,
    isFavorite: Boolean,
    onToggleFavorite: () -> Unit,
) {
    val top = seedColor(name)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(300.dp)
            .background(Brush.verticalGradient(listOf(top, JamarrColors.Bg))),
    ) {
        if (!artImageUrl.isNullOrBlank()) {
            AsyncImage(
                model = artImageUrl,
                contentDescription = name,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
            )
        }
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(160.dp)
                .align(Alignment.BottomCenter)
                .background(
                    Brush.verticalGradient(
                        listOf(Color.Transparent, JamarrColors.Bg),
                    ),
                ),
        )
        Box(
            modifier = Modifier
                .statusBarsPadding()
                .padding(JamarrDims.ScreenPadding)
                .size(34.dp)
                .clip(CircleShape)
                .background(Color(0x66000000))
                .clickable(onClick = onBack),
            contentAlignment = Alignment.Center,
        ) {
            Text(text = "←", color = Color.White, style = JamarrType.CardTitle)
        }
        if (canFavorite) {
            Box(
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .statusBarsPadding()
                    .padding(JamarrDims.ScreenPadding)
                    .size(34.dp)
                    .clip(CircleShape)
                    .background(Color(0x66000000))
                    .clickable(onClick = onToggleFavorite),
                contentAlignment = Alignment.Center,
            ) {
                HeartIcon(
                    tint = if (isFavorite) JamarrColors.Primary else Color.White,
                    filled = isFavorite,
                    size = 18.dp,
                )
            }
        }
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .align(Alignment.BottomStart)
                .padding(
                    horizontal = JamarrDims.ScreenPadding,
                    vertical = 16.dp,
                ),
        ) {
            Text(
                text = name,
                style = JamarrType.HeroTitle,
                color = JamarrColors.Text,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            val meta = listOfNotNull(
                genres?.takeIf { it.isNotBlank() },
                if (listens > 0) "$listens plays" else null,
            ).joinToString(" · ")
            if (meta.isNotEmpty()) {
                Text(
                    text = meta,
                    style = JamarrType.Caption,
                    color = JamarrColors.Muted,
                )
            }
        }
    }
}

private data class ArtistLink(val label: String, val url: String)

private fun ArtistDetail?.collectLinks(): List<ArtistLink> {
    if (this == null) return emptyList()
    return listOfNotNull(
        lastfmUrl?.let { ArtistLink("Last.fm", it) },
        musicbrainzUrl?.let { ArtistLink("MusicBrainz", it) },
        wikipediaUrl?.let { ArtistLink("Wikipedia", it) },
        discogsUrl?.let { ArtistLink("Discogs", it) },
        spotifyUrl?.let { ArtistLink("Spotify", it) },
        tidalUrl?.let { ArtistLink("Tidal", it) },
        qobuzUrl?.let { ArtistLink("Qobuz", it) },
        homepage?.let { ArtistLink("Homepage", it) },
    )
}

@Composable
private fun LinksRow(links: List<ArtistLink>) {
    LazyRow(
        contentPadding = PaddingValues(horizontal = JamarrDims.ScreenPadding, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(links, key = { it.label }) { link ->
            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(24.dp))
                    .background(JamarrColors.Card)
                    .padding(horizontal = 14.dp, vertical = 8.dp),
            ) {
                Text(text = link.label, style = JamarrType.Caption, color = JamarrColors.Primary)
            }
        }
    }
}

@Composable
private fun PillTabs(
    tabs: List<String>,
    selectedIndex: Int,
    onSelect: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        tabs.forEachIndexed { index, label ->
            val active = index == selectedIndex
            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(24.dp))
                    .background(if (active) JamarrColors.PrimaryTint else JamarrColors.Card)
                    .clickable { onSelect(index) }
                    .padding(horizontal = 12.dp, vertical = 6.dp),
            ) {
                Text(
                    text = label,
                    style = JamarrType.Caption,
                    color = if (active) JamarrColors.Primary else JamarrColors.Muted,
                )
            }
        }
    }
}

@Composable
private fun DiscographyRow(album: AlbumDetail, onClick: () -> Unit) {
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
                .size(52.dp)
                .clip(JamarrShapes.AlbumArt),
        ) {
            AlbumArt(
                title = album.album,
                seedName = album.album + (album.artistName ?: ""),
                artworkUrl = ctx.artworkUrl(album.artSha1, 200),
                modifier = Modifier.fillMaxSize(),
            )
        }
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = album.album,
                style = JamarrType.CardTitle,
                color = JamarrColors.Text,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            val meta = listOfNotNull(
                album.year?.take(4),
                album.trackCount?.let { "$it track${if (it == 1) "" else "s"}" },
            ).joinToString(" · ")
            if (meta.isNotEmpty()) {
                Text(
                    text = meta,
                    style = JamarrType.CaptionSmall,
                    color = JamarrColors.Muted,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun SimilarArtistTile(artist: SimilarArtist, onClick: () -> Unit) {
    val ctx = LocalJamarrContext.current
    Column(
        modifier = Modifier
            .width(96.dp)
            .clickable(onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        ArtistArt(
            name = artist.name,
            imageUrl = ctx.artworkUrl(artist.artSha1, 200) ?: artist.imageUrl,
            size = 64.dp,
        )
        Text(
            text = artist.name,
            style = JamarrType.CaptionSmall,
            color = JamarrColors.Text,
            textAlign = TextAlign.Center,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

private fun ArtistTrackEntry.toSearchTrack(artistName: String): SearchTrack? {
    val id = localTrackId ?: return null
    return SearchTrack(
        id = id,
        title = displayTitle,
        artist = artistName,
        album = album,
        durationSeconds = durationSeconds,
        artSha1 = artSha1,
        mbReleaseId = mbReleaseId,
    )
}
