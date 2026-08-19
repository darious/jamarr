package com.jamarr.android.download.db

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Covers the group/track ownership rules, which decide when cached bytes are
 * safe to delete — the one piece of download bookkeeping that can lose a user's
 * downloads if it is wrong.
 */
@RunWith(AndroidJUnit4::class)
class DownloadDaoInstrumentedTest {
    private lateinit var db: JamarrDownloadDatabase
    private lateinit var dao: DownloadDao

    @Before
    fun setUp() {
        db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(),
            JamarrDownloadDatabase::class.java,
        ).build()
        dao = db.downloadDao()
    }

    @After
    fun tearDown() = db.close()

    @Test
    fun removingTheOnlyGroupOrphansItsTracks() = runTest {
        dao.addGroup(group("album:1", DownloadGroupKind.ALBUM), listOf(track(10), track(11)))

        val orphans = dao.removeGroup("album:1")

        assertEquals(listOf(10L, 11L), orphans.sorted())
        assertNull(dao.track(10))
        assertNull(dao.track(11))
    }

    @Test
    fun aTrackHeldByAnotherGroupSurvives() = runTest {
        dao.addGroup(group("album:1", DownloadGroupKind.ALBUM), listOf(track(10), track(11)))
        dao.addGroup(group("track:10", DownloadGroupKind.TRACK), listOf(track(10)))

        val orphans = dao.removeGroup("album:1")

        assertEquals(listOf(11L), orphans)
        assertNotNull(dao.track(10))
        assertNull(dao.track(11))
    }

    @Test
    fun requestingTheSameGroupTwiceDoesNotDuplicate() = runTest {
        dao.addGroup(group("album:1", DownloadGroupKind.ALBUM), listOf(track(10)))
        dao.addGroup(group("album:1", DownloadGroupKind.ALBUM), listOf(track(10)))

        assertEquals(listOf(10L), dao.groupTracks("album:1").map { it.trackId })
    }

    @Test
    fun groupTracksComeBackInRequestedOrder() = runTest {
        dao.addGroup(
            group("album:1", DownloadGroupKind.ALBUM),
            listOf(track(30), track(10), track(20)),
        )

        assertEquals(listOf(30L, 10L, 20L), dao.groupTracks("album:1").map { it.trackId })
    }

    @Test
    fun stateUpdatesLandOnTheTrack() = runTest {
        dao.addGroup(group("track:10", DownloadGroupKind.TRACK), listOf(track(10)))

        dao.updateState(10, DownloadRecordState.COMPLETED, sizeBytes = 4_096)

        val stored = dao.track(10)
        assertNotNull(stored)
        assertEquals(DownloadRecordState.COMPLETED, stored!!.state)
        assertEquals(4_096L, stored.sizeBytes)
    }

    @Test
    fun deletingAGroupCascadesItsLinks() = runTest {
        dao.addGroup(group("album:1", DownloadGroupKind.ALBUM), listOf(track(10)))

        dao.removeGroup("album:1")

        assertTrue(dao.groupTracks("album:1").isEmpty())
    }

    private fun group(id: String, kind: DownloadGroupKind) = DownloadGroupEntity(
        groupId = id,
        kind = kind,
        title = "Title",
        subtitle = "Artist",
        artSha1 = null,
        requestedAt = 0L,
    )

    private fun track(id: Long) = DownloadedTrackEntity(
        trackId = id,
        title = "Track $id",
        artist = "Artist",
        album = "Album",
        albumMbid = null,
        artistMbid = null,
        artSha1 = null,
        durationSeconds = 180.0,
        quality = "original",
        sizeBytes = 0L,
        state = DownloadRecordState.QUEUED,
        addedAt = 0L,
    )
}
