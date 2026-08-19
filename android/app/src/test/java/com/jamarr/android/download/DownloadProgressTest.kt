package com.jamarr.android.download

import androidx.media3.exoplayer.offline.Download
import com.jamarr.android.download.db.DownloadRecordState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DownloadProgressTest {
    @Test
    fun `media3 states map onto record states`() {
        assertEquals(DownloadRecordState.COMPLETED, recordState(Download.STATE_COMPLETED))
        assertEquals(DownloadRecordState.FAILED, recordState(Download.STATE_FAILED))
        assertEquals(DownloadRecordState.DOWNLOADING, recordState(Download.STATE_DOWNLOADING))
        assertEquals(DownloadRecordState.QUEUED, recordState(Download.STATE_QUEUED))
    }

    @Test
    fun `states that will run again read as queued`() {
        // A stopped or restarting download is still going to happen, and the UI
        // has no separate affordance for either.
        assertEquals(DownloadRecordState.QUEUED, recordState(Download.STATE_STOPPED))
        assertEquals(DownloadRecordState.QUEUED, recordState(Download.STATE_RESTARTING))
    }

    @Test
    fun `only a completed download counts as on device`() {
        assertTrue(progress(DownloadRecordState.COMPLETED).isComplete)
        assertFalse(progress(DownloadRecordState.DOWNLOADING).isComplete)
        assertFalse(progress(DownloadRecordState.FAILED).isComplete)
    }

    private fun progress(state: DownloadRecordState) =
        DownloadProgress(trackId = 1L, state = state, percent = null)
}
