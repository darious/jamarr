package com.jamarr.android.ui.screens

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.jamarr.android.data.OnlineState
import com.jamarr.android.data.SearchTrack
import com.jamarr.android.download.DownloadProgress
import com.jamarr.android.download.GroupDownloadStatus
import com.jamarr.android.download.db.DownloadGroupEntity
import com.jamarr.android.download.db.DownloadGroupKind
import com.jamarr.android.download.db.DownloadRecordState
import com.jamarr.android.download.db.DownloadedTrackEntity
import com.jamarr.android.ui.components.GroupDownloadButton
import com.jamarr.android.ui.theme.JamarrTheme
import kotlinx.coroutines.flow.flowOf
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** The Phase 3 offline screens, fed directly — none of them call the API. */
@RunWith(AndroidJUnit4::class)
class DownloadScreensTest {
    @get:Rule
    val compose = createComposeRule()

    private val tracks = listOf(track(1, "Dummy Track"), track(2, "Second Track"))
    private val groups = listOf(
        group("album:a", DownloadGroupKind.ALBUM, "Dummy", "Portishead"),
        group("artist:p", DownloadGroupKind.ARTIST, "Portishead", "All releases"),
        group("artist_top:p:scrobbled", DownloadGroupKind.ARTIST_TOP, "Portishead", "Most Scrobbled"),
        group("playlist:7", DownloadGroupKind.PLAYLIST, "Trip Hop", null),
        group("track:2", DownloadGroupKind.TRACK, "Second Track", "Portishead"),
    )
    private val groupTracks = mapOf(
        "album:a" to listOf(1L, 2L),
        "artist:p" to listOf(1L, 2L),
        "artist_top:p:scrobbled" to listOf(1L),
        "playlist:7" to listOf(2L),
        "track:2" to listOf(2L),
    )
    private val complete = mapOf(
        1L to DownloadProgress(1, DownloadRecordState.COMPLETED, 100f),
        2L to DownloadProgress(2, DownloadRecordState.COMPLETED, 100f),
    )

    @Test
    fun downloadsAreListedUnderTheirTabs() {
        setDownloads()

        compose.onNodeWithText("Dummy Track").assertIsDisplayed()

        compose.onNodeWithText("Albums").performClick()
        compose.onNodeWithText("Portishead · 2 tracks").assertIsDisplayed()

        compose.onNodeWithText("Artists").performClick()
        compose.onNodeWithText("All releases · 2 tracks").assertIsDisplayed()
        compose.onNodeWithText("Most Scrobbled · kept in sync · 1 track").assertIsDisplayed()

        compose.onNodeWithText("Playlists").performClick()
        compose.onNodeWithText("Trip Hop").assertIsDisplayed()
        // A standalone track download lives under Tracks only.
        compose.onNodeWithText("Second Track").assertDoesNotExist()
    }

    @Test
    fun tappingAGroupOpensIt() {
        var opened: String? = null
        setDownloads(onGroupClick = { opened = it })

        compose.onNodeWithText("Playlists").performClick()
        compose.onNodeWithText("Trip Hop").performClick()

        assertEquals("playlist:7", opened)
    }

    @Test
    fun manualOfflineOffersAWayBackOnline() {
        var wentOnline = false
        setDownloads(onlineState = OnlineState(manualOffline = true), onGoOnline = { wentOnline = true })

        compose.onNodeWithText("Offline mode is on.").assertIsDisplayed()
        compose.onNodeWithText("Go online").performClick()

        assertEquals(true, wentOnline)
    }

    @Test
    fun anUnreachableServerSaysSoWithoutAGoOnlineButton() {
        setDownloads(onlineState = OnlineState(serverReachable = false))

        compose.onNodeWithText("Can't reach the server.").assertIsDisplayed()
        compose.onNodeWithText("Go online").assertDoesNotExist()
    }

    @Test
    fun onlineShowsNoBanner() {
        setDownloads()

        compose.onNodeWithText("Playing from this device.").assertDoesNotExist()
    }

