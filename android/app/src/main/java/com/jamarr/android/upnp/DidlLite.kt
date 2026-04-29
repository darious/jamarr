package com.jamarr.android.upnp

object DidlLite {
    fun build(track: QueuedTrack): String {
        val title = escape(track.title)
        val artist = escape(track.artist)
        val album = escape(track.album)
        val art = track.artUrl?.let {
            "<upnp:albumArtURI>${escape(it)}</upnp:albumArtURI>"
        }.orEmpty()
        return """
            <DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" xmlns:dlna="urn:schemas-dlna-org:metadata-1-0/">
                <item id="1" parentID="0" restricted="1">
                    <dc:title>$title</dc:title>
                    <dc:creator>$artist</dc:creator>
                    <upnp:artist>$artist</upnp:artist>
                    <upnp:album>$album</upnp:album>
                    <upnp:class>object.item.audioItem.musicTrack</upnp:class>
                    $art
                    <res protocolInfo="http-get:*:${track.mime}:*">${escape(track.streamUrl)}</res>
                </item>
            </DIDL-Lite>
        """.trimIndent()
    }

    private fun escape(s: String): String = s
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\"", "&quot;")
        .replace("'", "&apos;")
}
