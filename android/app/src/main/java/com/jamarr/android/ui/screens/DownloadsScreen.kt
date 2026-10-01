package com.jamarr.android.ui.screens

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
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.jamarr.android.data.OnlineState
import com.jamarr.android.data.SearchTrack
import com.jamarr.android.download.DownloadProgress
import com.jamarr.android.download.GroupDownloadStatus
import com.jamarr.android.download.db.DownloadGroupEntity
import com.jamarr.android.download.db.DownloadGroupKind
import com.jamarr.android.download.db.DownloadRecordState
import com.jamarr.android.download.db.DownloadedTrackEntity
import com.jamarr.android.download.formatBytes
import com.jamarr.android.download.groupDownloadStatus
import com.jamarr.android.ui.components.AlbumArt
import com.jamarr.android.ui.components.SubTabButton
import com.jamarr.android.ui.components.TrackRow
import com.jamarr.android.ui.components.formatDuration
import com.jamarr.android.ui.theme.JamarrColors
import com.jamarr.android.ui.theme.JamarrDims
import com.jamarr.android.ui.theme.JamarrShapes
import com.jamarr.android.ui.theme.JamarrType

private enum class DownloadsTab(val label: String) {
    Tracks("Tracks"),
    Albums("Albums"),
    Artists("Artists"),
    Playlists("Playlists"),
}

/** Which tab lists a group. Standalone track groups only show under Tracks. */
private fun DownloadGroupKind.tab(): DownloadsTab? = when (this) {
    DownloadGroupKind.ALBUM -> DownloadsTab.Albums
    DownloadGroupKind.ARTIST, DownloadGroupKind.ARTIST_TOP -> DownloadsTab.Artists
    DownloadGroupKind.PLAYLIST -> DownloadsTab.Playlists
    DownloadGroupKind.TRACK -> null
}

/**
 * What is on this device, by track, album, artist and playlist.
 *
 * Reads Room rather than the API, so it works with no server reachable — which
 * is why it doubles as the home screen while offline, with a banner saying so.
 */
@Composable
fun DownloadsScreen(
    tracks: List<DownloadedTrackEntity>,
    groups: List<DownloadGroupEntity>,
    groupTracks: Map<String, List<Long>>,
    downloadStates: Map<Long, DownloadProgress>,
    nowPlayingTrackId: Long?,
    onlineState: OnlineState,
    onGoOnline: () -> Unit,
    onTrackClick: (SearchTrack, List<SearchTrack>) -> Unit,
    onRemoveTrack: (Long) -> Unit,
    onGroupClick: (String) -> Unit,
    artworkUrl: (String?, Int) -> String?,
    contentPadding: PaddingValues = PaddingValues(0.dp),
) {
    var tab by rememberSaveable { mutableStateOf(DownloadsTab.Tracks) }
    val onDisk = tracks.filter { it.state == DownloadRecordState.COMPLETED }

    Column(modifier = Modifier.fillMaxSize().background(JamarrColors.Bg)) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .statusBarsPadding()
                .padding(horizontal = JamarrDims.ScreenPadding, vertical = 12.dp),
        ) {
            Text(text = "Downloads", style = JamarrType.ScreenTitle, color = JamarrColors.Text)
            Text(
                text = if (tracks.isEmpty()) {
                    "Nothing downloaded yet"
                } else {
                    "${onDisk.size} of ${tracks.size} ${plural(tracks.size, "track")} on this device · " +
                        formatBytes(onDisk.sumOf { it.sizeBytes })
                },
                style = JamarrType.Body,
                color = JamarrColors.Muted,
            )
        }

        if (onlineState.isOffline) {
            OfflineBanner(onlineState = onlineState, onGoOnline = onGoOnline)
            Spacer(Modifier.height(12.dp))
        }

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = JamarrDims.ScreenPadding),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            DownloadsTab.entries.forEach { entry ->
                SubTabButton(
                    label = entry.label,
                    selected = tab == entry,
                    onClick = { tab = entry },
                    modifier = Modifier.weight(1f),
                )
            }
        }
        Spacer(Modifier.height(12.dp))

        if (tab == DownloadsTab.Tracks) {
            TracksTab(
                tracks = tracks,
                downloadStates = downloadStates,
                nowPlayingTrackId = nowPlayingTrackId,
                onTrackClick = onTrackClick,
                onRemoveTrack = onRemoveTrack,
                contentPadding = contentPadding,
            )
        } else {
            val tabGroups = groups
                .filter { it.kind.tab() == tab }
                .sortedWith(compareBy({ it.title.lowercase() }, { it.subtitle.orEmpty() }))
            GroupsTab(
                groups = tabGroups,
                emptyText = when (tab) {
                    DownloadsTab.Albums -> "Use the download button on an album to keep it here."
                    DownloadsTab.Artists -> "Download an artist's releases or top tracks from their page."
                    else -> "Use the download button on a playlist to keep it here."
                },
                statusFor = { groupDownloadStatus(groupTracks[it.groupId].orEmpty(), downloadStates) },
                onGroupClick = onGroupClick,
                artworkUrl = artworkUrl,
                contentPadding = contentPadding,
            )
        }
    }
}

