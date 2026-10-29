package com.jamarr.android.playback

/**
 * Decides how browse artwork reaches the car.
 *
 * - **[Mode.URI]** — the server's own `/api/art/file/{sha1}` URL. The host
 *   process (the Android Auto app) fetches it; costs us nothing. Only safe
 *   over HTTPS: the host has its own network security config and Google's
 *   apps do not permit cleartext, so an `http://` icon URI silently fails
 *   to load there.
 * - **[Mode.CONTENT]** — a `content://` URI on [ArtworkContentProvider],
 *   which the host opens through a URI grant. The provider serves downloaded
 *   art from disk and fetches anything else from the server on demand, so a
 *   cleartext LAN server and offline Downloads both work without embedding
 *   image bytes in browse items (which was the previous answer, and cost a
 *   fetch and a full-size bitmap per row before a page could render).
 *
 * Downloaded art is always served by content URI, whatever the server
 * scheme: it must work with no network, and the host cannot read our files.
 *
 * Queue items are our own process's business (notification and now-playing
 * art) and keep file or server URIs; the policy here is browse-only.
 */
object ArtworkPolicy {

    enum class Mode { URI, CONTENT }

    /** Longest edge requested from the art endpoint, in px. */
    const val ART_SIZE_PX = 320

    fun modeFor(serverUrl: String): Mode =
        if (serverUrl.trim().startsWith("https://", ignoreCase = true)) Mode.URI else Mode.CONTENT

    /** How a browse row's single artwork should be referenced. */
    fun browseMode(serverUrl: String, downloaded: Boolean): Mode =
        if (downloaded) Mode.CONTENT else modeFor(serverUrl)
}
