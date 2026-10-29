package com.jamarr.android.playback

import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.util.UnstableApi

/**
 * What the local pipeline is doing with the current track, in three layers
 * that the quality badge alone conflates:
 *
 * 1. **Source** — what the server has and what it delivered (original vs
 *    transcoded vs a download), as reported by the server.
 * 2. **Decoder** — the stream format ExoPlayer parsed and the codec it chose.
 * 3. **Output** — how the `AudioTrack` was configured and where the platform
 *    routes it. The platform may resample or re-quantise between 2 and 3; the
 *    [processing] list names what can be inferred from the numbers, nothing
 *    more. Anything the platform does not report stays null and the UI says so.
 */
@OptIn(markerClass = [UnstableApi::class])
data class PlaybackDetails(
    val trackId: Long? = null,
    /** `download`, `read-ahead` or `network`. */
    val source: String? = null,
    /** Server labels: the file in the library, and what was sent/downloaded. */
    val originalLabel: String? = null,
    val deliveredLabel: String? = null,
    val deliveredQuality: String? = null,
    /** Original file characteristics, as the server reports them. */
    val sourceSampleRateHz: Int? = null,
    val sourceBitDepth: Int? = null,
    /** The parsed stream, from ExoPlayer's audio input `Format`. */
    val streamMimeType: String? = null,
    val streamCodecs: String? = null,
    val streamSampleRateHz: Int? = null,
    val streamChannels: Int? = null,
    val streamPcmEncoding: Int? = null,
    val streamBitrate: Int? = null,
    val decoderName: String? = null,
    /** `AudioTrack` configuration, from `onAudioTrackInitialized`. */
    val sinkEncoding: Int? = null,
    val sinkSampleRateHz: Int? = null,
    val sinkChannelCount: Int? = null,
    val sinkOffload: Boolean? = null,
    val sinkTunneling: Boolean? = null,
    val sinkBufferBytes: Int? = null,
    /** The platform mixer rate (`PROPERTY_OUTPUT_SAMPLE_RATE`); null when unknown. */
    val mixerSampleRateHz: Int? = null,
    val route: String? = null,
    /** False when [route] is a ranking heuristic rather than the platform's answer (API < 33). */
    val routeExact: Boolean = false,
    val underruns: Int = 0,
    val updatedAtMs: Long = 0L,
) {
    /** Human-readable inferences about what happens between stream and output. */
    fun processing(): List<String> {
        val out = mutableListOf<String>()
        if (originalLabel != null && deliveredLabel != null && originalLabel != deliveredLabel) {
            out += "Server transcoded: $originalLabel → $deliveredLabel"
        }
        val sr = streamSampleRateHz
        val sink = sinkSampleRateHz
        if (sr != null && sink != null && sr != sink) {
            out += "Resampled by Android: ${hz(sr)} → ${hz(sink)}"
        } else if (sr != null && sink != null) {
            out += "Sample rate kept at ${hz(sink)}"
        }
        val streamBits = pcmBits(streamPcmEncoding)
        val sinkBits = pcmBits(sinkEncoding)
        if (streamBits != null && sinkBits != null && streamBits != sinkBits) {
            out += "Re-quantised: $streamBits-bit → $sinkBits-bit PCM"
        } else if (sourceBitDepth != null && sinkBits != null && sourceBitDepth > sinkBits) {
            out += "Output depth $sinkBits-bit is below the $sourceBitDepth-bit source"
        }
        if (sinkOffload == true) out += "Offloaded to the audio DSP"
        if (sinkTunneling == true) out += "Tunneled output"
        val mixer = mixerSampleRateHz
        if (mixer != null && sink != null && mixer != sink && sinkOffload != true) {
            out += "Mixer runs at ${hz(mixer)}; the platform may resample again"
        }
        if (underruns > 0) out += "$underruns output underrun${if (underruns == 1) "" else "s"} this track"
        return out
    }

    companion object {
        fun hz(rate: Int): String =
            if (rate % 1000 == 0) "${rate / 1000} kHz" else "%.1f kHz".format(rate / 1000.0)

        /** Bits per sample for a PCM `C.ENCODING_*`, null for compressed or unknown. */
        fun pcmBits(encoding: Int?): Int? = when (encoding) {
            C.ENCODING_PCM_8BIT -> 8
            C.ENCODING_PCM_16BIT, C.ENCODING_PCM_16BIT_BIG_ENDIAN -> 16
            C.ENCODING_PCM_24BIT, C.ENCODING_PCM_24BIT_BIG_ENDIAN -> 24
            C.ENCODING_PCM_32BIT, C.ENCODING_PCM_32BIT_BIG_ENDIAN -> 32
            C.ENCODING_PCM_FLOAT -> 32
            else -> null
        }

        fun encodingName(encoding: Int?): String? = when (encoding) {
            null, C.ENCODING_INVALID -> null
            C.ENCODING_PCM_8BIT -> "PCM 8-bit"
            C.ENCODING_PCM_16BIT -> "PCM 16-bit"
            C.ENCODING_PCM_16BIT_BIG_ENDIAN -> "PCM 16-bit BE"
            C.ENCODING_PCM_24BIT -> "PCM 24-bit"
            C.ENCODING_PCM_24BIT_BIG_ENDIAN -> "PCM 24-bit BE"
            C.ENCODING_PCM_32BIT -> "PCM 32-bit"
            C.ENCODING_PCM_32BIT_BIG_ENDIAN -> "PCM 32-bit BE"
            C.ENCODING_PCM_FLOAT -> "PCM float"
            C.ENCODING_MP3 -> "MP3 (passthrough)"
            C.ENCODING_AAC_LC, C.ENCODING_AAC_HE_V1, C.ENCODING_AAC_HE_V2, C.ENCODING_AAC_XHE, C.ENCODING_AAC_ELD -> "AAC (passthrough)"
            C.ENCODING_OPUS -> "Opus (offload)"
            else -> "Encoding $encoding"
        }
    }
}
