package com.jamarr.android.ui.screens

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.jamarr.android.auth.TokenHolder
import com.jamarr.android.data.JamarrApiClient
import com.jamarr.android.playback.JamarrPlaybackController
import com.jamarr.android.ui.state.JamarrAppContext
import com.jamarr.android.ui.state.LocalJamarrContext
import com.jamarr.android.ui.theme.JamarrTheme
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AuthenticatedScreensTest {
    @get:Rule
    val compose = createComposeRule()

    private lateinit var server: MockWebServer
    private lateinit var playbackController: JamarrPlaybackController

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        playbackController = JamarrPlaybackController(InstrumentationRegistry.getInstrumentation().targetContext)
    }

    @After
    fun tearDown() {
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            playbackController.release()
        }
        server.close()
    }

    @Test
    fun favouritesScreenLoadsArtistsAndReleases() {
        server.enqueue(jsonResponse("""[{"mbid":"artist-1","name":"Portishead","listens":12}]"""))
        server.enqueue(jsonResponse("""[{"album_mbid":"album-1","title":"Dummy","artist_name":"Portishead"}]"""))

        setAuthenticatedContent {
            FavouritesScreen(
                onArtistClick = { _, _ -> },
                onAlbumClick = { _, _, _ -> },
                contentPadding = PaddingValues(),
            )
        }

        waitForText("Portishead")
        compose.onNodeWithText("Favourites").assertIsDisplayed()
        compose.onNodeWithText("Portishead").assertIsDisplayed()
        compose.onNodeWithText("12 plays").assertIsDisplayed()
    }

    @Test
    fun playlistsScreenLoadsRows() {
        server.enqueue(
            jsonResponse(
                """
                [
                  {
                    "id": 7,
                    "name": "Late Night",
                    "track_count": 2,
                    "total_duration": 500,
                    "updated_at": "2026-04-26"
                  }
                ]
                """.trimIndent()
            )
        )

        setAuthenticatedContent {
            PlaylistsScreen(onPlaylistClick = {}, contentPadding = PaddingValues())
        }

        waitForText("Late Night")
        compose.onNodeWithText("Playlists").assertIsDisplayed()
        compose.onNodeWithText("Late Night").assertIsDisplayed()
        compose.onNodeWithText("2 tracks", substring = true).assertIsDisplayed()
    }

    @Test
    fun chartsScreenLoadsChartEntries() {
        server.enqueue(
            jsonResponse(
                """
                [
                  {"position": 1, "title": "Blue Lines", "artist": "Massive Attack"},
                  {"position": 2, "title": "Dummy", "artist": "Portishead"}
                ]
                """.trimIndent()
            )
        )

        setAuthenticatedContent {
            ChartsScreen(onAlbumClick = {}, contentPadding = PaddingValues())
        }

        waitForText("Blue Lines")
        compose.onNodeWithText("Charts").assertIsDisplayed()
        compose.onNodeWithText("Blue Lines").assertIsDisplayed()
        compose.onNodeWithText("Dummy").assertIsDisplayed()
    }

    @Test
    fun historyScreenLoadsStats() {
        server.enqueue(
            jsonResponse(
                """
                {
                  "tracks": [{"id": 1, "title": "Angel", "artist": "Massive Attack", "plays": 4}],
                  "albums": [{"album": "Mezzanine", "artist": "Massive Attack", "plays": 3}],
                  "artists": [{"artist_name": "Massive Attack", "plays": 8}]
                }
                """.trimIndent()
            )
        )

        setAuthenticatedContent {
            HistoryScreen(
                onArtistClick = { _, _ -> },
                onAlbumClick = { _, _, _ -> },
                onTrackClick = {},
                contentPadding = PaddingValues(),
            )
        }

        waitForText("Angel")
        compose.onNodeWithText("History").assertIsDisplayed()
        compose.onNodeWithText("Angel").assertIsDisplayed()
        compose.onNodeWithText("Massive Attack").assertIsDisplayed()
    }

    private fun setAuthenticatedContent(content: @Composable () -> Unit) {
        compose.setContent {
            JamarrTheme {
                CompositionLocalProvider(
                    LocalJamarrContext provides JamarrAppContext(
                        apiClient = JamarrApiClient(TokenHolder("token")),
                        playbackController = playbackController,
                        serverUrl = server.url("/").toString(),
                        accessToken = "token",
                    ),
                ) {
                    content()
                }
            }
        }
    }

    private fun waitForText(text: String) {
        compose.waitUntil(timeoutMillis = 5_000) {
            compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty()
        }
    }

    private fun jsonResponse(body: String): MockResponse =
        MockResponse.Builder()
            .code(200)
            .body(body)
            .addHeader("Content-Type", "application/json")
            .build()
}
