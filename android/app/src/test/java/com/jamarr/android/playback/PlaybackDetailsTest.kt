package com.jamarr.android.playback

import androidx.media3.common.C
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PlaybackDetailsTest {
    @Test
    fun `nothing is inferred from nothing`() {
        assertTrue(PlaybackDetails().processing().isEmpty())
    }

    @Test
    fun `a hi-res source played through a 48k 16-bit track names both steps`() {
        val d = PlaybackDetails(
            originalLabel = "FLAC 24/96",
            deliveredLabel = "FLAC 24/96",
            sourceSampleRateHz = 96_000,
            sourceBitDepth = 24,
            streamSampleRateHz = 96_000,
            streamPcmEncoding = C.ENCODING_PCM_24BIT,
            sinkSampleRateHz = 48_000,
            sinkEncoding = C.ENCODING_PCM_16BIT,
            mixerSampleRateHz = 48_000,
        )
        val p = d.processing()
        assertEquals(listOf("Resampled by Android: 96 kHz → 48 kHz", "Re-quantised: 24-bit → 16-bit PCM"), p)
    }

    @Test
    fun `a server transcode is reported separately from the output path`() {
        val d = PlaybackDetails(
            originalLabel = "FLAC 24/192",
            deliveredLabel = "FLAC 16/48",
            streamSampleRateHz = 48_000,
            streamPcmEncoding = C.ENCODING_PCM_16BIT,
            sinkSampleRateHz = 48_000,
            sinkEncoding = C.ENCODING_PCM_16BIT,
        )
        assertEquals(listOf("Server transcoded: FLAC 24/192 → FLAC 16/48", "Sample rate kept at 48 kHz"), d.processing())
    }

    @Test
    fun `offload, tunneling and underruns are called out`() {
        val d = PlaybackDetails(sinkOffload = true, sinkTunneling = true, underruns = 2)
        assertEquals(listOf("Offloaded to the audio DSP", "Tunneled output", "2 output underruns this track"), d.processing())
    }

    @Test
    fun `a mixer rate that differs from the sink is flagged unless offloaded`() {
        val d = PlaybackDetails(streamSampleRateHz = 44_100, sinkSampleRateHz = 44_100, mixerSampleRateHz = 48_000)
        assertEquals(listOf("Sample rate kept at 44.1 kHz", "Mixer runs at 48 kHz; the platform may resample again"), d.processing())
        assertTrue(d.copy(sinkOffload = true).processing().none { it.startsWith("Mixer") })
    }

    @Test
    fun `encodings have names and bit depths`() {
        assertEquals(16, PlaybackDetails.pcmBits(C.ENCODING_PCM_16BIT))
        assertEquals(24, PlaybackDetails.pcmBits(C.ENCODING_PCM_24BIT))
        assertEquals(null, PlaybackDetails.pcmBits(C.ENCODING_MP3))
        assertEquals("PCM float", PlaybackDetails.encodingName(C.ENCODING_PCM_FLOAT))
        assertEquals(null, PlaybackDetails.encodingName(null))
        assertEquals("44.1 kHz", PlaybackDetails.hz(44_100))
    }
}
