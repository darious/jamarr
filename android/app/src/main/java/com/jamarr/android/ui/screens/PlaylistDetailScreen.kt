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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
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
import com.jamarr.android.data.PlaylistDetail
import com.jamarr.android.data.PlaylistTrack
import com.jamarr.android.data.SearchTrack
import com.jamarr.android.ui.components.PlayShuffleActions
import com.jamarr.android.ui.components.PlaylistCover
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
fun PlaylistDetailScreen(
    playlistId: Long,
    onBack: () -> Unit,
    onPlayTracks: (List<SearchTrack>, Int) -> Unit,
    contentPadding: PaddingValues,
) {
    val ctx = LocalJamarrContext.current
    val detail = remember { mutableStateOf<PlaylistDetail?>(null) }
    val error = remember { mutableStateOf<String?>(null) }

    LaunchedEffect(playlistId) {
        error.value = null
        runCatching { ctx.apiClient.playlistDetail(ctx.serverUrl, ctx.accessToken, playlistId) }
            .onSuccess { detail.value = it }
            .onFailure { error.value = it.message }
    }

    val d = detail.value
    val tracks = d?.tracks.orEmpty()
    val searchTracks = remember(tracks) { tracks.map { it.toSearchTrack() } }
    val currentMediaId = ctx.playbackController.currentMediaId?.toLongOrNull()

    Box(modifier = Modifier.fillMaxSize().background(JamarrColors.Bg)) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                bottom = contentPadding.calculateBottomPadding() + 16.dp,
            ),
        ) {
            item {
                val thumbs = tracks.mapNotNull { it.artSha1 }.distinct().take(4)
                PlaylistHero(
                    title = d?.name ?: "Playlist",
                    description = d?.description,
                    trackCount = d?.trackCount ?: tracks.size,
                    totalDuration = d?.totalDuration?.takeIf { it > 0 },
                    thumbnails = thumbs,
                    artworkUrlFor = { sha -> ctx.artworkUrl(sha, 400) },
                    seed = d?.name ?: "Playlist",
                    onBack = onBack,
                )
            }
            item {
                Column(modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding, vertical = 16.dp)) {
                    PlayShuffleActions(
                        onPlay = {
                            if (searchTracks.isNotEmpty()) onPlayTracks(searchTracks, 0)
                        },
                        onShuffle = {
                            if (searchTracks.isNotEmpty()) {
                                onPlayTracks(searchTracks.shuffled(), 0)
                            }
                        },
                    )
                }
            }
            if (error.value != null && tracks.isEmpty()) {
                item {
                    Text(
                        text = error.value.orEmpty(),
                        style = JamarrType.Body,
                        color = JamarrColors.Muted,
                        modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding),
                    )
                }
            }
            itemsIndexed(tracks, key = { _, it -> it.playlistTrackId }) { index, track ->
                TrackRow(
                    number = index + 1,
                    title = track.title,
                    subtitle = listOfNotNull(track.artist, track.album)
                        .filter { it.isNotBlank() }
                        .joinToString(" · ")
                        .ifBlank { null },
                    duration = formatDuration(track.durationSeconds),
                    active = currentMediaId == track.trackId,
                    onClick = { onPlayTracks(searchTracks, index) },
                )
            }
        }
    }
}

@Composable
private fun PlaylistHero(
    title: String,
    description: String?,
    trackCount: Int,
    totalDuration: Double?,
    thumbnails: List<String>,
    artworkUrlFor: (String) -> String?,
    seed: String,
    onBack: () -> Unit,
) {
    val top = seedColor(seed)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .background(Brush.verticalGradient(listOf(top, JamarrColors.Bg)))
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
            Text(text = "←", color = Color.White, style = JamarrType.CardTitle)
        }
        Column(
            modifier = Modifier.fillMaxWidth().padding(top = 46.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            PlaylistCover(
                title = title,
                seedName = seed,
                thumbnails = thumbnails,
                artworkUrlFor = artworkUrlFor,
                modifier = Modifier
                    .size(180.dp)
                    .clip(JamarrShapes.AlbumArtLarge),
            )
            Spacer(Modifier.height(16.dp))
            Text(
                text = title,
                style = JamarrType.AlbumHeroTitle,
                color = JamarrColors.Text,
                textAlign = TextAlign.Center,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            if (!description.isNullOrBlank()) {
                Spacer(Modifier.height(6.dp))
                Text(
                    text = description,
                    style = JamarrType.Body,
                    color = JamarrColors.Muted,
                    textAlign = TextAlign.Center,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Spacer(Modifier.height(8.dp))
            val metaParts = listOfNotNull(
                "$trackCount track${if (trackCount == 1) "" else "s"}",
                formatTotalDuration(totalDuration),
            )
            Text(
                text = metaParts.joinToString(" · "),
                style = JamarrType.Caption,
                color = JamarrColors.Muted,
            )
        }
    }
}

private fun PlaylistTrack.toSearchTrack(): SearchTrack = SearchTrack(
    id = trackId,
    title = title,
    artist = artist,
    album = album,
    durationSeconds = durationSeconds,
    artSha1 = artSha1,
)
