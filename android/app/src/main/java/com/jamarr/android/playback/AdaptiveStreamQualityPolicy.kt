package com.jamarr.android.playback

/** Source characteristics of the playing track, as reported by the server. */
data class StreamSource(val sampleRateHz: Int? = null, val bitDepth: Int? = null)

object StreamQualityLadder {
    val qualities = listOf("original", "flac_24_48", "flac_16_48", "mp3_320", "opus_128")

    /** Output characteristics of the lossless rungs; mirrors the backend. */
    private val losslessRungs = mapOf(
        "flac_24_48" to Pair(48_000, 24),
        "flac_16_48" to Pair(48_000, 16),
    )

    fun normalize(quality: String?): String =
        if (quality != null && qualities.contains(quality)) quality else "original"

    /**
     * Whether transcoding to [quality] would actually shrink [source].
     *
     * Lossy rungs always do. A lossless rung only does if it lowers the raw
     * data rate: FLAC 24/48 off a 16/44.1 source is an upsample, ~69% larger,
     * so stepping onto it to relieve a stall makes the stall worse.
     */
    fun reducesSource(quality: String?, source: StreamSource?): Boolean {
        val rung = losslessRungs[normalize(quality)] ?: return true
        val rate = source?.sampleRateHz ?: return true
        val depth = source.bitDepth ?: return true
        if (rate <= 0 || depth <= 0) return true
        return rung.first * rung.second < rate * depth
    }

    /**
     * Next rung down, skipping any that would not shrink [source]. Called
     * without a source it walks the ladder verbatim, which is the right
     * behaviour when the characteristics are unknown.
     */
    fun nextLower(quality: String?, source: StreamSource? = null): String {
        val current = normalize(quality)
        val index = qualities.indexOf(current)
        for (candidate in qualities.drop(index + 1)) {
            if (reducesSource(candidate, source)) return candidate
        }
        return current
    }

    fun canDowngrade(quality: String?, source: StreamSource? = null): Boolean =
        nextLower(quality, source) != normalize(quality)

    fun label(quality: String?): String = when (normalize(quality)) {
        "flac_24_48" -> "FLAC 24/48"
        "flac_16_48" -> "FLAC 16/48"
        "mp3_320" -> "MP3 320"
        "opus_128" -> "Opus 128"
        else -> "Original"
    }
}

class AdaptiveStreamQualityPolicy(
    private val windowMs: Long = 60_000L,
    private val threshold: Int = 3,
) {
    private val bufferingEvents = ArrayDeque<Long>()

    fun recordBufferingEvent(
        currentQuality: String?,
        nowMs: Long,
        source: StreamSource? = null,
    ): String? {
        while (bufferingEvents.isNotEmpty() && nowMs - bufferingEvents.first() >= windowMs) {
            bufferingEvents.removeFirst()
        }
        bufferingEvents.addLast(nowMs)
        if (bufferingEvents.size < threshold) return null

        val next = StreamQualityLadder.nextLower(currentQuality, source)
        return if (next == StreamQualityLadder.normalize(currentQuality)) null else next
    }

    fun reset() {
        bufferingEvents.clear()
    }

    fun eventCount(): Int = bufferingEvents.size
}
