package com.jamarr.android.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.jamarr.android.data.SearchTrack
import com.jamarr.android.download.DownloadProgress
import com.jamarr.android.download.db.DownloadedTrackEntity
import com.jamarr.android.ui.components.TrackRow
import com.jamarr.android.ui.components.formatDuration
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrType

/**
 * What the user has downloaded, newest first.
 *
 * Reads Room rather than the API, so it is the one screen that already works
 * with no server reachable. The offline-mode routing that makes the rest of the
 * app fall back here is phase 3.
 */
@Composable
fun DownloadsScreen(
    tracks: List<DownloadedTrackEntity>,
    downloadStates: Map<Long, DownloadProgress>,
    nowPlayingTrackId: Long?,
    onTrackClick: (SearchTrack, List<SearchTrack>) -> Unit,
    onRemove: (Long) -> Unit,
    contentPadding: PaddingValues = PaddingValues(0.dp),
) {
    val queue = tracks.map { it.toSearchTrack() }

    Column(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .statusBarsPadding()
                .padding(horizontal = JamarrDims.ScreenPadding, vertical = 12.dp),
        ) {
            Text(
                text = "Downloads",
                style = JamarrType.ScreenTitle,
                color = JamarrColors.Text,
            )
            Text(
                text = if (tracks.isEmpty()) {
                    "Nothing downloaded yet"
                } else {
                    "${tracks.size} ${if (tracks.size == 1) "track" else "tracks"} on this device"
                },
                style = JamarrType.Body,
                color = JamarrColors.Muted,
            )
        }

        if (tracks.isEmpty()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(JamarrDims.ScreenPadding),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "Tap the download arrow on any track to keep it on this device.",
                    style = JamarrType.Body,
                    color = JamarrColors.Neutral,
                )
            }
            return@Column
        }

        LazyColumn(contentPadding = contentPadding) {
            items(tracks, key = { it.trackId }) { entity ->
                TrackRow(
                    number = null,
                    title = entity.title,
                    subtitle = listOfNotNull(entity.artist, entity.album)
                        .takeIf { it.isNotEmpty() }
                        ?.joinToString(" • "),
                    duration = formatDuration(entity.durationSeconds),
                    active = entity.trackId == nowPlayingTrackId,
                    onClick = { onTrackClick(entity.toSearchTrack(), queue) },
                    downloadState = downloadStates[entity.trackId],
                    onDownloadClick = { onRemove(entity.trackId) },
                )
            }
        }
    }
}

private fun DownloadedTrackEntity.toSearchTrack(): SearchTrack = SearchTrack(
    id = trackId,
    title = title,
    artist = artist,
    album = album,
    mbReleaseId = albumMbid,
    durationSeconds = durationSeconds,
    artSha1 = artSha1,
)
