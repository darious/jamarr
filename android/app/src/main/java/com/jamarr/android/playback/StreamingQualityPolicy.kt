package com.jamarr.android.playback

/** The user's streaming ceilings, one per network class. */
data class StreamingQualityPrefs(
    val unmetered: String = DEFAULT,
    val metered: String = DEFAULT,
) {
    companion object {
        const val DEFAULT = "original"
    }
}

/**
 * Which quality a stream may start at on the current network.
 *
 * Metering comes from `ConnectivityManager.isActiveNetworkMetered`, so a
 * metered Wi-Fi hotspot counts as metered. The cap is a ceiling: adaptive
 * downgrade ([AdaptiveStreamQualityPolicy]) still steps below it on repeated
 * buffering, and a download plays at whatever quality it was fetched at.
 *
 * When the cap applies (the transition boundary):
 * - a **new queue** starts at the cap for the network at that moment;
 * - a **lower** cap (network change or setting change) applies at once — the
 *   current track reloads at its position, unless it is already on the
 *   device, in which case only the following tracks change;
 * - a **higher** cap applies from the next queue, so read-ahead already on
 *   disk at the lower quality is not thrown away mid-album.
 */
object StreamingQualityPolicy {
    fun cap(prefs: StreamingQualityPrefs, metered: Boolean): String =
        StreamQualityLadder.normalize(if (metered) prefs.metered else prefs.unmetered)

    /** True when [a] is a lower rung than [b] (or equal). */
    fun isAtMost(a: String?, b: String?): Boolean =
        StreamQualityLadder.qualities.indexOf(StreamQualityLadder.normalize(a)) >=
            StreamQualityLadder.qualities.indexOf(StreamQualityLadder.normalize(b))

    /** The lower of two rungs. */
    fun lower(a: String?, b: String?): String =
        if (isAtMost(a, b)) StreamQualityLadder.normalize(a) else StreamQualityLadder.normalize(b)

    /**
     * What the active quality becomes when the cap changes mid-play: the
     * active value when the cap is at or above it, the cap when it is lower.
     * Equal to [active] means nothing to do now.
     */
    fun applyCapNow(active: String, cap: String): String = lower(active, cap)
}
