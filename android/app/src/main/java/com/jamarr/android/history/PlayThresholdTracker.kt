package com.jamarr.android.history

/** A play that crossed the history threshold while the server was unreachable. */
data class OfflinePlayEvent(
    val trackId: Long,
    /** Wall-clock time the track started playing, epoch millis. */
    val startedAtMs: Long,
    val playedMs: Long,
)

/** 30s or 20% of the track, whichever is smaller — the server's rule (`play_threshold_seconds`). */
fun playThresholdMs(durationMs: Long?): Long {
    val cap = 30_000L
    if (durationMs == null || durationMs <= 0) return cap
    return minOf(cap, durationMs / 5)
}

/**
 * Decides which plays the app must record itself.
 *
 * Online, the server logs a play from progress reports at the moment it
 * crosses the threshold. So a play is recorded here exactly when the app was
 * offline at that same moment: it cannot be counted twice when the network
 * drops mid-track, and none is lost when it comes back mid-track.
 *
 * Like the server, a track counts once per run of it: playing it again
 * (repeat-one, seeking back) only counts after a different track has played.
 * Time is accumulated only while actually playing, so a long pause does not
 * count towards the threshold.
 */
class PlayThresholdTracker(private val clock: () -> Long = System::currentTimeMillis) {
    private var trackId: Long? = null
    private var startedAtMs = 0L
    private var playedMs = 0L
    private var lastTickMs: Long? = null
    private var decided = false

    /**
     * Feed the player's state on every tick. Returns a play to record, at most
     * once per play, when it crosses the threshold while [offline].
     */
    fun onTick(currentTrackId: Long?, isPlaying: Boolean, durationMs: Long?, offline: Boolean): OfflinePlayEvent? {
        val now = clock()
        if (currentTrackId != trackId) {
            trackId = currentTrackId
            startedAtMs = now
            playedMs = 0L
            decided = false
            lastTickMs = if (isPlaying) now else null
            return null
        }
        val id = trackId ?: return null
        val last = lastTickMs
        if (isPlaying && last != null) playedMs += now - last
        lastTickMs = if (isPlaying) now else null
        if (decided || playedMs < playThresholdMs(durationMs)) return null
        decided = true
        return if (offline) OfflinePlayEvent(id, startedAtMs, playedMs) else null
    }
}
