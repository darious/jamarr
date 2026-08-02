package com.jamarr.android.playback

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PrefetchPolicyTest {
    @Test
    fun `unresolved track ids are dropped`() {
        // The player reports 0 for a queue item whose id has not resolved yet;
        // prefetching it would build a "track:0:…" cache entry.
        assertEquals(listOf(7L), PrefetchPolicy.targets(listOf(0L, 7L, -1L)))
        assertEquals(emptyList<Long>(), PrefetchPolicy.targets(listOf(0L, -3L)))
    }

    @Test
    fun `a repeated track is fetched once`() {
        // Two writers on one cache key contend; the loser refetches uncached.
        assertEquals(listOf(4L, 9L), PrefetchPolicy.targets(listOf(4L, 9L, 4L)))
    }

    @Test
    fun `order is preserved so the next track is fetched first`() {
        assertEquals(listOf(3L, 1L, 2L), PrefetchPolicy.targets(listOf(3L, 1L, 2L)))
    }

    @Test
    fun `wifi-only blocks read-ahead only on a metered network`() {
        assertFalse(PrefetchPolicy.allowsNetwork(wifiOnly = true, metered = true))
        assertTrue(PrefetchPolicy.allowsNetwork(wifiOnly = true, metered = false))
    }

    @Test
    fun `read-ahead is unrestricted when wifi-only is off`() {
        // Default setting: read-ahead pulls the track about to play anyway, so
        // it costs no more data than simply playing on.
        assertTrue(PrefetchPolicy.allowsNetwork(wifiOnly = false, metered = true))
        assertTrue(PrefetchPolicy.allowsNetwork(wifiOnly = false, metered = false))
    }
}