    @Test
    fun groupScreenShowsProgressAndPlaysItsTracks() {
        var played: List<SearchTrack>? = null
        compose.setContent {
            JamarrTheme {
                DownloadGroupScreen(
                    group = groups.first(),
                    tracksFlow = flowOf(listOf(tracks[0], tracks[1].copy(state = DownloadRecordState.QUEUED))),
                    downloadStates = mapOf(1L to DownloadProgress(1, DownloadRecordState.COMPLETED, 100f)),
                    nowPlayingTrackId = null,
                    artworkUrl = { _, _ -> null },
                    onBack = {},
                    onPlayTracks = { queue, _ -> played = queue },
                    onRemove = {},
                    contentPadding = PaddingValues(),
                )
            }
        }

        compose.onNodeWithText("Portishead · 1 of 2 tracks").assertIsDisplayed()
        // Track 2 is still queued, so its row shows that instead of a duration.
        compose.onNodeWithText("queued").assertIsDisplayed()

        compose.onNodeWithText("Shuffle").performClick()

        assertEquals(setOf(1L, 2L), played?.map { it.id }?.toSet())
    }

    @Test
    fun removingAGroupAsksFirst() {
        var removed = false
        compose.setContent {
            JamarrTheme {
                DownloadGroupScreen(
                    group = groups.first(),
                    tracksFlow = flowOf(tracks),
                    downloadStates = complete,
                    nowPlayingTrackId = null,
                    artworkUrl = { _, _ -> null },
                    onBack = {},
                    onPlayTracks = { _, _ -> },
                    onRemove = { removed = true },
                    contentPadding = PaddingValues(),
                )
            }
        }

        compose.onNodeWithContentDescription("Downloaded, remove").performClick()
        compose.onNodeWithText("Remove download?").assertIsDisplayed()
        assertEquals(false, removed)

        compose.onNodeWithText("Remove").performClick()

        assertEquals(true, removed)
    }

    @Test
    fun offlinePlaceholderPointsAtDownloads() {
        var opened = false
        compose.setContent {
            JamarrTheme {
                OfflinePlaceholder(
                    title = "Charts",
                    onlineState = OnlineState(networkAvailable = false),
                    onGoOnline = {},
                    onOpenDownloads = { opened = true },
                )
            }
        }

        compose.onNodeWithText("No network connection.").assertIsDisplayed()
        compose.onNodeWithText("Charts needs the server. Your downloads are still here.").assertIsDisplayed()
        compose.onNodeWithText("Open downloads").performClick()

        assertEquals(true, opened)
    }

    @Test
    fun groupDownloadButtonDescribesEachState() {
        val states = listOf(
            null to "Download",
            GroupDownloadStatus(total = 2, completed = 2, failed = 0, percent = 100f) to "Downloaded, remove",
            GroupDownloadStatus(total = 2, completed = 1, failed = 0, percent = 50f) to "Downloading, cancel",
            GroupDownloadStatus(total = 2, completed = 1, failed = 1, percent = 50f) to
                "Download failed for 1 tracks, remove",
        )
        var index by mutableIntStateOf(0)
        compose.setContent {
            JamarrTheme {
                GroupDownloadButton(status = states[index].first, onClick = {})
            }
        }

        states.forEachIndexed { i, (_, description) ->
            index = i
            compose.onNodeWithContentDescription(description).assertIsDisplayed()
        }
        index = 2
        compose.onNodeWithText("50%").assertIsDisplayed()
    }

    private fun setDownloads(
        onlineState: OnlineState = OnlineState(),
        onGoOnline: () -> Unit = {},
        onGroupClick: (String) -> Unit = {},
    ) {
        compose.setContent {
            JamarrTheme {
                DownloadsScreen(
                    tracks = tracks,
                    groups = groups,
                    groupTracks = groupTracks,
                    downloadStates = complete,
                    nowPlayingTrackId = null,
                    onlineState = onlineState,
                    onGoOnline = onGoOnline,
                    onTrackClick = { _, _ -> },
                    onRemoveTrack = {},
                    onGroupClick = onGroupClick,
                    artworkUrl = { _, _ -> null },
                )
            }
        }
    }

    private fun group(id: String, kind: DownloadGroupKind, title: String, subtitle: String?) =
        DownloadGroupEntity(
            groupId = id,
            kind = kind,
            title = title,
            subtitle = subtitle,
            artSha1 = null,
            requestedAt = 0L,
        )

    private fun track(id: Long, title: String) = DownloadedTrackEntity(
        trackId = id,
        title = title,
        artist = "Portishead",
        album = "Dummy",
        albumMbid = null,
        artistMbid = null,
        artSha1 = null,
        durationSeconds = 180.0,
        quality = "original",
        sizeBytes = 1_000_000L,
        state = DownloadRecordState.COMPLETED,
        addedAt = 0L,
    )
}
