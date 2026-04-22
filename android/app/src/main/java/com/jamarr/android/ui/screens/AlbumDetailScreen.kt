package com.jamarr.android.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.jamarr.android.data.AlbumDetail
import com.jamarr.android.data.SearchTrack
import com.jamarr.android.ui.components.AlbumArt
import com.jamarr.android.ui.components.PlayShuffleActions
import com.jamarr.android.ui.components.TrackRow
import com.jamarr.android.ui.components.formatDuration
import com.jamarr.android.ui.components.formatTotalDuration
import com.jamarr.android.ui.components.seedColor
import com.jamarr.android.ui.state.LocalJamarrContext
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrShapes
import com.jamarr.android.ui.theme.JamarrType

@Composable
fun AlbumDetailScreen(
    albumMbid: String?,
    albumTitle: String?,
    artistName: String?,
    artistMbid: String?,
    onBack: () -> Unit,
    onArtistClick: () -> Unit,
    onPlayTracks: (List<SearchTrack>, Int) -> Unit,
    contentPadding: PaddingValues,
) {
    val ctx = LocalJamarrContext.current
    val detail = remember { mutableStateOf<AlbumDetail?>(null) }
    val tracks = remember { mutableStateOf<List<SearchTrack>>(emptyList()) }
    val errorState = remember { mutableStateOf<String?>(null) }

    LaunchedEffect(albumMbid, albumTitle, artistName, artistMbid) {
        errorState.value = null
        runCatching {
            ctx.apiClient.albumDetail(
                serverUrl = ctx.serverUrl,
                accessToken = ctx.accessToken,
                albumMbid = albumMbid,
                artistMbid = artistMbid,
            )
        }.onSuccess { detail.value = it }
            .onFailure { errorState.value = it.message }

        runCatching {
            ctx.apiClient.albumTracks(
                serverUrl = ctx.serverUrl,
                accessToken = ctx.accessToken,
                albumMbid = albumMbid,
                album = albumTitle,
                artist = artistName,
            )
        }.onSuccess { tracks.value = it }
            .onFailure { errorState.value = it.message }
    }

    val title = detail.value?.album ?: albumTitle ?: "Album"
    val artist = detail.value?.artistName ?: artistName ?: "Unknown artist"
    val year = (detail.value?.year ?: detail.value?.releaseDate)?.take(4)
    val trackCount = detail.value?.trackCount ?: tracks.value.size
    val totalDuration = detail.value?.totalDuration
        ?: tracks.value.mapNotNull { it.durationSeconds }.sum().takeIf { it > 0 }
    val artworkUrl = ctx.artworkUrl(detail.value?.artSha1, 800)
    val currentMediaId = ctx.playbackController.currentMediaId?.toLongOrNull()

    Box(modifier = Modifier.fillMaxSize().background(JamarrColors.Bg)) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                bottom = contentPadding.calculateBottomPadding() + 16.dp,
            ),
        ) {
            item {
                AlbumHero(
                    title = title,
                    artist = artist,
                    year = year,
                    trackCount = trackCount,
                    totalDuration = totalDuration,
                    artworkUrl = artworkUrl,
                    seed = title + artist,
                    onBack = onBack,
                    onArtistClick = onArtistClick,
                )
            }
            item {
                Column(modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding, vertical = 16.dp)) {
                    PlayShuffleActions(
                        onPlay = {
                            if (tracks.value.isNotEmpty()) {
                                onPlayTracks(tracks.value, 0)
                            }
                        },
                        onShuffle = {
                            if (tracks.value.isNotEmpty()) {
                                val shuffled = tracks.value.shuffled()
                                onPlayTracks(shuffled, 0)
                            }
                        },
                    )
                }
            }
            if (errorState.value != null && tracks.value.isEmpty()) {
                item {
                    Text(
                        text = errorState.value.orEmpty(),
                        style = JamarrType.Body,
                        color = JamarrColors.Muted,
                        modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding),
                    )
                }
            }
            items(tracks.value, key = { it.id }) { track ->
                TrackRow(
                    number = tracks.value.indexOf(track) + 1,
                    title = track.title,
                    subtitle = track.artist,
                    duration = formatDuration(track.durationSeconds),
                    active = currentMediaId == track.id,
                    onClick = {
                        val start = tracks.value.indexOf(track).coerceAtLeast(0)
                        onPlayTracks(tracks.value, start)
                    },
                )
            }
        }
    }
}

@Composable
private fun AlbumHero(
    title: String,
    artist: String,
    year: String?,
    trackCount: Int?,
    totalDuration: Double?,
    artworkUrl: String?,
    seed: String,
    onBack: () -> Unit,
    onArtistClick: () -> Unit,
) {
    val top = seedColor(seed)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .background(
                Brush.verticalGradient(
                    colors = listOf(top, JamarrColors.Bg),
                ),
            )
            .statusBarsPadding()
            .padding(horizontal = JamarrDims.ScreenPadding, vertical = 20.dp),
    ) {
        Box(
            modifier = Modifier
                .size(34.dp)
                .clip(CircleShape)
                .background(Color(0x66000000))
                .clickable(onClick = onBack),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = "←",
                color = Color.White,
                style = JamarrType.CardTitle,
            )
        }
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 46.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(
                modifier = Modifier
                    .size(180.dp)
                    .clip(JamarrShapes.AlbumArtLarge),
            ) {
                AlbumArt(
                    title = title,
                    seedName = seed,
                    artworkUrl = artworkUrl,
                    modifier = Modifier.fillMaxSize(),
                )
            }
            Spacer(Modifier.height(16.dp))
            Text(
                text = title,
                style = JamarrType.AlbumHeroTitle,
                color = JamarrColors.Text,
                textAlign = TextAlign.Center,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                text = artist,
                style = JamarrType.ArtistLink,
                color = JamarrColors.Primary,
                modifier = Modifier.clickable(onClick = onArtistClick),
            )
            Spacer(Modifier.height(6.dp))
            val metaParts = listOfNotNull(
                year,
                trackCount?.let { "$it track${if (it == 1) "" else "s"}" },
                formatTotalDuration(totalDuration),
            )
            if (metaParts.isNotEmpty()) {
                Text(
                    text = metaParts.joinToString(" · "),
                    style = JamarrType.Caption,
                    color = JamarrColors.Muted,
                )
            }
        }
    }
}
