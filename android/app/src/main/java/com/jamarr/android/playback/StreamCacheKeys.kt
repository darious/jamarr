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

    /** The quality a `track:{id}:{quality}` key was stored at, or null for any other key. */
    fun qualityFromKey(key: String?): String? {
        val parts = key?.split(':') ?: return null
        if (parts.size != 3 || parts[0] != "track" || parts[1].toLongOrNull() == null) return null
        return parts[2].takeIf { it in StreamQualityLadder.qualities }
    }

    /**
     * Which quality to read a download back at: [preferred] if that is on
     * disk, else whichever other quality is, best first. Null when none is.
     *
     * A download is fetched at the download-quality setting, which need not be
     * the quality playback is asking for (or has adapted down to), so looking
     * only under the active quality would miss it and stream over the network.
     */
    fun downloadedQuality(preferred: String?, isOnDisk: (quality: String) -> Boolean): String? =
        (listOf(StreamQualityLadder.normalize(preferred)) + StreamQualityLadder.qualities)
            .distinct()
            .firstOrNull(isOnDisk)

    /** Extracts the track id from a `jamarr://track/{id}` URI, or null. */
    fun trackIdFromUri(uri: String): Long? {
        val prefix = "${JamarrPlaybackService.JAMARR_SCHEME}://track/"
        if (!uri.startsWith(prefix)) return null
        return uri.removePrefix(prefix).substringBefore('?').substringBefore('/').toLongOrNull()
    }
}
