package com.jamarr.android.history

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase

/** A play waiting to be uploaded to the server's history. */
@Entity(tableName = "pending_play")
data class PendingPlayEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val trackId: Long,
    /** Epoch millis the track started playing. */
    val playedAtMs: Long,
    val msPlayed: Long,
)

@Dao
interface PendingPlayDao {
    @Insert
    suspend fun insert(play: PendingPlayEntity)

    @Query("SELECT * FROM pending_play ORDER BY playedAtMs LIMIT :limit")
    suspend fun oldest(limit: Int): List<PendingPlayEntity>

    @Query("DELETE FROM pending_play WHERE id IN (:ids)")
    suspend fun delete(ids: List<Long>)

    @Query("SELECT COUNT(*) FROM pending_play")
    suspend fun count(): Int
}

/**
 * Its own database rather than a table in the downloads one: history has
 * nothing to do with what is on disk, and keeping it apart means neither
 * schema needs migrating for the other.
 */
@Database(entities = [PendingPlayEntity::class], version = 1, exportSchema = false)
abstract class OfflinePlayDatabase : RoomDatabase() {
    abstract fun pendingPlayDao(): PendingPlayDao

    companion object {
        fun build(context: Context): OfflinePlayDatabase =
            Room.databaseBuilder(
                context.applicationContext,
                OfflinePlayDatabase::class.java,
                "jamarr_history.db",
            ).build()
    }
}
