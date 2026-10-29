package com.jamarr.android.download.db

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.jamarr.android.download.DownloadFailureReason
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * A v1 install (no `failureReason` column) must open under the v2 schema with
 * its rows intact. The v1 DDL below is what Room generated for v1, so the
 * migration is exercised against the real on-disk shape rather than a mock.
 */
@RunWith(AndroidJUnit4::class)
class DownloadDatabaseMigrationTest {
    private val context: Context = ApplicationProvider.getApplicationContext()
    private val name = "migration-test.db"
    private var db: JamarrDownloadDatabase? = null

    @Before
    fun createV1() {
        context.deleteDatabase(name)
        context.openOrCreateDatabase(name, Context.MODE_PRIVATE, null).use { raw ->
            raw.execSQL(
                "CREATE TABLE IF NOT EXISTS `downloaded_track` (`trackId` INTEGER NOT NULL, `title` TEXT NOT NULL, " +
                    "`artist` TEXT, `album` TEXT, `albumMbid` TEXT, `artistMbid` TEXT, `artSha1` TEXT, " +
                    "`durationSeconds` REAL, `quality` TEXT NOT NULL, `sizeBytes` INTEGER NOT NULL, " +
                    "`state` TEXT NOT NULL, `addedAt` INTEGER NOT NULL, PRIMARY KEY(`trackId`))",
            )
            raw.execSQL(
                "CREATE TABLE IF NOT EXISTS `download_group` (`groupId` TEXT NOT NULL, `kind` TEXT NOT NULL, " +
                    "`title` TEXT NOT NULL, `subtitle` TEXT, `artSha1` TEXT, `requestedAt` INTEGER NOT NULL, " +
                    "PRIMARY KEY(`groupId`))",
            )
            raw.execSQL(
                "CREATE TABLE IF NOT EXISTS `download_group_track` (`groupId` TEXT NOT NULL, `trackId` INTEGER NOT NULL, " +
                    "`position` INTEGER NOT NULL, PRIMARY KEY(`groupId`, `trackId`), " +
                    "FOREIGN KEY(`groupId`) REFERENCES `download_group`(`groupId`) ON UPDATE NO ACTION ON DELETE CASCADE , " +
                    "FOREIGN KEY(`trackId`) REFERENCES `downloaded_track`(`trackId`) ON UPDATE NO ACTION ON DELETE CASCADE )",
            )
            raw.execSQL("CREATE INDEX IF NOT EXISTS `index_download_group_track_trackId` ON `download_group_track` (`trackId`)")
            raw.execSQL("CREATE TABLE IF NOT EXISTS room_master_table (id INTEGER PRIMARY KEY,identity_hash TEXT)")
            raw.execSQL(
                "INSERT INTO downloaded_track (trackId,title,artist,album,quality,sizeBytes,state,addedAt) " +
                    "VALUES (7,'Angel','Massive Attack','Mezzanine','flac_16_48',123,'FAILED',1)",
            )
            raw.execSQL("INSERT INTO download_group (groupId,kind,title,requestedAt) VALUES ('album:1','ALBUM','Mezzanine',1)")
            raw.execSQL("INSERT INTO download_group_track (groupId,trackId,position) VALUES ('album:1',7,0)")
            raw.version = 1
        }
    }

    @After
    fun tearDown() {
        db?.close()
        context.deleteDatabase(name)
    }

    @Test
    fun v1RowsSurviveAndGainANullReason() = runTest {
        val opened = Room.databaseBuilder(context, JamarrDownloadDatabase::class.java, name)
            .addMigrations(JamarrDownloadDatabase.MIGRATION_1_2)
            .build()
        db = opened
        val dao = opened.downloadDao()

        val track = dao.track(7)
        assertEquals("Angel", track?.title)
        assertEquals(DownloadRecordState.FAILED, track?.state)
        assertNull(track?.failureReason)
        assertEquals(listOf(7L), dao.groupTrackIds("album:1"))

        // And the new column is writable through the DAO.
        dao.updateState(7, DownloadRecordState.FAILED, 0L, DownloadFailureReason.STORAGE_FULL.name)
        assertEquals(DownloadFailureReason.STORAGE_FULL, DownloadFailureReason.fromName(dao.track(7)?.failureReason))
        assertEquals(listOf(7L), dao.failedTracksInGroup("album:1").map { it.trackId })
    }
}
