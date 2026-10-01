package com.jamarr.android.download

import com.jamarr.android.data.SearchTrack
import com.jamarr.android.data.TopTrackList
import com.jamarr.android.download.db.DownloadGroupKind
import com.jamarr.android.download.db.DownloadRecordState

/**
 * Deterministic group ids, so asking for the same thing twice updates one
 * group instead of creating a duplicate.
 *
 * The album id is whatever MBID the album screen was opened with — usually the
 * release group, since that is what the API calls `album_mbid` — because the
 * screen's track list is what the download has to match.
 */
object DownloadGroupIds {
    fun track(trackId: Long): String = "track:$trackId"
    fun album(albumMbid: String): String = "album:$albumMbid"
    fun playlist(playlistId: Long): String = "playlist:$playlistId"
    fun artist(artistMbid: String): String = "artist:$artistMbid"
    fun artistTop(artistMbid: String, list: TopTrackList): String =
        "artist_top:$artistMbid:${list.key}"

    /** The artist and list a synced top-tracks group follows, or null. */
    fun parseArtistTop(groupId: String): Pair<String, TopTrackList>? {
        val parts = groupId.split(':')
        if (parts.size != 3 || parts[0] != "artist_top" || parts[1].isBlank()) return null
        val list = TopTrackList.fromKey(parts[2]) ?: return null
        return parts[1] to list
    }
}

/** Everything needed to download a group, gathered by the screen showing it. */
data class GroupDownloadRequest(
    val groupId: String,
    val kind: DownloadGroupKind,
    val title: String,
    val subtitle: String?,
    val artSha1: String?,
    val tracks: List<SearchTrack>,
    val artistMbid: String? = null,
)

/** What a group's download button shows, aggregated over its tracks. */
data class GroupDownloadStatus(
    val total: Int,
    val completed: Int,
    val failed: Int,
    /** Mean progress across the group, 0..100. */
    val percent: Float,
) {
    val isComplete: Boolean get() = total > 0 && completed == total
    val hasFailures: Boolean get() = failed > 0
}

/**
 * Null when nothing in the group has been requested. A track with no state yet
 * counts as queued: the request is recorded before Media3 reports on it.
 */
fun groupDownloadStatus(
    trackIds: Collection<Long>,
    states: Map<Long, DownloadProgress>,
): GroupDownloadStatus? {
    if (trackIds.isEmpty()) return null
    var completed = 0
    var failed = 0
    var percentSum = 0f
    trackIds.forEach { id ->
        val state = states[id]
        when (state?.state) {
            DownloadRecordState.COMPLETED -> {
                completed++
                percentSum += 100f
            }
            DownloadRecordState.FAILED -> failed++
            DownloadRecordState.DOWNLOADING -> percentSum += state.percent ?: 0f
            DownloadRecordState.QUEUED, null -> Unit
        }
    }
    return GroupDownloadStatus(
        total = trackIds.size,
        completed = completed,
        failed = failed,
        percent = percentSum / trackIds.size,
    )
}

/**
 * The library's median FLAC bitrate. Stands in for a track whose bitrate the
 * server did not send, so an estimate errs towards a realistic lossless size.
 */
const val FALLBACK_BITRATE_BPS = 968_000L

/**
 * Rough on-disk size of downloading [tracks] at [quality]. Lossy rungs are
 * fixed-rate; the FLAC rungs are capped at about what a 48 kHz FLAC of that
 * depth compresses to, and never exceed the source (the server does not
 * upsample a download onto a bigger file).
 */
fun estimateDownloadBytes(tracks: Collection<SearchTrack>, quality: String = "original"): Long =
    tracks.sumOf { track ->
        val seconds = track.durationSeconds ?: 0.0
        val source = track.bitrate?.takeIf { it > 0 } ?: FALLBACK_BITRATE_BPS
        val bitrate = when (quality) {
            "mp3_320" -> 320_000L
            "opus_128" -> 128_000L
            "flac_16_48" -> minOf(source, FLAC_16_48_BPS)
            "flac_24_48" -> minOf(source, FLAC_24_48_BPS)
            else -> source
        }
        (seconds * bitrate / 8).toLong()
    }

private const val FLAC_16_48_BPS = 1_000_000L
private const val FLAC_24_48_BPS = 1_500_000L

fun formatBytes(bytes: Long): String {
    val gib = bytes / (1024.0 * 1024 * 1024)
    if (gib >= 1) return "%.1f GB".format(gib)
    val mib = bytes / (1024.0 * 1024)
    return "%.0f MB".format(mib.coerceAtLeast(1.0))
}
