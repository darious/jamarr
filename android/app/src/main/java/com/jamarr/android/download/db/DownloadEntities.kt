package com.jamarr.android.download.db

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * What the user asked for, as opposed to what is on disk.
 *
 * The bytes live in the Media3 download cache keyed by
 * `track:{id}:{quality}`; this database only records the intent and the
 * metadata needed to browse and play offline, when no API call can answer.
 */
@Entity(tableName = "downloaded_track")
data class DownloadedTrackEntity(
    @PrimaryKey val trackId: Long,
    val title: String,
    val artist: String?,
    val album: String?,
    val albumMbid: String?,
    val artistMbid: String?,
    val artSha1: String?,
    val durationSeconds: Double?,
    val quality: String,
    val sizeBytes: Long,
    val state: DownloadRecordState,
    val addedAt: Long,
)

/**
 * An album, artist, playlist or single track the user chose to download.
 *
 * Every download belongs to at least one group — a standalone track download
 * gets a [DownloadGroupKind.TRACK] group of its own. That keeps removal
 * uniform: a track is deleted once its last group goes, so an album a track
 * also belongs to still holds it.
 */
@Entity(tableName = "download_group")
data class DownloadGroupEntity(
    /** Deterministic, e.g. `album:{mbid}`, so re-requesting cannot duplicate. */
    @PrimaryKey val groupId: String,
    val kind: DownloadGroupKind,
    val title: String,
    val subtitle: String?,
    val artSha1: String?,
    val requestedAt: Long,
)

@Entity(
    tableName = "download_group_track",
    primaryKeys = ["groupId", "trackId"],
    foreignKeys = [
        ForeignKey(
            entity = DownloadGroupEntity::class,
            parentColumns = ["groupId"],
            childColumns = ["groupId"],
            onDelete = ForeignKey.CASCADE,
        ),
        ForeignKey(
            entity = DownloadedTrackEntity::class,
            parentColumns = ["trackId"],
            childColumns = ["trackId"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
    indices = [Index("trackId")],
)
data class DownloadGroupTrackEntity(
    val groupId: String,
    val trackId: Long,
    /** Playback order inside the group; album/playlist position. */
    val position: Int,
)

enum class DownloadGroupKind { TRACK, ALBUM, ARTIST, PLAYLIST }

enum class DownloadRecordState { QUEUED, DOWNLOADING, COMPLETED, FAILED }
