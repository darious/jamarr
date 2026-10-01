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

    @Test
    fun `quality is read back from a track key`() {
        assertEquals("flac_16_48", StreamCacheKeys.qualityFromKey(StreamCacheKeys.trackKey(9L, "flac_16_48")))
        assertNull(StreamCacheKeys.qualityFromKey(null))
        assertNull(StreamCacheKeys.qualityFromKey("track:9:bogus"))
        assertNull(StreamCacheKeys.qualityFromKey("jamarr://track/9"))
    }

    @Test
    fun `a download is found at whatever quality it was fetched at`() {
        val onDisk = setOf("flac_16_48")

        // Playing at original, downloaded at 16/48: read the 16/48 bytes, not the network.
        assertEquals("flac_16_48", StreamCacheKeys.downloadedQuality("original") { it in onDisk })
    }

    @Test
    fun `the active quality wins when it is downloaded too`() {
        val onDisk = setOf("original", "mp3_320")

        assertEquals("mp3_320", StreamCacheKeys.downloadedQuality("mp3_320") { it in onDisk })
        // Otherwise the best quality on disk.
        assertEquals("original", StreamCacheKeys.downloadedQuality("opus_128") { it in onDisk })
    }

    @Test
    fun `nothing downloaded means no quality`() {
        assertNull(StreamCacheKeys.downloadedQuality("original") { false })
    }
}