@Composable
private fun TracksTab(
    tracks: List<DownloadedTrackEntity>,
    downloadStates: Map<Long, DownloadProgress>,
    nowPlayingTrackId: Long?,
    onTrackClick: (SearchTrack, List<SearchTrack>) -> Unit,
    onRemoveTrack: (Long) -> Unit,
    contentPadding: PaddingValues,
) {
    if (tracks.isEmpty()) {
        EmptyText("Tap the download arrow on any track to keep it on this device.")
        return
    }
    val queue = tracks.map { it.toSearchTrack() }
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
                onDownloadClick = { onRemoveTrack(entity.trackId) },
            )
        }
    }
}

@Composable
private fun GroupsTab(
    groups: List<DownloadGroupEntity>,
    emptyText: String,
    statusFor: (DownloadGroupEntity) -> GroupDownloadStatus?,
    onGroupClick: (String) -> Unit,
    artworkUrl: (String?, Int) -> String?,
    contentPadding: PaddingValues,
) {
    if (groups.isEmpty()) {
        EmptyText(emptyText)
        return
    }
    LazyColumn(contentPadding = contentPadding) {
        items(groups, key = { it.groupId }) { group ->
            GroupRow(
                group = group,
                status = statusFor(group),
                artworkUrl = artworkUrl(group.artSha1, 200),
                onClick = { onGroupClick(group.groupId) },
            )
        }
    }
}

@Composable
private fun GroupRow(
    group: DownloadGroupEntity,
    status: GroupDownloadStatus?,
    artworkUrl: String?,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = JamarrDims.ScreenPadding, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(modifier = Modifier.size(52.dp).clip(JamarrShapes.AlbumArt)) {
            AlbumArt(
                title = group.title,
                seedName = group.title + group.subtitle.orEmpty(),
                artworkUrl = artworkUrl,
                modifier = Modifier.fillMaxSize(),
            )
        }
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = group.title,
                style = JamarrType.CardTitle,
                color = JamarrColors.Text,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = listOfNotNull(
                    group.subtitle?.takeIf { it.isNotBlank() },
                    if (group.kind == DownloadGroupKind.ARTIST_TOP) "kept in sync" else null,
                    status?.let(::statusText),
                ).joinToString(" · "),
                style = JamarrType.CaptionSmall,
                color = JamarrColors.Muted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

/** "12 tracks", "4 of 12 tracks", or the failure count when there is one. */
internal fun statusText(status: GroupDownloadStatus): String = when {
    status.isComplete -> "${status.total} ${plural(status.total, "track")}"
    status.hasFailures -> "${status.failed} failed"
    else -> "${status.completed} of ${status.total} ${plural(status.total, "track")}"
}

@Composable
internal fun OfflineBanner(onlineState: OnlineState, onGoOnline: () -> Unit) {
    val reason = when {
        onlineState.manualOffline -> "Offline mode is on."
        !onlineState.networkAvailable -> "No network connection."
        else -> "Can't reach the server."
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = JamarrDims.ScreenPadding)
            .clip(JamarrShapes.Card)
            .background(JamarrColors.Card)
            .padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(text = reason, style = JamarrType.CardTitle, color = JamarrColors.Text)
            Text(
                text = "Playing from this device.",
                style = JamarrType.CaptionSmall,
                color = JamarrColors.Muted,
            )
        }
        if (onlineState.manualOffline) {
            Text(
                text = "Go online",
                style = JamarrType.Caption,
                color = JamarrColors.Primary,
                modifier = Modifier
                    .clickable(onClick = onGoOnline)
                    .padding(8.dp),
            )
        }
    }
}

@Composable
private fun EmptyText(text: String) {
    Text(
        text = text,
        style = JamarrType.Body,
        color = JamarrColors.Neutral,
        modifier = Modifier.padding(JamarrDims.ScreenPadding),
    )
}

internal fun plural(count: Int, noun: String): String = if (count == 1) noun else "${noun}s"

internal fun DownloadedTrackEntity.toSearchTrack(): SearchTrack = SearchTrack(
    id = trackId,
    title = title,
    artist = artist,
    album = album,
    mbReleaseId = albumMbid,
    durationSeconds = durationSeconds,
    artSha1 = artSha1,
)
