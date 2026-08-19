package com.jamarr.android.download

import androidx.annotation.OptIn
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.offline.Download
import com.jamarr.android.download.db.DownloadRecordState

/** UI-facing view of one track's download, merged from Media3 and Room. */
data class DownloadProgress(
    val trackId: Long,
    val state: DownloadRecordState,
    /** 0..100, or null while the total size is still unknown. */
    val percent: Float?,
) {
    val isComplete: Boolean get() = state == DownloadRecordState.COMPLETED
}

@OptIn(markerClass = [UnstableApi::class])
internal fun recordState(mediaState: Int): DownloadRecordState = when (mediaState) {
    Download.STATE_COMPLETED -> DownloadRecordState.COMPLETED
    Download.STATE_FAILED -> DownloadRecordState.FAILED
    Download.STATE_DOWNLOADING -> DownloadRecordState.DOWNLOADING
    // RESTARTING and STOPPED are both "will run again", which is what QUEUED
    // means to the UI; REMOVING rows are dropped before they get here.
    else -> DownloadRecordState.QUEUED
}
