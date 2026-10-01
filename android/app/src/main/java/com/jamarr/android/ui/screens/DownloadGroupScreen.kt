package com.jamarr.android.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.jamarr.android.data.SearchTrack
import com.jamarr.android.download.DownloadProgress
import com.jamarr.android.download.db.DownloadGroupEntity
import com.jamarr.android.download.db.DownloadGroupKind
import com.jamarr.android.download.db.DownloadRecordState
import com.jamarr.android.download.db.DownloadedTrackEntity
import com.jamarr.android.download.groupDownloadStatus
import com.jamarr.android.ui.components.AlbumArt
import com.jamarr.android.ui.components.ConfirmDialog
import com.jamarr.android.ui.components.GroupDownloadButton
import com.jamarr.android.ui.components.PlayShuffleActions
import com.jamarr.android.ui.components.TrackRow
import com.jamarr.android.ui.components.formatDuration
import com.jamarr.android.ui.components.seedColor
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrShapes
import com.jamarr.android.ui.theme.JamarrType
import kotlinx.coroutines.flow.Flow

/**
 * One downloaded album, artist, playlist or top-tracks list, from Room.
 *
 * The online detail screens need the API; this one is how a group is browsed
 * and played while offline, and where it is removed.
 */
@Composable
fun DownloadGroupScreen(
    group: DownloadGroupEntity?,
    tracksFlow: Flow<List<DownloadedTrackEntity>>,
    downloadStates: Map<Long, DownloadProgress>,
    nowPlayingTrackId: Long?,
    artworkUrl: (String?, Int) -> String?,
    onBack: () -> Unit,
    onPlayTracks: (List<SearchTrack>, Int) -> Unit,
    onRemove: () -> Unit,
    contentPadding: PaddingValues,
) {
    val tracks by tracksFlow.collectAsState(initial = emptyList())
    var confirmRemove by remember { mutableStateOf(false) }
    val queue = tracks.map { it.toSearchTrack() }
    val status = groupDownloadStatus(tracks.map { it.trackId }, downloadStates)
    val title = group?.title ?: "Download"

    Box(modifier = Modifier.fillMaxSize().background(JamarrColors.Bg)) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(bottom = contentPadding.calculateBottomPadding() + 16.dp),
        ) {
            item {
                GroupHero(
                    title = title,
                    subtitle = listOfNotNull(
                        group?.subtitle?.takeIf { it.isNotBlank() },
                        if (group?.kind == DownloadGroupKind.ARTIST_TOP) "kept in sync" else null,
                        status?.let(::statusText),
                    ).joinToString(" · "),
                    artworkUrl = artworkUrl(group?.artSha1, 600),
                    onBack = onBack,
                )
            }
            item {
                PlayShuffleActions(
                    onPlay = { if (queue.isNotEmpty()) onPlayTracks(queue, 0) },
                    onShuffle = { if (queue.isNotEmpty()) onPlayTracks(queue.shuffled(), 0) },
                    trailing = if (group != null) {
                        { GroupDownloadButton(status = status, onClick = { confirmRemove = true }) }
                    } else {
                        null
                    },
                    modifier = Modifier.padding(horizontal = JamarrDims.ScreenPadding, vertical = 16.dp),
                )
            }
            itemsIndexed(tracks, key = { _, it -> it.trackId }) { index, entity ->
                val state = downloadStates[entity.trackId]
                TrackRow(
                    number = index + 1,
                    title = entity.title,
                    subtitle = listOfNotNull(entity.artist, entity.album)
                        .takeIf { it.isNotEmpty() }
                        ?.joinToString(" • "),
                    // Mid-download a row says how far along it is; the duration
                    // only matters once the track can actually be played.
                    duration = when (state?.state ?: entity.state) {
                        DownloadRecordState.COMPLETED -> formatDuration(entity.durationSeconds)
                        DownloadRecordState.DOWNLOADING -> state?.percent?.let { "${it.toInt()}%" } ?: "…"
                        DownloadRecordState.FAILED -> "failed"
                        DownloadRecordState.QUEUED -> "queued"
                    },
                    active = entity.trackId == nowPlayingTrackId,
                    onClick = { onPlayTracks(queue, index) },
                )
            }
        }
    }

    if (confirmRemove && group != null) {
        ConfirmDialog(
            title = "Remove download?",
            text = "$title will be removed from this device, except tracks another download still holds.",
            confirmLabel = "Remove",
            onConfirm = {
                confirmRemove = false
                onRemove()
            },
            onDismiss = { confirmRemove = false },
        )
    }
}

@Composable
private fun GroupHero(
    title: String,
    subtitle: String,
    artworkUrl: String?,
    onBack: () -> Unit,
) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .background(Brush.verticalGradient(listOf(seedColor(title), JamarrColors.Bg)))
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
            Box(modifier = Modifier.size(180.dp).clip(JamarrShapes.AlbumArtLarge)) {
                AlbumArt(
                    title = title,
                    seedName = title,
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
            if (subtitle.isNotBlank()) {
                Spacer(Modifier.height(6.dp))
                Text(text = subtitle, style = JamarrType.Caption, color = JamarrColors.Muted)
            }
        }
    }
}
