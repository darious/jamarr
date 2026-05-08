package com.jamarr.android.playback

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AdaptiveStreamQualityPolicyTest {
    @Test
    fun ladderStopsAtOpus128() {
        assertEquals("flac_24_48", StreamQualityLadder.nextLower("original"))
        assertEquals("flac_16_48", StreamQualityLadder.nextLower("flac_24_48"))
        assertEquals("mp3_320", StreamQualityLadder.nextLower("flac_16_48"))
        assertEquals("opus_128", StreamQualityLadder.nextLower("mp3_320"))
        assertEquals("opus_128", StreamQualityLadder.nextLower("opus_128"))
    }

    @Test
    fun unknownQualityNormalizesToOriginal() {
        assertEquals("original", StreamQualityLadder.normalize("bad"))
        assertEquals("flac_24_48", StreamQualityLadder.nextLower("bad"))
    }

    @Test
    fun threeBufferingEventsWithinWindowDowngrade() {
        val policy = AdaptiveStreamQualityPolicy()

        assertNull(policy.recordBufferingEvent("original", 1_000L))
        assertNull(policy.recordBufferingEvent("original", 20_000L))
        assertEquals("flac_24_48", policy.recordBufferingEvent("original", 40_000L))
    }

    @Test
    fun staleEventsDoNotTriggerDowngrade() {
        val policy = AdaptiveStreamQualityPolicy()

        assertNull(policy.recordBufferingEvent("flac_24_48", 1_000L))
        assertNull(policy.recordBufferingEvent("flac_24_48", 10_000L))
        assertNull(policy.recordBufferingEvent("flac_24_48", 69_999L))
        assertEquals(2, policy.eventCount())
    }

    @Test
    fun finalProfileDoesNotDowngrade() {
        val policy = AdaptiveStreamQualityPolicy()

        assertFalse(StreamQualityLadder.canDowngrade("opus_128"))
        assertTrue(StreamQualityLadder.canDowngrade("mp3_320"))
        assertNull(policy.recordBufferingEvent("opus_128", 1_000L))
        assertNull(policy.recordBufferingEvent("opus_128", 2_000L))
        assertNull(policy.recordBufferingEvent("opus_128", 3_000L))
    }
}
