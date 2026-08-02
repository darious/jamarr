package com.jamarr.android.playback

/**
 * The decisions [StreamPrefetcher] makes, split out from the Media3 plumbing.
 *
 * Kept free of Android types so it stays testable as a plain JVM unit test,
 * same as [StreamCacheKeys].
 */
object PrefetchPolicy {
    /**
     * Normalises the ids the player hands us into the set worth fetching.
     *
     * A queue can contain placeholder items with no resolved track id, and the
     * same track can legitimately appear twice in one queue — fetching it twice
     * would just contend on one cache key.
     */
    fun targets(trackIds: List<Long>): List<Long> =
        trackIds.filter { it > 0L }.distinct()

    /**
     * Whether read-ahead may use the network.
     *
     * Read-ahead is the one background transfer that is hard to justify on a
     * metered connection the user did not opt into, so the wifi-only setting
     * blocks it — but only when the active network is actually metered.
     */
    fun allowsNetwork(wifiOnly: Boolean, metered: Boolean): Boolean =
        !wifiOnly || !metered
}
