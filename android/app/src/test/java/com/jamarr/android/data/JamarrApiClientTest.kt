package com.jamarr.android.data

import com.jamarr.android.auth.TokenHolder
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

class JamarrApiClientTest {
    private lateinit var server: MockWebServer

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        server.close()
    }

    @Test
    fun normalizeServerUrlTrimsWhitespaceAndTrailingSlash() {
        val client = JamarrApiClient()

        assertEquals("https://jamarr.example", client.normalizeServerUrl(" https://jamarr.example/ "))
    }

    @Test
    fun normalizeServerUrlRequiresHttpScheme() {
        val client = JamarrApiClient()

        val error = assertThrows(IllegalArgumentException::class.java) {
            client.normalizeServerUrl("jamarr.example")
        }

        assertTrue(error.message.orEmpty().contains("http:// or https://"))
    }

    @Test
    fun artworkUrlResolvesRelativeApiPathAgainstServerRoot() {
        val client = JamarrApiClient()

        assertEquals(
            "https://jamarr.example/api/art/file/abc123?max_size=256",
            client.artworkUrl("https://jamarr.example/music/", "abc123", maxSize = 256),
        )
    }

    @Test
    fun loginPostsCredentialsAndDecodesToken() = runTest {
        server.enqueue(
            MockResponse.Builder()
                .code(200)
                .body("""{"access_token":"token-123","token_type":"bearer"}""")
                .addHeader("Content-Type", "application/json")
                .build()
        )
        val client = JamarrApiClient(TokenHolder("existing-token"))

        val response = client.login(server.url("/").toString(), "darious", "secret")
        val request = server.takeRequest()

        assertEquals("token-123", response.accessToken)
        assertEquals("/api/auth/login", request.url.encodedPath)
        assertEquals("POST", request.method)
        assertEquals("""{"username":"darious","password":"secret"}""", request.body?.utf8())
        assertEquals(null, request.headers["Authorization"])
    }

    @Test
    fun searchSendsBearerTokenAndQueryParameter() = runTest {
        server.enqueue(
            MockResponse.Builder()
                .code(200)
                .body(
                    """
                    {
                      "artists": [],
                      "albums": [],
                      "tracks": [
                        {
                          "id": 42,
                          "title": "Track",
                          "artist": "Artist",
                          "album": "Album",
                          "duration_seconds": 123.4,
                          "art_sha1": "art"
                        }
                      ]
                    }
                    """.trimIndent()
                )
                .addHeader("Content-Type", "application/json")
                .build()
        )
        val client = JamarrApiClient(TokenHolder("access-token"))

        val response = client.search(server.url("/").toString(), "ignored", "Track Name")
        val request = server.takeRequest()

        assertEquals("/api/search?q=Track%20Name", request.url.encodedPath + "?" + request.url.encodedQuery)
        assertEquals("Bearer access-token", request.headers["Authorization"])
        assertEquals(1, response.tracks.size)
        assertEquals("Track", response.tracks.single().title)
    }

    @Test
    fun unsuccessfulResponsesThrowApiExceptionWithDetailMessage() = runTest {
        server.enqueue(
            MockResponse.Builder()
                .code(403)
                .body("""{"detail":"admin access required"}""")
                .addHeader("Content-Type", "application/json")
                .build()
        )
        val client = JamarrApiClient()

        val error = try {
            client.search(server.url("/").toString(), "ignored", "anything")
            fail("Expected JamarrApiException")
            return@runTest
        } catch (error: JamarrApiException) {
            error
        }

        assertEquals(403, error.statusCode)
        assertEquals("admin access required", error.message)
    }

    @Test
    fun blankArtworkHashReturnsNull() {
        val client = JamarrApiClient()

        assertEquals(null, client.artworkUrl("https://jamarr.example", " "))
    }

    @Test
    fun getRenderersFetchesListWithRefreshParam() = runTest {
        server.enqueue(
            MockResponse.Builder()
                .code(200)
                .body("""[{"udn":"uuid:1","renderer_id":"upnp:uuid:1","name":"Speaker","kind":"upnp","type":"upnp","ip":"10.0.0.1"}]""")
                .addHeader("Content-Type", "application/json")
                .build()
        )
        val client = JamarrApiClient(TokenHolder("token"))

        val renderers = client.getRenderers(server.url("/").toString(), refresh = true)
        val request = server.takeRequest()

        assertEquals("/api/renderers?refresh=true", request.url.encodedPath + "?" + request.url.encodedQuery)
        assertEquals("GET", request.method)
        assertEquals(1, renderers.size)
        assertEquals("uuid:1", renderers.single().udn)
        assertEquals("upnp:uuid:1", renderers.single().activeKey)
        assertEquals("Speaker", renderers.single().name)
    }

    @Test
    fun getRenderersOmitsRefreshWhenFalse() = runTest {
        server.enqueue(
            MockResponse.Builder()
                .code(200)
                .body("[]")
                .addHeader("Content-Type", "application/json")
                .build()
        )
        val client = JamarrApiClient(TokenHolder("token"))

        client.getRenderers(server.url("/").toString(), refresh = false)
        val request = server.takeRequest()

        assertEquals("/api/renderers", request.url.encodedPath)
        assertEquals(null, request.url.encodedQuery)
    }

    @Test
    fun setRendererPostsRendererIdWithClientIdHeader() = runTest {
        server.enqueue(
            MockResponse.Builder()
                .code(200)
                .body("{}")
                .build()
        )
        val client = JamarrApiClient(TokenHolder("token"))

        client.setRenderer(server.url("/").toString(), "client-123", "upnp:uuid:speaker-1")
        val request = server.takeRequest()

        assertEquals("/api/player/renderer", request.url.encodedPath)
        assertEquals("POST", request.method)
        assertEquals("client-123", request.headers["X-Jamarr-Client-Id"])
        assertEquals("""{"renderer_id":"upnp:uuid:speaker-1"}""", request.body?.utf8())
    }

    @Test
    fun setRendererThrowsOnError() = runTest {
        server.enqueue(
            MockResponse.Builder()
                .code(404)
                .body("""{"detail":"renderer not found"}""")
                .addHeader("Content-Type", "application/json")
                .build()
        )
        val client = JamarrApiClient()

        val error = try {
            client.setRenderer(server.url("/").toString(), "c", "bad-udn")
            fail("Expected JamarrApiException")
            return@runTest
        } catch (error: JamarrApiException) {
            error
        }
        assertEquals(404, error.statusCode)
        assertEquals("renderer not found", error.message)
    }

    @Test
    fun getPlayerStateDecodesResponse() = runTest {
        server.enqueue(
            MockResponse.Builder()
                .code(200)
                .body(
                    """
                    {
                      "queue": [],
                      "current_index": -1,
                      "position_seconds": 0.0,
                      "is_playing": false,
                      "renderer": "",
                      "volume": 50
                    }
                    """.trimIndent()
                )
                .addHeader("Content-Type", "application/json")
                .build()
        )
        val client = JamarrApiClient(TokenHolder("token"))

        val state = client.getPlayerState(server.url("/").toString(), "client-1")
        val request = server.takeRequest()

        assertEquals("/api/player/state", request.url.encodedPath)
        assertEquals("GET", request.method)
        assertEquals("client-1", request.headers["X-Jamarr-Client-Id"])
        assertEquals(false, state.isPlaying)
        assertEquals(50, state.volume)
    }

    @Test
    fun remotePauseSendsPostWithEmptyBody() = runTest {
        server.enqueue(MockResponse.Builder().code(200).body("{}").build())
        val client = JamarrApiClient(TokenHolder("token"))

        client.remotePause(server.url("/").toString(), "c1")
        val request = server.takeRequest()

        assertEquals("/api/player/pause", request.url.encodedPath)
        assertEquals("POST", request.method)
        assertEquals("c1", request.headers["X-Jamarr-Client-Id"])
    }

    @Test
    fun remotePauseThrowsOnError() = runTest {
        server.enqueue(
            MockResponse.Builder()
                .code(500)
                .body("""{"detail":"server error"}""")
                .addHeader("Content-Type", "application/json")
                .build()
        )
        val client = JamarrApiClient()

        val error = try {
            client.remotePause(server.url("/").toString(), "c1")
            fail("Expected JamarrApiException")
            return@runTest
        } catch (error: JamarrApiException) {
            error
        }
        assertEquals(500, error.statusCode)
    }

    @Test
    fun remotePlaySendsTrackIdInBody() = runTest {
        server.enqueue(MockResponse.Builder().code(200).body("{}").build())
        val client = JamarrApiClient(TokenHolder("token"))

        client.remotePlay(server.url("/").toString(), "c1", trackId = 99)
        val request = server.takeRequest()

        assertEquals("/api/player/play", request.url.encodedPath)
        assertEquals("POST", request.method)
        assertEquals("""{"track_id":99}""", request.body?.utf8())
    }

    @Test
    fun remoteSeekSendsSecondsInBody() = runTest {
        server.enqueue(MockResponse.Builder().code(200).body("{}").build())
        val client = JamarrApiClient(TokenHolder("token"))

        client.remoteSeek(server.url("/").toString(), "c1", seconds = 120.5)
        val request = server.takeRequest()

        assertEquals("/api/player/seek", request.url.encodedPath)
        assertEquals("""{"seconds":120.5}""", request.body?.utf8())
    }

    @Test
    fun remoteVolumeThrowsOnError() = runTest {
        server.enqueue(
            MockResponse.Builder()
                .code(400)
                .body("""{"detail":"invalid volume"}""")
                .addHeader("Content-Type", "application/json")
                .build()
        )
        val client = JamarrApiClient()

        val error = try {
            client.remoteVolume(server.url("/").toString(), "c1", percent = 200)
            fail("Expected JamarrApiException")
            return@runTest
        } catch (error: JamarrApiException) {
            error
        }
        assertEquals(400, error.statusCode)
    }

    @Test
    fun remoteClearQueueSendsPostToCorrectPath() = runTest {
        server.enqueue(MockResponse.Builder().code(200).body("{}").build())
        val client = JamarrApiClient(TokenHolder("token"))

        client.remoteClearQueue(server.url("/").toString(), "c1")
        val request = server.takeRequest()

        assertEquals("/api/player/queue/clear", request.url.encodedPath)
        assertEquals("POST", request.method)
        assertEquals("c1", request.headers["X-Jamarr-Client-Id"])
    }
}
