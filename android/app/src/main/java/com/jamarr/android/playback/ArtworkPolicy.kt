package com.jamarr.android.playback

/**
 * Decides how browse artwork reaches the car.
 *
 * Two ways exist, and neither is right for every server:
 *
 * - **[Mode.URI]** — set `MediaMetadata.artworkUri`. Media3 hands it to the
 *   browser as `MediaDescriptionCompat.iconUri` and the *host* process (the
 *   Android Auto app) fetches it. Costs us nothing: no HTTP call while
 *   building the tree, and no bitmap crossing the binder. Jamarr's
 *   `/api/art/file/{sha1}` needs no auth, so an unauthenticated host fetch
 *   works.
 * - **[Mode.BYTES]** — additionally set `MediaMetadata.artworkData`. Media3
 *   decodes every blob into a `Bitmap` and attaches it to each browse item
 *   (`LegacyConversions.convertToMediaDescriptionCompat` -> `setIconBitmap`)
 *   with no downscaling, so a page of items costs one HTTP fetch and one
 *   full-size bitmap each.
 *
 * URI mode is only safe over HTTPS: the host is a separate app with its own
 * network security config, and Google's apps do not permit cleartext, so an
 * `http://` icon URI silently fails to load there. Plain-HTTP servers (the
 * usual LAN setup) therefore keep paying for bytes.
 *
 * The artwork URI is always set regardless of mode — it is just a string, and
 * it lets our own process render notification art without carrying bytes on
 * every queue item.
 */
object ArtworkPolicy {

    enum class Mode { URI, BYTES }

    /** Longest edge requested from the art endpoint, in px. */
    const val ART_SIZE_PX = 320

    fun modeFor(serverUrl: String): Mode =
        if (serverUrl.trim().startsWith("https://", ignoreCase = true)) Mode.URI else Mode.BYTES

    /**
     * Whether to embed bitmap bytes for a set of items.
     *
     * Only browse results ever need them: queue items are never rendered by
     * the browser, and fetching art to build a queue just delays playback.
     */
    fun embedsBytes(serverUrl: String, forBrowse: Boolean): Boolean =
        forBrowse && modeFor(serverUrl) == Mode.BYTES
}
