package com.jamarr.android.ui.components

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.jamarr.android.ui.theme.JamarrTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MiniPlayerTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun rendersTrackMetadataAndDispatchesControls() {
        val calls = mutableListOf<String>()

        compose.setContent {
            JamarrTheme {
                MiniPlayer(
                    title = "Angel",
                    artist = "Massive Attack",
                    isPlaying = false,
                    artworkUrl = null,
                    seedName = "Mezzanine",
                    progressMs = 10_000,
                    durationMs = 100_000,
                    onToggle = { calls += "toggle" },
                    onPrevious = { calls += "previous" },
                    onNext = { calls += "next" },
                    onStop = { calls += "stop" },
                    onSeek = { calls += "seek" },
                    onClick = { calls += "open" },
                )
            }
        }

        compose.onNodeWithText("Angel").assertIsDisplayed().performClick()
        compose.onNodeWithText("Massive Attack").assertIsDisplayed()
        compose.onNodeWithContentDescription("Previous").performClick()
        compose.onNodeWithContentDescription("Play").performClick()
        compose.onNodeWithContentDescription("Next").performClick()
        compose.onNodeWithContentDescription("Stop").performClick()

        assertEquals(listOf("open", "previous", "toggle", "next", "stop"), calls)
    }
}
