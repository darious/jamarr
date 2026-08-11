package com.jamarr.android.playback

import androidx.media3.common.MediaItem
import androidx.media3.session.LibraryResult
import androidx.media3.session.SessionError
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.jamarr.android.auth.TokenHolder
import com.jamarr.android.data.JamarrApiClient
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.test.runTest
import mockwebserver3.Dispatcher
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
import okio.Buffer
import okio.ByteString.Companion.decodeBase64
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The Android Auto browse tree, driven the way the car drives it.
 *
 * Runs against a fake Jamarr server so every node, page window and failure mode
 * is reproducible. The provider is built fresh per test — it caches — and needs
 * a device only for the Android types it builds (`MediaItem`, `Uri`, `Bitmap`).
 */
@RunWith(AndroidJUnit4::class)
class JamarrLibraryProviderInstrumentedTest {

    private lateinit var server: MockWebServer
    private lateinit var scope: CoroutineScope

    /** Path -> body, so tests can rewrite one endpoint without restating the rest. */
    private val routes = ConcurrentHashMap<String, String>()

    /** Path -> HTTP status, for the failure cases. */
    private val failures = ConcurrentHashMap<String, Int>()

    private val hits = ConcurrentHashMap<String, AtomicInteger>()

    @Before
    fun setUp() {
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val path = request.url.encodedPath
                hits.getOrPut(path) { AtomicInteger() }.incrementAndGet()
                failures[path]?.let { code ->
                    return MockResponse.Builder().code(code).body("""{"detail":"nope"}""").build()
                }
                if (path.startsWith("/api/art/file/")) {
                    return MockResponse.Builder()
                        .code(200)
                        .addHeader("Content-Type", "image/jpeg")
                        .body(Buffer().write(ONE_PIXEL_JPEG))
                        .build()
                }
                val body = routes[path] ?: "[]"
                return MockResponse.Builder()
                    .code(200)
                    .addHeader("Content-Type", "application/json")
                    .body(body)
                    .build()
            }
        }
        server.start()
        scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        seedDefaultRoutes()
    }

    @After
    fun tearDown() {
        scope.cancel()
        server.close()
    }

    private fun seedDefaultRoutes() {
        routes["/api/favorites/artists"] = """
            [
              {"mbid":"artist-1","name":"Massive Attack","art_sha1":"$SHA_A"},
              {"mbid":"artist-2","name":"Portishead","art_sha1":"$SHA_B"}
            ]
        """.trimIndent()
        routes["/api/favorites/releases"] = """
            [{"album_mbid":"album-1","title":"Mezzanine","artist_name":"Massive Attack",
              "year":"1998","art_sha1":"$SHA_A"}]
        """.trimIndent()
        routes["/api/playlists"] = """
            [{"id":7,"name":"Night drive","track_count":3,"thumbnails":["$SHA_A","$SHA_B"]}]
        """.trimIndent()
        routes["/api/playlists/7"] = """
            {"id":7,"name":"Night drive","track_count":2,"tracks":[
              {"playlist_track_id":1,"position":1,"track_id":101,"title":"Angel",
               "artist":"Massive Attack","album":"Mezzanine","duration_seconds":379.0,"art_sha1":"$SHA_A"},
              {"playlist_track_id":2,"position":2,"track_id":102,"title":"Teardrop",
               "artist":"Massive Attack","album":"Mezzanine","duration_seconds":330.0,"art_sha1":"$SHA_A"}
            ]}
        """.trimIndent()
        routes["/api/tracks"] = """
            [
              {"id":101,"title":"Angel","artist":"Massive Attack","album":"Mezzanine",
               "duration_seconds":379.0,"art_sha1":"$SHA_A"},
              {"id":102,"title":"Risingson","artist":"Massive Attack","album":"Mezzanine",
               "duration_seconds":298.0,"art_sha1":"$SHA_A"},
              {"id":103,"title":"Teardrop","artist":"Massive Attack","album":"Mezzanine",
               "duration_seconds":330.0,"art_sha1":"$SHA_A"},
              {"id":104,"title":"Inertia Creeps","artist":"Massive Attack","album":"Mezzanine",
               "duration_seconds":355.0,"art_sha1":"$SHA_A"}
            ]
        """.trimIndent()
        routes["/api/history/artists"] = """
            [
              {"artist_name":"Portishead","artist_mbid":"artist-2","art_sha1":"$SHA_B","plays":9},
              {"artist_name":"Unmatched Artist","plays":3}
            ]
        """.trimIndent()
        routes["/api/history/albums"] = """
            [
              {"album":"Dummy","artist":"Portishead","mb_release_id":"album-2","art_sha1":"$SHA_B"},
              {"album":"Unmatched Album","artist":"Nobody"}
            ]
        """.trimIndent()
        routes["/api/history/stats"] = """
            {"artists":[
               {"artist_name":"Portishead","artist_mbid":"artist-2","art_sha1":"$SHA_B","plays":9},
               {"artist_name":"Unmatched Artist","plays":3}],
             "albums":[
               {"album":"Dummy","artist":"Portishead","mb_release_id":"album-2","art_sha1":"$SHA_B"},
               {"album":"Unmatched Album","artist":"Nobody"}],
             "tracks":[]}
        """.trimIndent()
        routes["/api/history/tracks"] = """
            [{"track_id":101,"title":"Angel","artist":"Massive Attack","album":"Mezzanine",
              "duration_seconds":379.0,"art_sha1":"$SHA_A","played_at":"2026-01-01T00:00:00Z"}]
        """.trimIndent()
        routes["/api/charts"] = """
            [{"position":1,"title":"Mezzanine","artist":"Massive Attack","in_library":true,
              "local_album_mbid":"album-1","art_sha1":"$SHA_A"},
             {"position":2,"title":"Not Here","artist":"Nobody","in_library":false}]
        """.trimIndent()
        routes["/api/home/new-releases"] = "[]"
        routes["/api/home/recently-added-albums"] = """
            [{"album":"Mezzanine","artist_name":"Massive Attack","album_mbid":"album-1",
              "year":"1998","art_sha1":"$SHA_A"}]
        """.trimIndent()
        routes["/api/home/discover-artists"] = "[]"
        routes["/api/artists"] = """
            [{"mbid":"artist-1","name":"Massive Attack","art_sha1":"$SHA_A",
              "top_tracks":[{"title":"Angel","local_track_id":101,"duration_seconds":379.0,"art_sha1":"$SHA_A"}],
              "singles":[{"title":"Teardrop","local_track_id":103,"date":"1998-04-27","art_sha1":"$SHA_A"}]}]
        """.trimIndent()
    }

    private fun provider(token: String = "test-token"): JamarrLibraryProvider {
        val url = server.url("/").toString().trimEnd('/')
        return JamarrLibraryProvider(
            apiClient = JamarrApiClient(TokenHolder(token)),
            credentials = { JamarrLibraryProvider.Credentials(url, token) },
            scope = scope,
        )
    }

    private fun LibraryResult<com.google.common.collect.ImmutableList<MediaItem>>.items(): List<MediaItem> =
        checkNotNull(value) { "expected items, got error ${this.resultCode}" }

    private fun titles(items: List<MediaItem>) = items.map { it.mediaMetadata.title?.toString() }

    private fun hitsFor(path: String) = hits[path]?.get() ?: 0

    // ----- tree shape ---------------------------------------------------

    @Test
    fun rootListsTheSixTopLevelFolders() = runTest {
        val items = provider().childrenResult(BrowseTree.ID_ROOT, 0, Int.MAX_VALUE).items()

        assertEquals(
            listOf("Favourites", "Playlists", "Recently Played", "Charts", "History", "Recently Added"),
            titles(items),
        )
        assertTrue(items.all { it.mediaMetadata.isBrowsable == true })
    }

    @Test
    fun aDeepNodeResolvesOnItsOwn() = runTest {
        // Restoring a browse stack asks for the node directly; only root's
        // children used to resolve, so deeper screens failed to restore.
        val result = provider().itemResult(BrowseTree.ID_FAV_ARTISTS)

        assertEquals(LibraryResult.RESULT_SUCCESS, result.resultCode)
        assertEquals("Artists", result.value?.mediaMetadata?.title?.toString())
    }

    @Test
    fun anUnknownMediaIdIsABadValue() = runTest {
        assertEquals(
            SessionError.ERROR_BAD_VALUE,
            provider().itemResult("node:not-a-thing").resultCode,
        )
    }

    // ----- auth ----------------------------------------------------------

    @Test
    fun signedOutShowsTheSignInPrompt() = runTest {
        val items = provider(token = "").childrenResult(BrowseTree.ID_ROOT, 0, Int.MAX_VALUE).items()

        assertEquals(1, items.size)
        assertEquals(JamarrLibraryProvider.ID_SIGN_IN, items.single().mediaId)
        assertEquals(0, hitsFor("/api/favorites/artists"))
    }

    @Test
    fun anExpiredSessionIsReportedAsAuthenticationExpired() = runTest {
        failures["/api/favorites/artists"] = 401

        val result = provider().childrenResult(BrowseTree.ID_FAV_ARTISTS, 0, Int.MAX_VALUE)

        assertEquals(SessionError.ERROR_SESSION_AUTHENTICATION_EXPIRED, result.resultCode)
    }

    // ----- failures ------------------------------------------------------

    @Test
    fun aFailingNodeIsAnErrorNotAnEmptyFolder() = runTest {
        // Swallowing this used to render a dead server as an empty library,
        // with no way for the car to offer a retry.
        failures["/api/playlists"] = 500

        val result = provider().childrenResult(BrowseTree.ID_PLAYLISTS, 0, Int.MAX_VALUE)

        assertEquals(SessionError.ERROR_IO, result.resultCode)
        assertNull(result.value)
    }

    @Test
    fun aGenuinelyEmptyFolderIsStillEmpty() = runTest {
        routes["/api/playlists"] = "[]"

        val result = provider().childrenResult(BrowseTree.ID_PLAYLISTS, 0, Int.MAX_VALUE)

        assertEquals(LibraryResult.RESULT_SUCCESS, result.resultCode)
        assertEquals(emptyList<MediaItem>(), result.items())
    }

    // ----- paging --------------------------------------------------------

    @Test
    fun pagesAreDistinctWindowsOfTheSameFolder() = runTest {
        val p = provider()
        // Album folders lead with "Play all", so the four tracks span pages 0-2.
        val first = p.childrenResult(BrowseTree.albumId("album-1"), 0, 2).items()
        val second = p.childrenResult(BrowseTree.albumId("album-1"), 1, 2).items()
        val third = p.childrenResult(BrowseTree.albumId("album-1"), 2, 2).items()

        assertEquals(listOf(JamarrLibraryProvider.PLAY_ALL_TITLE, "Angel"), titles(first))
        assertEquals(listOf("Risingson", "Teardrop"), titles(second))
        assertEquals(listOf("Inertia Creeps"), titles(third))
    }

    @Test
    fun aPagePastTheEndIsEmpty() = runTest {
        val items = provider().childrenResult(BrowseTree.albumId("album-1"), 9, 2).items()

        assertEquals(emptyList<MediaItem>(), items)
    }

    // ----- play all ------------------------------------------------------

    @Test
    fun anAlbumFolderLeadsWithPlayAll() = runTest {
        val items = provider().childrenResult(BrowseTree.albumId("album-1"), 0, Int.MAX_VALUE).items()

        val playAll = items.first()
        assertEquals(BrowseTree.playAllId(BrowseTree.albumId("album-1")), playAll.mediaId)
        assertEquals(true, playAll.mediaMetadata.isPlayable)
        assertEquals("4 tracks", playAll.mediaMetadata.subtitle?.toString())
    }

    @Test
    fun playAllQueuesTheWholeFolderFromTheTop() = runTest {
        val playAll = MediaItem.Builder()
            .setMediaId(BrowseTree.playAllId(BrowseTree.playlistId(7)))
            .build()

        val expansion = provider().expandForPlayback(listOf(playAll))

        assertEquals(listOf("Angel", "Teardrop"), titles(expansion.items))
        assertEquals(0, expansion.startIndex)
    }

    @Test
    fun anEmptyFolderHasNoPlayAllRow() = runTest {
        routes["/api/tracks"] = "[]"

        val items = provider().childrenResult(BrowseTree.albumId("album-1"), 0, Int.MAX_VALUE).items()

        assertEquals(emptyList<MediaItem>(), items)
    }

    // ----- tap to play ---------------------------------------------------

    @Test
    fun tappingATrackQueuesItsSiblingsAtTheRightIndex() = runTest {
        val tapped = MediaItem.Builder()
            .setMediaId(BrowseTree.trackId(103L, BrowseTree.albumId("album-1")))
            .build()

        val expansion = provider().expandForPlayback(listOf(tapped))

        assertEquals(listOf("Angel", "Risingson", "Teardrop", "Inertia Creeps"), titles(expansion.items))
        assertEquals(2, expansion.startIndex)
        assertTrue(expansion.items.all { it.localConfiguration != null })
    }

    @Test(expected = UnsupportedOperationException::class)
    fun aVoiceSearchIsRejectedRatherThanPlayedAsNothing() = runTest {
        // The manifest has to advertise MEDIA_PLAY_FROM_SEARCH for Auto, but
        // search is not implemented; the old code handed the player an item
        // with no URI, which fails deep inside ExoPlayer instead of here.
        val spoken = MediaItem.Builder()
            .setRequestMetadata(
                MediaItem.RequestMetadata.Builder().setSearchQuery("play some jazz").build(),
            )
            .build()

        provider().expandForPlayback(listOf(spoken))
    }

    @Test
    fun aQueueIsBuiltWithoutFetchingArtwork() = runTest {
        // Artwork here bought nothing — the browser never renders queue items —
        // and every fetch delayed the first note.
        val tapped = MediaItem.Builder()
            .setMediaId(BrowseTree.trackId(101L, BrowseTree.albumId("album-1")))
            .build()

        val expansion = provider().expandForPlayback(listOf(tapped))

        assertEquals(0, hitsFor("/api/art/file/$SHA_A"))
        // The URI is still published, so notification art still resolves.
        assertNotNull(expansion.items.first().mediaMetadata.artworkUri)
    }

    @Test
    fun addingOneTrackAddsOneTrack() = runTest {
        // onAddMediaItems used to expand, so "add to queue" inserted the album.
        val tapped = MediaItem.Builder()
            .setMediaId(BrowseTree.trackId(103L, BrowseTree.albumId("album-1")))
            .build()

        val resolved = provider().resolveForQueue(listOf(tapped))

        assertEquals(1, resolved.size)
        assertNotNull(resolved.single().localConfiguration)
    }

    // ----- metadata ------------------------------------------------------

    @Test
    fun trackItemsCarryDurationAndArtwork() = runTest {
        val items = provider().childrenResult(BrowseTree.albumId("album-1"), 0, Int.MAX_VALUE).items()

        val angel = items.first { it.mediaMetadata.title?.toString() == "Angel" }
        assertEquals(379_000L, angel.mediaMetadata.durationMs)
        assertEquals("Massive Attack", angel.mediaMetadata.artist?.toString())
        assertNotNull(angel.mediaMetadata.artworkUri)
        assertNotNull(angel.localConfiguration)
    }

    @Test
    fun aSubtitleComesWithTheDisplayTitleThatMakesItRender() = runTest {
        // Media3 only forwards subtitle when displayTitle is set; otherwise it
        // falls back to (title, artist, album) and drops it.
        val items = provider().childrenResult(BrowseTree.ID_FAV_RELEASES, 0, Int.MAX_VALUE).items()

        val album = items.single().mediaMetadata
        assertEquals("Mezzanine", album.displayTitle?.toString())
        assertEquals("Massive Attack • 1998", album.subtitle?.toString())
    }

    @Test
    fun playlistsShowTheirTrackCount() = runTest {
        val items = provider().childrenResult(BrowseTree.ID_PLAYLISTS, 0, Int.MAX_VALUE).items()

        val playlist = items.single().mediaMetadata
        assertEquals("Night drive", playlist.displayTitle?.toString())
        assertEquals("3 tracks", playlist.subtitle?.toString())
    }

    // ----- dead ends -----------------------------------------------------

    @Test
    fun entriesWithoutAnMbidAreNotOfferedAsFolders() = runTest {
        // They were browsable but had no id to browse, so tapping opened an
        // empty screen.
        val p = provider()
        val artists = p.childrenResult(BrowseTree.ID_HISTORY_ARTISTS, 0, Int.MAX_VALUE).items()
        val albums = p.childrenResult(BrowseTree.ID_HISTORY_ALBUMS, 0, Int.MAX_VALUE).items()

        assertEquals(listOf("Portishead"), titles(artists))
        assertEquals(listOf("Dummy"), titles(albums))
        assertTrue(artists.all { it.mediaId.startsWith(BrowseTree.PREFIX_ARTIST) })
        assertTrue(albums.all { it.mediaId.startsWith(BrowseTree.PREFIX_ALBUM) })
    }

    // ----- caching -------------------------------------------------------

    @Test
    fun siblingNodesShareOnePayload() = runTest {
        val p = provider()
        p.childrenResult(BrowseTree.ID_HISTORY_ARTISTS, 0, Int.MAX_VALUE)
        p.childrenResult(BrowseTree.ID_HISTORY_ALBUMS, 0, Int.MAX_VALUE)

        // Both folders are one /api/history/stats response.
        assertEquals(1, hitsFor("/api/history/stats"))
    }

    @Test
    fun revisitingAFolderDoesNotRefetchIt() = runTest {
        val p = provider()
        p.childrenResult(BrowseTree.albumId("album-1"), 0, 2)
        p.childrenResult(BrowseTree.albumId("album-1"), 1, 2)
        p.childrenResult(BrowseTree.albumId("album-1"), 0, 2)

        assertEquals(1, hitsFor("/api/tracks"))
    }

    @Test
    fun aFreshProviderStartsWithAColdCache() = runTest {
        provider().childrenResult(BrowseTree.ID_PLAYLISTS, 0, Int.MAX_VALUE)
        provider().childrenResult(BrowseTree.ID_PLAYLISTS, 0, Int.MAX_VALUE)

        assertEquals(2, hitsFor("/api/playlists"))
    }

    // ----- artwork -------------------------------------------------------

    @Test
    fun aCleartextServerStillEmbedsBrowseArtwork() = runTest {
        // MockWebServer is http, so the host could not load an icon URI.
        val items = provider().childrenResult(BrowseTree.ID_FAV_ARTISTS, 0, Int.MAX_VALUE).items()

        assertNotNull(items.first().mediaMetadata.artworkData)
        assertNotNull(items.first().mediaMetadata.artworkUri)
        assertEquals(1, hitsFor("/api/art/file/$SHA_A"))
    }

    @Test
    fun artworkIsOnlyFetchedForTheRequestedPage() = runTest {
        provider().childrenResult(BrowseTree.albumId("album-1"), 0, 2)

        // Play all + one track on this page; the other three tracks are untouched.
        assertTrue("art fetches should be bounded by the page", hitsFor("/api/art/file/$SHA_A") <= 2)
    }

    companion object {
        private const val SHA_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        private const val SHA_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

        /** Smallest thing BitmapFactory will decode, as a JPEG byte string. */
        private val ONE_PIXEL_JPEG = (
            "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a" +
                "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAA" +
                "AAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="
            ).decodeBase64()!!
    }
}
