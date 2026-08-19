package com.jamarr.android.download.db

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

@Database(
    entities = [
        DownloadedTrackEntity::class,
        DownloadGroupEntity::class,
        DownloadGroupTrackEntity::class,
    ],
    version = 1,
    exportSchema = false,
)
abstract class JamarrDownloadDatabase : RoomDatabase() {
    abstract fun downloadDao(): DownloadDao

    companion object {
        fun build(context: Context): JamarrDownloadDatabase =
            Room.databaseBuilder(
                context.applicationContext,
                JamarrDownloadDatabase::class.java,
                "jamarr_downloads.db",
            ).build()
    }
}
