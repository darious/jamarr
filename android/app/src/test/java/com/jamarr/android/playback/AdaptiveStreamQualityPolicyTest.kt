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

    @Test
    fun cdQualitySourceSkipsLosslessRungsThatWouldNotShrinkIt() {
        // FLAC 24/48 resamples 44.1k up and pads 16-bit to 24, landing larger
        // than the source: stepping onto it to relieve a stall makes it worse.
        val cdQuality = StreamSource(sampleRateHz = 44_100, bitDepth = 16)

        assertFalse(StreamQualityLadder.reducesSource("flac_24_48", cdQuality))
        assertFalse(StreamQualityLadder.reducesSource("flac_16_48", cdQuality))
        assertTrue(StreamQualityLadder.reducesSource("mp3_320", cdQuality))
        assertEquals("mp3_320", StreamQualityLadder.nextLower("original", cdQuality))
    }

    @Test
    fun hiResSourceKeepsLosslessRungs() {
        val hiRes = StreamSource(sampleRateHz = 96_000, bitDepth = 24)

        assertEquals("flac_24_48", StreamQualityLadder.nextLower("original", hiRes))
        assertEquals("flac_16_48", StreamQualityLadder.nextLower("flac_24_48", hiRes))
    }

    @Test
    fun ladderIsUnchangedWhenSourceIsUnknown() {
        assertEquals("flac_24_48", StreamQualityLadder.nextLower("original"))
        assertEquals("flac_24_48", StreamQualityLadder.nextLower("original", StreamSource()))
    }

    @Test
    fun bufferingOnCdQualityDowngradesStraightToMp3() {
        val policy = AdaptiveStreamQualityPolicy()
        val cdQuality = StreamSource(sampleRateHz = 44_100, bitDepth = 16)

        assertNull(policy.recordBufferingEvent("original", 1_000L, cdQuality))
        assertNull(policy.recordBufferingEvent("original", 2_000L, cdQuality))
        assertEquals("mp3_320", policy.recordBufferingEvent("original", 3_000L, cdQuality))
    }
}
