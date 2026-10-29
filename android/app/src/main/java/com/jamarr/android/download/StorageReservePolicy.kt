package com.jamarr.android.download

/**
 * How much free space downloads must leave on the device.
 *
 * Policy: keep **the larger of 500 MB and 5 % of the volume** free. Android's
 * own "storage low" signal fires at the *smaller* of those two (its
 * `sys_storage_threshold_percentage` = 5 % capped at 500 MB), at which point
 * the system starts refusing writes and clearing caches. Holding downloads at
 * a reserve that is always at least as large means Jamarr stops filling the
 * disk before the OS has to intervene, and leaves room for the app's own
 * database, read-ahead and artwork writes.
 *
 * Resuming needs [resumeMarginBytes] more than the reserve so a device
 * hovering at the line does not flip between held and running every poll.
 *
 * Nothing here ever deletes a download to make room: a hold only pauses the
 * queue, which Media3 keeps resumable.
 */
object StorageReservePolicy {
    const val MIN_RESERVE_BYTES: Long = 500L * 1024 * 1024
    const val RESERVE_FRACTION: Double = 0.05
    const val RESUME_MARGIN_BYTES: Long = 100L * 1024 * 1024

    fun reserveBytes(totalBytes: Long): Long =
        maxOf(MIN_RESERVE_BYTES, (totalBytes * RESERVE_FRACTION).toLong())

    fun resumeMarginBytes(): Long = RESUME_MARGIN_BYTES

    /**
     * Whether downloads should be held given the current free space.
     *
     * A hold starts once free space is under the reserve and ends once it is
     * back above the reserve plus the margin.
     */
    fun shouldHold(freeBytes: Long, totalBytes: Long, currentlyHeld: Boolean): Boolean {
        val reserve = reserveBytes(totalBytes)
        return if (currentlyHeld) freeBytes < reserve + RESUME_MARGIN_BYTES else freeBytes < reserve
    }
}

/** Why the download queue is not moving although nothing has failed. */
sealed interface DownloadHold {
    /** Free space is under the reserve; the queue is paused, not failed. */
    data class LowStorage(val freeBytes: Long, val reserveBytes: Long) : DownloadHold

    /** Media3's requirements (unmetered network, storage not low) are not met. */
    data class WaitingForNetwork(val wifiOnly: Boolean) : DownloadHold

    data object WaitingForSystemStorage : DownloadHold
}
