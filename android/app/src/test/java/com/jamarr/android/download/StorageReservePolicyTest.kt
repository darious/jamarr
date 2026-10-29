package com.jamarr.android.download

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class StorageReservePolicyTest {
    private val gb = 1024L * 1024 * 1024

    @Test
    fun `reserve is at least 500 MB and otherwise 5 percent`() {
        assertEquals(500L * 1024 * 1024, StorageReservePolicy.reserveBytes(4 * gb))
        assertEquals((128 * gb * 0.05).toLong(), StorageReservePolicy.reserveBytes(128 * gb))
    }

    @Test
    fun `holds under the reserve and releases only above reserve plus margin`() {
        val total = 64 * gb
        val reserve = StorageReservePolicy.reserveBytes(total)
        val margin = StorageReservePolicy.resumeMarginBytes()
        assertFalse(StorageReservePolicy.shouldHold(reserve + 1, total, currentlyHeld = false))
        assertTrue(StorageReservePolicy.shouldHold(reserve - 1, total, currentlyHeld = false))
        // Hysteresis: just above the reserve is still held once holding.
        assertTrue(StorageReservePolicy.shouldHold(reserve + margin - 1, total, currentlyHeld = true))
        assertFalse(StorageReservePolicy.shouldHold(reserve + margin, total, currentlyHeld = true))
    }
}
