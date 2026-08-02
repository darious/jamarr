package com.jamarr.android.playback

/**
 * Cache keys for media stored on disk.
 *
 * Stream URLs carry a short-lived signed token, so the resolved
 * `/api/stream/{id}?token=…` URL changes on every resolve and is useless as a
 * cache key. Keys are derived from the stable `jamarr://track/{id}` URI plus
 * the quality the bytes were fetched at, so a quality change never serves the
 * wrong file back.
 *
 * Kept free of Android types so it stays testable as a plain JVM unit test.
 */
object StreamCacheKeys {
    fun trackKey(trackId: Long, quality: String?): String =
        "track:$trackId:${StreamQualityLadder.normalize(quality)}"

    /** Extracts the track id from a `jamarr://track/{id}` URI, or null. */
    fun trackIdFromUri(uri: String): Long? {
        val prefix = "${JamarrPlaybackService.JAMARR_SCHEME}://track/"
        if (!uri.startsWith(prefix)) return null
        return uri.removePrefix(prefix).substringBefore('?').substringBefore('/').toLongOrNull()
    }
}
