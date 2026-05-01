package com.jamarr.android.data

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class JamarrDtosTest {
    private val json = Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
    }

    @Test
    fun searchResponseDecodesSnakeCaseBackendFields() {
        val response = json.decodeFromString<SearchResponse>(
            """
            {
              "artists": [
                {
                  "name": "Artist",
                  "mbid": "artist-mbid",
                  "image_url": "https://example.test/artist.jpg",
                  "art_sha1": "artist-art"
                }
              ],
              "albums": [
                {
                  "title": "Album",
                  "artist": "Artist",
                  "mbid": "album-mbid",
                  "art_sha1": "album-art"
                }
              ],
              "tracks": [
                {
                  "id": 7,
                  "title": "Track",
                  "artist": "Artist",
                  "album": "Album",
                  "mb_release_id": "release-mbid",
                  "duration_seconds": 200.5,
                  "art_sha1": "track-art"
                }
              ]
            }
            """.trimIndent()
        )

        assertEquals("https://example.test/artist.jpg", response.artists.single().imageUrl)
        assertEquals("album-art", response.albums.single().artSha1)
        assertEquals("release-mbid", response.tracks.single().mbReleaseId)
        assertEquals(200.5, response.tracks.single().durationSeconds ?: 0.0, 0.0)
    }

    @Test
    fun artistTrackEntryDisplayTitleFallsBackFromTitleToNameToUntitled() {
        assertEquals("Title", ArtistTrackEntry(title = "Title", name = "Name").displayTitle)
        assertEquals("Name", ArtistTrackEntry(name = "Name").displayTitle)
        assertEquals("Untitled", ArtistTrackEntry().displayTitle)
    }

    @Test
    fun rendererDecodesSnakeCaseBackendFields() {
        val renderer = json.decodeFromString<Renderer>(
            """
            {
              "udn": "uuid:1234-5678",
              "renderer_id": "upnp:uuid:1234-5678",
              "name": "Living Room Speaker",
              "type": "upnp",
              "kind": "upnp",
              "native_id": "uuid:1234-5678",
              "ip": "192.168.1.100",
              "icon_url": "https://example.test/icon.png",
              "manufacturer": "Sonos",
              "model_name": "Play:5",
              "model_number": "P5G2",
              "serial_number": "SN-001",
              "firmware_version": "2.0.1",
              "cast_type": null,
              "supports_events": true,
              "supports_gapless": false,
              "supported_mime_types": "audio/flac,audio/mpeg"
            }
            """.trimIndent()
        )

        assertEquals("uuid:1234-5678", renderer.udn)
        assertEquals("upnp:uuid:1234-5678", renderer.rendererId)
        assertEquals("upnp:uuid:1234-5678", renderer.activeKey)
        assertEquals("Living Room Speaker", renderer.name)
        assertEquals("upnp", renderer.type)
        assertEquals("upnp", renderer.kind)
        assertEquals("upnp", renderer.rendererKind)
        assertEquals("uuid:1234-5678", renderer.nativeId)
        assertEquals("192.168.1.100", renderer.ip)
        assertEquals("https://example.test/icon.png", renderer.iconUrl)
        assertEquals("Sonos", renderer.manufacturer)
        assertEquals("Play:5", renderer.modelName)
        assertEquals("P5G2", renderer.modelNumber)
        assertEquals("SN-001", renderer.serialNumber)
        assertEquals("2.0.1", renderer.firmwareVersion)
        assertEquals(true, renderer.supportsEvents)
        assertEquals(false, renderer.supportsGapless)
        assertEquals("audio/flac,audio/mpeg", renderer.supportedMimeTypes)
    }

    @Test
    fun rendererIsLocalTrueWhenUdnStartsWithLocal() {
        assertTrue(json.decodeFromString<Renderer>("""{"udn":"local:abc123"}""").isLocal)
        assertTrue(json.decodeFromString<Renderer>("""{"udn":"local:def456"}""").isLocal)
    }

    @Test
    fun rendererIsLocalFalseForUpnpUdns() {
        assertFalse(json.decodeFromString<Renderer>("""{"udn":"uuid:1234"}""").isLocal)
        assertFalse(json.decodeFromString<Renderer>("""{"udn":"some-other-id"}""").isLocal)
    }

    @Test
    fun rendererDefaultsEmptyNameWhenFriendlyNameMissing() {
        val renderer = json.decodeFromString<Renderer>("""{"udn":"uuid:1"}""")
        assertEquals("", renderer.name)
        assertEquals("upnp", renderer.type)
    }

    @Test
    fun rendererFallsBackToLegacyFriendlyName() {
        val renderer = json.decodeFromString<Renderer>("""{"udn":"uuid:1","friendly_name":"Legacy Speaker"}""")
        assertEquals("Legacy Speaker", renderer.name)
    }

    @Test
    fun playerStateResponseDecodesAllFields() {
        val state = json.decodeFromString<PlayerStateResponse>(
            """
            {
              "queue": [
                {
                  "id": 42,
                  "title": "Song Title",
                  "artist": "Artist Name",
                  "album": "Album Name",
                  "art_sha1": "art-hash",
                  "duration_seconds": 234.5,
                  "mb_release_id": "release-mbid"
                }
              ],
              "current_index": 0,
              "position_seconds": 45.2,
              "is_playing": true,
              "renderer": "Living Room",
              "renderer_id": "cast:abc",
              "renderer_kind": "cast",
              "transport_state": "PLAYING",
              "volume": 75
            }
            """.trimIndent()
        )

        assertEquals(1, state.queue.size)
        assertEquals(42, state.queue.single().id)
        assertEquals("Song Title", state.queue.single().title)
        assertEquals("Artist Name", state.queue.single().artist)
        assertEquals("Album Name", state.queue.single().album)
        assertEquals("art-hash", state.queue.single().artSha1)
        assertEquals(234.5, state.queue.single().durationSeconds)
        assertEquals("release-mbid", state.queue.single().mbReleaseId)
        assertEquals(0, state.currentIndex)
        assertEquals(45.2, state.positionSeconds, 0.0)
        assertEquals(true, state.isPlaying)
        assertEquals("Living Room", state.renderer)
        assertEquals("cast:abc", state.rendererId)
        assertEquals("cast", state.rendererKind)
        assertEquals("PLAYING", state.transportState)
        assertEquals(75, state.volume)
    }

    @Test
    fun playerStateResponseDefaultsEmptyQueueAndNegativeIndex() {
        val state = json.decodeFromString<PlayerStateResponse>("{}")

        assertEquals(emptyList<PlayerStateTrack>(), state.queue)
        assertEquals(-1, state.currentIndex)
        assertEquals(0.0, state.positionSeconds, 0.0)
        assertEquals(false, state.isPlaying)
        assertEquals("", state.renderer)
        assertEquals(null, state.transportState)
        assertEquals(null, state.volume)
    }

    @Test
    fun playerStateTrackNullableFieldsDefaultToNull() {
        val track = json.decodeFromString<PlayerStateTrack>("""{"id":1,"title":"T"}""")

        assertEquals(1, track.id)
        assertEquals("T", track.title)
        assertEquals(null, track.artist)
        assertEquals(null, track.album)
        assertEquals(null, track.artSha1)
        assertEquals(null, track.durationSeconds)
        assertEquals(null, track.mbReleaseId)
    }
}
