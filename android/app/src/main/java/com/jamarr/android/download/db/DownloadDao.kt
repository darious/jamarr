package com.jamarr.android.download.db

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

@Dao
interface DownloadDao {
    @Query("SELECT * FROM downloaded_track ORDER BY addedAt DESC")
    fun observeTracks(): Flow<List<DownloadedTrackEntity>>

    @Query("SELECT * FROM downloaded_track WHERE state = :state ORDER BY addedAt DESC")
    fun observeTracksByState(state: DownloadRecordState): Flow<List<DownloadedTrackEntity>>

    @Query("SELECT * FROM downloaded_track WHERE trackId = :trackId")
    suspend fun track(trackId: Long): DownloadedTrackEntity?

    @Query("SELECT * FROM download_group ORDER BY requestedAt DESC")
    fun observeGroups(): Flow<List<DownloadGroupEntity>>

    @Query("SELECT * FROM download_group WHERE kind = :kind ORDER BY requestedAt DESC")
    fun observeGroups(kind: DownloadGroupKind): Flow<List<DownloadGroupEntity>>

    @Query(
        """
        SELECT t.* FROM downloaded_track t
        JOIN download_group_track gt ON gt.trackId = t.trackId
        WHERE gt.groupId = :groupId
        ORDER BY gt.position
        """,
    )
    suspend fun groupTracks(groupId: String): List<DownloadedTrackEntity>

    @Query("SELECT * FROM download_group WHERE groupId = :groupId")
    suspend fun group(groupId: String): DownloadGroupEntity?

    @Query("SELECT * FROM download_group WHERE kind = :kind")
    suspend fun groups(kind: DownloadGroupKind): List<DownloadGroupEntity>

    @Query("SELECT * FROM download_group ORDER BY title COLLATE NOCASE")
    suspend fun allGroups(): List<DownloadGroupEntity>

    @Query("SELECT * FROM downloaded_track WHERE state = :state ORDER BY addedAt DESC")
    suspend fun tracksByState(state: DownloadRecordState): List<DownloadedTrackEntity>

    /** Every group membership; small enough to hold whole for the UI. */
    @Query("SELECT * FROM download_group_track")
    fun observeLinks(): Flow<List<DownloadGroupTrackEntity>>

    @Query(
        """
        SELECT t.* FROM downloaded_track t
        JOIN download_group_track gt ON gt.trackId = t.trackId
        WHERE gt.groupId = :groupId
        ORDER BY gt.position
        """,
    )
    fun observeGroupTracks(groupId: String): Flow<List<DownloadedTrackEntity>>

    @Query("SELECT trackId FROM download_group_track WHERE groupId = :groupId ORDER BY position")
    suspend fun groupTrackIds(groupId: String): List<Long>

    /** Art still referenced by something on disk; everything else can go. */
    @Query(
        """
        SELECT artSha1 FROM downloaded_track WHERE artSha1 IS NOT NULL
        UNION
        SELECT artSha1 FROM download_group WHERE artSha1 IS NOT NULL
        """,
    )
    suspend fun referencedArtSha1s(): List<String>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertTrack(track: DownloadedTrackEntity)

    /**
     * A track another group already holds keeps its row: replacing it would
     * reset a finished download's state to queued.
     */
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertTrackIfAbsent(track: DownloadedTrackEntity)

    /** An update in place: REPLACE would delete the row and cascade its links away. */
    @Upsert
    suspend fun upsertGroup(group: DownloadGroupEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertLinks(links: List<DownloadGroupTrackEntity>)

    @Query("UPDATE downloaded_track SET state = :state, sizeBytes = :sizeBytes WHERE trackId = :trackId")
    suspend fun updateState(trackId: Long, state: DownloadRecordState, sizeBytes: Long)

    @Query("DELETE FROM download_group WHERE groupId = :groupId")
    suspend fun deleteGroup(groupId: String)

    @Query("DELETE FROM downloaded_track WHERE trackId = :trackId")
    suspend fun deleteTrack(trackId: Long)

    @Query("DELETE FROM download_group_track WHERE groupId = :groupId")
    suspend fun deleteLinks(groupId: String)

    /**
     * Tracks left with no group after a removal. Their cached bytes are the
     * caller's problem — the download cache is not touched from here. Whole
     * rows, because the bytes are keyed by the quality each was fetched at.
     */
    @Query(
        """
        SELECT t.* FROM downloaded_track t
        LEFT JOIN download_group_track gt ON gt.trackId = t.trackId
        WHERE gt.trackId IS NULL
        """,
    )
    suspend fun orphanedTracks(): List<DownloadedTrackEntity>

    /**
     * Records a request and its tracks in one go, so a crash mid-write cannot
     * leave a group pointing at rows that were never inserted.
     */
    @Transaction
    suspend fun addGroup(
        group: DownloadGroupEntity,
        tracks: List<DownloadedTrackEntity>,
    ) {
        upsertGroup(group)
        tracks.forEach { insertTrackIfAbsent(it) }
        upsertLinks(
            tracks.mapIndexed { index, track ->
                DownloadGroupTrackEntity(
                    groupId = group.groupId,
                    trackId = track.trackId,
                    position = index,
                )
            },
        )
    }

    /**
     * Drops a group and returns the tracks that no other group still holds, so
     * the caller can remove exactly those from the download cache.
     */
    @Transaction
    suspend fun removeGroup(groupId: String): List<DownloadedTrackEntity> {
        deleteGroup(groupId)
        val orphans = orphanedTracks()
        orphans.forEach { deleteTrack(it.trackId) }
        return orphans
    }

    /**
     * Points a group at a new track list — the top-tracks sync — and returns
     * the tracks that no group holds any more, for the caller to delete from
     * the download cache. Positions follow [tracks]' order.
     */
    @Transaction
    suspend fun replaceGroupTracks(
        group: DownloadGroupEntity,
        tracks: List<DownloadedTrackEntity>,
    ): List<DownloadedTrackEntity> {
        deleteLinks(group.groupId)
        addGroup(group, tracks)
        val orphans = orphanedTracks()
        orphans.forEach { deleteTrack(it.trackId) }
        return orphans
    }

    /** Everything, for "delete all downloads". */
    @Transaction
    suspend fun removeAll(): List<DownloadedTrackEntity> {
        val all = allTracks()
        deleteAllGroups()
        deleteAllTracks()
        return all
    }

    @Query("SELECT * FROM downloaded_track")
    suspend fun allTracks(): List<DownloadedTrackEntity>

    @Query("DELETE FROM download_group")
    suspend fun deleteAllGroups()

    @Query("DELETE FROM downloaded_track")
    suspend fun deleteAllTracks()
}
