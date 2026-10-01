package com.jamarr.android.history

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PendingPlayDaoInstrumentedTest {
    private lateinit var db: OfflinePlayDatabase
    private lateinit var dao: PendingPlayDao

    @Before
    fun setUp() {
        db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(),
            OfflinePlayDatabase::class.java,
        ).build()
        dao = db.pendingPlayDao()
    }

    @After
    fun tearDown() = db.close()

    @Test
    fun playsComeBackOldestFirstInBatches() = runTest {
        dao.insert(PendingPlayEntity(trackId = 3, playedAtMs = 300, msPlayed = 40_000))
        dao.insert(PendingPlayEntity(trackId = 1, playedAtMs = 100, msPlayed = 40_000))
        dao.insert(PendingPlayEntity(trackId = 2, playedAtMs = 200, msPlayed = 40_000))

        assertEquals(listOf(1L, 2L), dao.oldest(2).map { it.trackId })
    }

    @Test
    fun uploadedPlaysAreDeletedByIdOnly() = runTest {
        dao.insert(PendingPlayEntity(trackId = 1, playedAtMs = 100, msPlayed = 40_000))
        dao.insert(PendingPlayEntity(trackId = 2, playedAtMs = 200, msPlayed = 40_000))
        val first = dao.oldest(1)

        dao.delete(first.map { it.id })

        assertEquals(listOf(2L), dao.oldest(10).map { it.trackId })
        assertEquals(1, dao.count())
    }
}
