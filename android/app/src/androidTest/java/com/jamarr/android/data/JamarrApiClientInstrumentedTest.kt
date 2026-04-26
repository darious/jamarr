package com.jamarr.android.data

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.jamarr.android.auth.TokenHolder
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class JamarrApiClientInstrumentedTest {
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
    fun searchUsesRealAndroidNetworkingStack() = runTest {
        server.enqueue(
            MockResponse.Builder()
                .code(200)
                .body(
                    """
                    {
                      "artists": [{"name": "Massive Attack", "mbid": "artist-1"}],
                      "albums": [{"title": "Mezzanine", "artist": "Massive Attack"}],
                      "tracks": [{"id": 1, "title": "Angel", "artist": "Massive Attack"}]
                    }
                    """.trimIndent()
                )
                .addHeader("Content-Type", "application/json")
                .build()
        )
        val client = JamarrApiClient(TokenHolder("android-token"))

        val response = client.search(server.url("/").toString(), "ignored", "angel")
        val request = server.takeRequest()

        assertEquals("/api/search?q=angel", request.url.encodedPath + "?" + request.url.encodedQuery)
        assertEquals("Bearer android-token", request.headers["Authorization"])
        assertEquals("Massive Attack", response.artists.single().name)
        assertEquals("Mezzanine", response.albums.single().title)
        assertEquals("Angel", response.tracks.single().title)
    }

    @Test
    fun loginUsesRealAndroidNetworkingStackWithoutBearerHeader() = runTest {
        server.enqueue(
            MockResponse.Builder()
                .code(200)
                .body("""{"access_token":"android-access-token","token_type":"bearer"}""")
                .addHeader("Content-Type", "application/json")
                .build()
        )
        val client = JamarrApiClient(TokenHolder("old-token"))

        val response = client.login(server.url("/").toString(), "user", "pass")
        val request = server.takeRequest()

        assertEquals("android-access-token", response.accessToken)
        assertEquals("/api/auth/login", request.url.encodedPath)
        assertEquals("""{"username":"user","password":"pass"}""", request.body?.utf8())
        assertEquals(null, request.headers["Authorization"])
    }
}
