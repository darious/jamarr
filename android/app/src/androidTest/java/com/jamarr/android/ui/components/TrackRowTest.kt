package com.jamarr.android.ui.components

import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.text.style.TextDecoration
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.jamarr.android.ui.theme.JamarrTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class TrackRowTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun missingTrackTitleIsStruckThrough() {
        setUpRow(title = "Ghost Track", missing = true)

        assertEquals(listOf(TextDecoration.LineThrough), titleDecorationsOf("Ghost Track"))
    }

    @Test
    fun presentTrackTitleIsNotStruckThrough() {
        setUpRow(title = "Real Track", missing = false)

        assertEquals(emptyList<TextDecoration>(), titleDecorationsOf("Real Track"))
    }

    private fun setUpRow(title: String, missing: Boolean) {
        compose.setContent {
            JamarrTheme {
                TrackRow(
                    number = 1,
                    title = title,
                    subtitle = "Some Album",
                    duration = "3:21",
                    active = false,
                    onClick = {},
                    missing = missing,
                )
            }
        }
    }

    /**
     * Decorations carried by the title's own spans, in order. Reads the unmerged
     * tree: the merged row node folds the subtitle and duration in alongside the
     * title, so there would be no single text to inspect.
     */
    private fun titleDecorationsOf(title: String): List<TextDecoration> =
        compose.onNodeWithText(title, useUnmergedTree = true)
            .fetchSemanticsNode()
            .config[SemanticsProperties.Text]
            .single()
            .spanStyles
            .mapNotNull { it.item.textDecoration }
}
