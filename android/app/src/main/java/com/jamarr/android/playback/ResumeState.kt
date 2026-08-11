package com.jamarr.android.playback

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * The last queue, persisted so the car can resume it.
 *
 * When a head unit connects (or the user hits play on a Bluetooth remote) the
 * system starts the service and calls `onPlaybackResumption` **before any
 * controller has set a queue** — so unless the queue was written down, there is
 * nothing to resume and the car's resume affordance does nothing.
 *
 * Enough metadata is stored to rebuild browsable-looking items without a round
 * trip: the ids alone would resume audio but leave the now-playing screen blank
 * until the first track loaded. Artwork is kept as the resolved URI rather than
 * a sha1 so queues built by the phone — which set their own artwork URL and a
 * bare numeric media id — resume with art too.
 */
@Serializable
data class ResumeTrack(
    val mediaId: String,
    val title: String = "",
    val artist: String? = null,
    val album: String? = null,
    val artUri: String? = null,
    /** Milliseconds, or -1 when unknown. */
    val durationMs: Long = -1L,
)

@Serializable
data class ResumeQueue(
    val tracks: List<ResumeTrack> = emptyList(),
    val index: Int = 0,
    val positionMs: Long = 0L,
) {
    /** Clamps a snapshot that was written by an older build or truncated on disk. */
    fun sanitised(): ResumeQueue? {
        if (tracks.isEmpty()) return null
        val safeIndex = index.coerceIn(0, tracks.size - 1)
        val safePosition = positionMs.coerceAtLeast(0L)
        return if (safeIndex == index && safePosition == positionMs) {
            this
        } else {
            copy(index = safeIndex, positionMs = safePosition)
        }
    }

    companion object {
        private val json = Json { ignoreUnknownKeys = true }

        fun encode(queue: ResumeQueue): String = json.encodeToString(queue)

        /** Never throws: a corrupt or stale blob simply means "nothing to resume". */
        fun decode(raw: String?): ResumeQueue? {
            if (raw.isNullOrBlank()) return null
            return runCatching { json.decodeFromString<ResumeQueue>(raw) }.getOrNull()?.sanitised()
        }
    }
}
