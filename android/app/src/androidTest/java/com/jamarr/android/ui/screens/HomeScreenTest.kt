package com.jamarr.android.ui.screens

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.jamarr.android.data.HomeAlbum
import com.jamarr.android.data.HomeArtist
import com.jamarr.android.data.HomeContent
import com.jamarr.android.data.SearchResponse
import com.jamarr.android.ui.theme.JamarrTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class HomeScreenTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun rendersHomeSections() {
        compose.setContent {
            JamarrTheme {
                HomeScreen(
                    greetingInitial = "D",
                    serverUrl = "https://jamarr.example",
                    homeContent = HomeContent(
                        newReleases = listOf(HomeAlbum(album = "Mezzanine", artistName = "Massive Attack")),
                        recentlyAddedAlbums = listOf(HomeAlbum(album = "Dummy", artistName = "Portishead")),
                        discoverArtists = listOf(HomeArtist(name = "Tricky")),
                    ),
                    searchResults = SearchResponse(),
                    searchQuery = "",
                    onSearchQueryChange = {},
                    onSearchSubmit = {},
                    onAlbumClick = {},
                    onArtistClick = {},
                    onTrackClick = {},
                    onSearchArtistClick = { _, _ -> },
                    onSearchAlbumClick = { _, _, _ -> },
                    onLogout = {},
                    artworkUrlForAlbum = { null },
                    artworkUrlForArtist = { null },
                    contentPadding = PaddingValues(),
                )
            }
        }

        compose.onNodeWithText("Good evening").assertIsDisplayed()
        compose.onNodeWithText("New Releases").assertIsDisplayed()
        compose.onNodeWithText("Mezzanine").assertIsDisplayed()
        compose.onNodeWithText("Recently Added").assertIsDisplayed()
        compose.onNodeWithText("Newly Added Artists").assertIsDisplayed()
    }

    @Test
    fun rendersEmptySearchState() {
        compose.setContent {
            JamarrTheme {
                HomeScreen(
                    greetingInitial = "D",
                    serverUrl = "https://jamarr.example",
                    homeContent = HomeContent(),
                    searchResults = SearchResponse(),
                    searchQuery = "xy",
                    onSearchQueryChange = {},
                    onSearchSubmit = {},
                    onAlbumClick = {},
                    onArtistClick = {},
                    onTrackClick = {},
                    onSearchArtistClick = { _, _ -> },
                    onSearchAlbumClick = { _, _, _ -> },
                    onLogout = {},
                    artworkUrlForAlbum = { null },
                    artworkUrlForArtist = { null },
                    contentPadding = PaddingValues(),
                )
            }
        }

        compose.onNodeWithText("No results yet. Keep typing…").assertIsDisplayed()
    }
}
