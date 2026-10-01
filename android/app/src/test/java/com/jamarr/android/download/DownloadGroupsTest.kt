package com.jamarr.android.download

import com.jamarr.android.data.SearchTrack
import com.jamarr.android.data.TopTrackList
import com.jamarr.android.download.db.DownloadRecordState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DownloadGroupsTest {
    @Test
    fun `top-tracks group ids round-trip`() {
        val id = DownloadGroupIds.artistTop("mbid-1", TopTrackList.MostListened)

        assertEquals("artist_top:mbid-1:listened", id)
        assertEquals("mbid-1" to TopTrackList.MostListened, DownloadGroupIds.parseArtistTop(id))
    }

    @Test
    fun `other group ids do not parse as top-tracks`() {
        assertNull(DownloadGroupIds.parseArtistTop(DownloadGroupIds.artist("mbid-1")))
        assertNull(DownloadGroupIds.parseArtistTop("artist_top::scrobbled"))
        assertNull(DownloadGroupIds.parseArtistTop("artist_top:mbid-1:unknown"))
    }

    @Test
    fun `an empty group has no status`() {
        assertNull(groupDownloadStatus(emptyList(), emptyMap()))
    }

    @Test
    fun `a track with no state yet counts as queued`() {
        val status = groupDownloadStatus(listOf(1L, 2L), mapOf(1L to progress(1, DownloadRecordState.COMPLETED)))!!

        assertEquals(2, status.total)
        assertEquals(1, status.completed)
        assertFalse(status.isComplete)
        assertEquals(50f, status.percent)
    }

    @Test
    fun `progress averages over the whole group`() {
        val status = groupDownloadStatus(
            listOf(1L, 2L),
            mapOf(
                1L to progress(1, DownloadRecordState.COMPLETED),
                2L to progress(2, DownloadRecordState.DOWNLOADING, percent = 50f),
            ),
        )!!

        assertEquals(75f, status.percent)
    }

    @Test
    fun `a failed track is reported, not hidden in the percentage`() {
        val status = groupDownloadStatus(
            listOf(1L, 2L),
            mapOf(
                1L to progress(1, DownloadRecordState.COMPLETED),
                2L to progress(2, DownloadRecordState.FAILED),
            ),
        )!!

        assertTrue(status.hasFailures)
        assertFalse(status.isComplete)
    }

    @Test
    fun `size estimate uses each track's bitrate`() {
        val tracks = listOf(track(seconds = 100.0, bitrate = 800_000L))

        assertEquals(10_000_000L, estimateDownloadBytes(tracks))
    }

    @Test
    fun `size estimate falls back to a lossless bitrate`() {
        val tracks = listOf(track(seconds = 8.0, bitrate = null), track(seconds = 8.0, bitrate = 0L))

        assertEquals(2 * FALLBACK_BITRATE_BPS, estimateDownloadBytes(tracks))
    }

    @Test
    fun `size estimate follows the download quality`() {
        val hiRes = listOf(track(seconds = 80.0, bitrate = 4_000_000L))

        assertEquals(40_000_000L, estimateDownloadBytes(hiRes, "original"))
        assertEquals(10_000_000L, estimateDownloadBytes(hiRes, "flac_16_48"))
        assertEquals(3_200_000L, estimateDownloadBytes(hiRes, "mp3_320"))
        // A FLAC rung never estimates above a smaller source.
        assertEquals(5_000_000L, estimateDownloadBytes(listOf(track(seconds = 80.0, bitrate = 500_000L)), "flac_24_48"))
    }

    @Test
    fun `byte counts format as MB below a gigabyte`() {
        assertEquals("1 MB", formatBytes(10))
        assertEquals("512 MB", formatBytes(512L * 1024 * 1024))
        assertEquals("2.5 GB", formatBytes(5L * 1024 * 1024 * 1024 / 2))
    }

    private fun progress(id: Long, state: DownloadRecordState, percent: Float? = null) =
        DownloadProgress(trackId = id, state = state, percent = percent)

    private fun track(seconds: Double, bitrate: Long?) =
        SearchTrack(id = 1L, title = "t", durationSeconds = seconds, bitrate = bitrate)
}
