package com.jamarr.android.playback

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class StreamingQualityPolicyTest {
    private val prefs = StreamingQualityPrefs(unmetered = "original", metered = "mp3_320")

    @Test
    fun `the cap follows metering`() {
        assertEquals("original", StreamingQualityPolicy.cap(prefs, metered = false))
        assertEquals("mp3_320", StreamingQualityPolicy.cap(prefs, metered = true))
    }

    @Test
    fun `an unknown stored value falls back to original`() {
        assertEquals("original", StreamingQualityPolicy.cap(StreamingQualityPrefs(metered = "nope"), metered = true))
    }

    @Test
    fun `ordering follows the ladder`() {
        assertTrue(StreamingQualityPolicy.isAtMost("mp3_320", "original"))
        assertTrue(StreamingQualityPolicy.isAtMost("mp3_320", "mp3_320"))
        assertFalse(StreamingQualityPolicy.isAtMost("original", "flac_16_48"))
        assertEquals("opus_128", StreamingQualityPolicy.lower("flac_24_48", "opus_128"))
    }

    @Test
    fun `a lower cap applies now, a higher one does not`() {
        // Adaptive already took playback down to FLAC 16/48; moving onto a
        // metered network capped at MP3 must drop further at once.
        assertEquals("mp3_320", StreamingQualityPolicy.applyCapNow(active = "flac_16_48", cap = "mp3_320"))
        // Back on Wi-Fi the cap is above the active quality: untouched until
        // the next queue starts.
        assertEquals("mp3_320", StreamingQualityPolicy.applyCapNow(active = "mp3_320", cap = "original"))
    }

    @Test
    fun `defaults keep today's behaviour`() {
        val d = StreamingQualityPrefs()
        assertEquals("original", StreamingQualityPolicy.cap(d, metered = true))
        assertEquals("original", StreamingQualityPolicy.cap(d, metered = false))
    }
}
