package com.jamarr.android.playback

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class StreamCacheKeysTest {
    @Test
    fun `track key includes quality`() {
        assertEquals("track:12:original", StreamCacheKeys.trackKey(12, "original"))
        assertEquals("track:12:mp3_320", StreamCacheKeys.trackKey(12, "mp3_320"))
    }

    @Test
    fun `unknown quality normalises to original`() {
        assertEquals("track:12:original", StreamCacheKeys.trackKey(12, null))
        assertEquals("track:12:original", StreamCacheKeys.trackKey(12, "nonsense"))
    }

    @Test
    fun `track id parsed from jamarr uri`() {
        assertEquals(4321L, StreamCacheKeys.trackIdFromUri("jamarr://track/4321"))
    }

    @Test
    fun `signed stream urls are never keys`() {
        // The whole point of the scheme: the resolved URL rotates per token and
        // must not reach the cache key.
        assertNull(StreamCacheKeys.trackIdFromUri("https://jamarr.example/api/stream/12?token=abc"))
        assertNull(StreamCacheKeys.trackIdFromUri("jamarr://album/12"))
        assertNull(StreamCacheKeys.trackIdFromUri("jamarr://track/not-a-number"))
    }
}
