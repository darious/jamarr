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
}
