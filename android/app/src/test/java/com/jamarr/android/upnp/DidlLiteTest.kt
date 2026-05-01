package com.jamarr.android.upnp

import com.jamarr.android.renderer.QueuedTrack
import org.junit.Assert.assertTrue
import org.junit.Test

class DidlLiteTest {

    @Test
    fun producesValidDidlLiteXmlStructure() {
        val track = QueuedTrack(
            id = 42,
            title = "Test Track",
            artist = "Test Artist",
            album = "Test Album",
            mime = "audio/flac",
            durationSeconds = 200.5,
            streamUrl = "https://jamarr.example/stream/42",
            artUrl = "https://jamarr.example/art/abc",
        )

        val xml = DidlLite.build(track)

        assertTrue("root DIDL-Lite element", xml.contains("<DIDL-Lite"))
        assertTrue("dc namespace", xml.contains("xmlns:dc=\"http://purl.org/dc/elements/1.1/\""))
        assertTrue("upnp namespace", xml.contains("xmlns:upnp=\"urn:schemas-upnp-org:metadata-1-0/upnp/\""))
        assertTrue("item element", xml.contains("<item "))
        assertTrue("dc:title", xml.contains("<dc:title>Test Track</dc:title>"))
        assertTrue("dc:creator", xml.contains("<dc:creator>Test Artist</dc:creator>"))
        assertTrue("upnp:artist", xml.contains("<upnp:artist>Test Artist</upnp:artist>"))
        assertTrue("upnp:album", xml.contains("<upnp:album>Test Album</upnp:album>"))
        assertTrue("upnp:class", xml.contains("object.item.audioItem.musicTrack"))
        assertTrue("res element", xml.contains("<res "))
        assertTrue("stream URL in res", xml.contains("https://jamarr.example/stream/42"))
        assertTrue("mime in protocolInfo", xml.contains("audio/flac"))
        assertTrue("albumArtURI", xml.contains("<upnp:albumArtURI>https://jamarr.example/art/abc</upnp:albumArtURI>"))
    }

    @Test
    fun omitsAlbumArtUriWhenArtUrlIsNull() {
        val track = QueuedTrack(
            id = 1,
            title = "No Art",
            artist = "Artist",
            album = "Album",
            mime = "audio/mpeg",
            durationSeconds = 100.0,
            streamUrl = "https://example.test/stream",
            artUrl = null,
        )

        val xml = DidlLite.build(track)

        assertTrue("no albumArtURI when artUrl null", !xml.contains("albumArtURI"))
    }

    @Test
    fun includesAlbumArtUriForBlankArtUrl() {
        val track = QueuedTrack(
            id = 1,
            title = "No Art",
            artist = "Artist",
            album = "Album",
            mime = "audio/mpeg",
            durationSeconds = 100.0,
            streamUrl = "https://example.test/stream",
            artUrl = "   ",
        )

        val xml = DidlLite.build(track)

        assertTrue("albumArtURI present even for blank artUrl", xml.contains("albumArtURI"))
    }

    @Test
    fun escapesAmpersandInTextFields() {
        val track = QueuedTrack(
            id = 1,
            title = "Rock & Roll",
            artist = "Tom & Jerry",
            album = "Greatest & Hits",
            mime = "audio/mpeg",
            durationSeconds = 100.0,
            streamUrl = "https://example.test/stream",
            artUrl = null,
        )

        val xml = DidlLite.build(track)

        assertTrue("ampersand in title escaped", xml.contains("<dc:title>Rock &amp; Roll</dc:title>"))
        assertTrue("ampersand in artist escaped", xml.contains("<dc:creator>Tom &amp; Jerry</dc:creator>"))
        assertTrue("ampersand in album escaped", xml.contains("<upnp:album>Greatest &amp; Hits</upnp:album>"))
    }

    @Test
    fun escapesXmlSpecialCharacters() {
        val track = QueuedTrack(
            id = 1,
            title = "A < B > C",
            artist = "Artist \"Name\"",
            album = "Album 'X'",
            mime = "audio/mpeg",
            durationSeconds = 100.0,
            streamUrl = "https://example.test/stream?a=1&b=2",
            artUrl = null,
        )

        val xml = DidlLite.build(track)

        assertTrue("lt escaped", xml.contains("<dc:title>A &lt; B &gt; C</dc:title>"))
        assertTrue("quot escaped", xml.contains("<dc:creator>Artist &quot;Name&quot;</dc:creator>"))
        assertTrue("apos escaped", xml.contains("<upnp:album>Album &apos;X&apos;</upnp:album>"))
        assertTrue("ampersand in stream URL escaped", xml.contains("a=1&amp;b=2"))
    }

    @Test
    fun emptyFieldsProduceEmptyElements() {
        val track = QueuedTrack(
            id = 1,
            title = "",
            artist = "",
            album = "",
            mime = "",
            durationSeconds = 0.0,
            streamUrl = "https://example.test/stream",
            artUrl = null,
        )

        val xml = DidlLite.build(track)

        assertTrue("empty title", xml.contains("<dc:title></dc:title>"))
        assertTrue("empty creator", xml.contains("<dc:creator></dc:creator>"))
        assertTrue("empty artist", xml.contains("<upnp:artist></upnp:artist>"))
        assertTrue("empty album", xml.contains("<upnp:album></upnp:album>"))
    }
}
