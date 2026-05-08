package com.jamarr.android.playback

object StreamQualityLadder {
    val qualities = listOf("original", "flac_24_48", "flac_16_48", "mp3_320", "opus_128")

    fun normalize(quality: String?): String =
        if (quality != null && qualities.contains(quality)) quality else "original"

    fun nextLower(quality: String?): String {
        val current = normalize(quality)
        val index = qualities.indexOf(current)
        return qualities[(index + 1).coerceAtMost(qualities.lastIndex)]
    }

    fun canDowngrade(quality: String?): Boolean =
        nextLower(quality) != normalize(quality)

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

    fun recordBufferingEvent(currentQuality: String?, nowMs: Long): String? {
        while (bufferingEvents.isNotEmpty() && nowMs - bufferingEvents.first() >= windowMs) {
            bufferingEvents.removeFirst()
        }
        bufferingEvents.addLast(nowMs)
        if (bufferingEvents.size < threshold) return null

        val next = StreamQualityLadder.nextLower(currentQuality)
        return if (next == StreamQualityLadder.normalize(currentQuality)) null else next
    }

    fun reset() {
        bufferingEvents.clear()
    }

    fun eventCount(): Int = bufferingEvents.size
}
