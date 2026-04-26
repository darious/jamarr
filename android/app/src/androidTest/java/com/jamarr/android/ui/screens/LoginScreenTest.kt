package com.jamarr.android.ui.screens

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.jamarr.android.ui.theme.JamarrTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LoginScreenTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun loginButtonIsDisabledUntilRequiredFieldsArePresent() {
        compose.setContent {
            JamarrTheme {
                LoginScreen(
                    serverUrl = "https://jamarr.example",
                    username = "",
                    password = "",
                    busy = false,
                    status = "Connect to Jamarr.",
                    onServerUrlChange = {},
                    onUsernameChange = {},
                    onPasswordChange = {},
                    onSubmit = {},
                )
            }
        }

        compose.onNodeWithText("Jamarr Music").assertIsDisplayed()
        compose.onNodeWithText("Connect to Jamarr.").assertIsDisplayed()
        compose.onNodeWithText("Log in").assertIsNotEnabled()
    }

    @Test
    fun loginButtonSubmitsWhenRequiredFieldsArePresent() {
        var submitCount = 0

        compose.setContent {
            JamarrTheme {
                LoginScreen(
                    serverUrl = "https://jamarr.example",
                    username = "darious",
                    password = "secret",
                    busy = false,
                    status = "Ready.",
                    onServerUrlChange = {},
                    onUsernameChange = {},
                    onPasswordChange = {},
                    onSubmit = { submitCount += 1 },
                )
            }
        }

        compose.onNodeWithText("Log in").assertIsEnabled().performClick()

        assertEquals(1, submitCount)
    }

    @Test
    fun textFieldCallbacksReceiveUserInput() {
        var serverUrl by mutableStateOf("")
        var username by mutableStateOf("")
        var password by mutableStateOf("")

        compose.setContent {
            JamarrTheme {
                LoginScreen(
                    serverUrl = serverUrl,
                    username = username,
                    password = password,
                    busy = false,
                    status = "Ready.",
                    onServerUrlChange = { serverUrl = it },
                    onUsernameChange = { username = it },
                    onPasswordChange = { password = it },
                    onSubmit = {},
                )
            }
        }

        compose.onAllNodes(hasSetTextAction()).assertCountEquals(3)
        compose.onNodeWithText("Server URL").performTextInput("https://jamarr.example")
        compose.onNodeWithText("Username").performTextInput("darious")
        compose.onNodeWithText("Password").performTextInput("secret")

        compose.runOnIdle {
            assertEquals("https://jamarr.example", serverUrl)
            assertEquals("darious", username)
            assertEquals("secret", password)
        }
    }
}
