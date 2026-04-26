package com.jamarr.android.data

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
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
}
