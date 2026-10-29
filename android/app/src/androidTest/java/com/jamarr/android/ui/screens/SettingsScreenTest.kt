package com.jamarr.android.ui.screens

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.jamarr.android.playback.StreamingQualityPrefs
import com.jamarr.android.ui.theme.JamarrTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SettingsScreenTest {
    @get:Rule
    val compose = createComposeRule()

    private var quality: String? = null
    private var cap: Long? = null
    private var wifiOnly: Boolean? = null
    private var cleared = false
    private var deletedAll = false
    private var streaming: Pair<String?, String?>? = null

    private fun setSettings() {
        compose.setContent {
            JamarrTheme {
                SettingsScreen(
                    downloadQuality = "flac_16_48",
                    wifiOnly = false,
                    readAheadMaxBytes = 1024L * 1024 * 1024,
                    storage = StorageUsage(
                        downloadBytes = 3L * 1024 * 1024 * 1024,
                        readAheadBytes = 0L,
                        artworkBytes = 5L * 1024 * 1024,
                    ),
                    onBack = {},
                    onDownloadQualityChange = { quality = it },
                    onWifiOnlyChange = { wifiOnly = it },
                    onReadAheadMaxBytesChange = { cap = it },
                    onClearReadAhead = { cleared = true },
                    onDeleteAllDownloads = { deletedAll = true },
                    streamingQuality = StreamingQualityPrefs(unmetered = "original", metered = "flac_16_48"),
                    onStreamingQualityChange = { u, m -> streaming = u to m },
                )
            }
        }
    }

    @Test
    fun choosingADownloadQualityReportsItsKey() {
        setSettings()

        compose.onNodeWithText("FLAC 16-bit / 48 kHz").assertIsDisplayed()
        compose.onNodeWithText("MP3 320").performClick()

        assertEquals("mp3_320", quality)
    }

    @Test
    fun wifiOnlyAndReadAheadCapAreSettable() {
        setSettings()

        compose.onNodeWithText("Downloads on Wi-Fi only").performClick()
        compose.onNodeWithText("2.0 GB").performScrollTo().performClick()

        assertEquals(true, wifiOnly)
        assertEquals(2048L * 1024 * 1024, cap)
    }

    @Test
    fun storageIsShownAndReadAheadCanBeCleared() {
        setSettings()

        compose.onNodeWithText("3.0 GB").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("None").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("Clear").performScrollTo().performClick()

        assertEquals(true, cleared)
    }

    @Test
    fun streamingCapsArePickedPerNetwork() {
        setSettings()

        // The metered row shows its current value, and picking changes only it.
        compose.onNodeWithText("On mobile data (metered)").assertIsDisplayed()
        compose.onNodeWithText("FLAC 16/48").assertIsDisplayed()
        // The picker repeats the download-quality labels, so match inside it.
        val inDialog = hasAnyAncestor(hasTestTag(STREAMING_QUALITY_DIALOG_TAG))
        compose.onNodeWithText("On mobile data (metered)").performClick()
        compose.onNode(hasText("Opus 128") and inDialog).performClick()
        assertEquals(null to "opus_128", streaming)

        compose.onNodeWithText("On Wi-Fi (unmetered)").performClick()
        compose.onNode(hasText("FLAC 24-bit / 48 kHz") and inDialog).performClick()
        assertEquals("flac_24_48" to null, streaming)
    }

    @Test
    fun deletingAllDownloadsAsksFirst() {
        setSettings()

        compose.onNodeWithText("Delete all downloads").performScrollTo().performClick()
        compose.onNodeWithText("Delete all downloads?").assertIsDisplayed()
        assertEquals(false, deletedAll)

        compose.onNodeWithText("Delete").performClick()

        assertEquals(true, deletedAll)
    }
}
