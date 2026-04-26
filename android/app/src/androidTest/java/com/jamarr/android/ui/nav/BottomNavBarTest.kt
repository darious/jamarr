package com.jamarr.android.ui.nav

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.jamarr.android.ui.theme.JamarrTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class BottomNavBarTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun rendersAllTabsAndDispatchesSelection() {
        var selected = JamarrTab.Home

        compose.setContent {
            JamarrTheme {
                BottomNavBar(selected = selected, onSelect = { selected = it })
            }
        }

        JamarrTab.entries.forEach { tab ->
            compose.onNodeWithText(tab.title).assertIsDisplayed()
        }

        compose.onNodeWithText("Charts").performClick()

        assertEquals(JamarrTab.Charts, selected)
    }
}
