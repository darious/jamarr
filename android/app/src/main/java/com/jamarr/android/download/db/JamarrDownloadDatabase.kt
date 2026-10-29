package com.jamarr.android.download.db

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(
    entities = [
        DownloadedTrackEntity::class,
        DownloadGroupEntity::class,
        DownloadGroupTrackEntity::class,
    ],
    version = 2,
    exportSchema = false,
)
abstract class JamarrDownloadDatabase : RoomDatabase() {
    abstract fun downloadDao(): DownloadDao

    companion object {
        /** v2: a failed download remembers why (`failureReason`), which Media3's index does not. */
        val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE downloaded_track ADD COLUMN failureReason TEXT DEFAULT NULL")
            }
        }

        fun build(context: Context): JamarrDownloadDatabase =
            Room.databaseBuilder(
                context.applicationContext,
                JamarrDownloadDatabase::class.java,
                "jamarr_downloads.db",
            ).addMigrations(MIGRATION_1_2).build()
    }
}
