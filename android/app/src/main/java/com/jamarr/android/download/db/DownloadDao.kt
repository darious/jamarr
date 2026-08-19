package com.jamarr.android.download.db

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
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

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertTrack(track: DownloadedTrackEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertGroup(group: DownloadGroupEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertLinks(links: List<DownloadGroupTrackEntity>)

    @Query("UPDATE downloaded_track SET state = :state, sizeBytes = :sizeBytes WHERE trackId = :trackId")
    suspend fun updateState(trackId: Long, state: DownloadRecordState, sizeBytes: Long)

    @Query("DELETE FROM download_group WHERE groupId = :groupId")
    suspend fun deleteGroup(groupId: String)

    @Query("DELETE FROM downloaded_track WHERE trackId = :trackId")
    suspend fun deleteTrack(trackId: Long)

    /**
     * Tracks left with no group after a removal. Their cached bytes are the
     * caller's problem — the download cache is not touched from here.
     */
    @Query(
        """
        SELECT t.trackId FROM downloaded_track t
        LEFT JOIN download_group_track gt ON gt.trackId = t.trackId
        WHERE gt.trackId IS NULL
        """,
    )
    suspend fun orphanedTrackIds(): List<Long>

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
        tracks.forEach { upsertTrack(it) }
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
    suspend fun removeGroup(groupId: String): List<Long> {
        deleteGroup(groupId)
        val orphans = orphanedTrackIds()
        orphans.forEach { deleteTrack(it) }
        return orphans
    }
}
