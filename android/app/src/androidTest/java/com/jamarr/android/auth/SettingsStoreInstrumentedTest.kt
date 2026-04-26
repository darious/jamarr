package com.jamarr.android.auth

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SettingsStoreInstrumentedTest {
    private val store = SettingsStore(InstrumentationRegistry.getInstrumentation().targetContext)

    @Test
    fun persistsSessionValues() = runTest {
        store.saveServerUrl(" https://jamarr.example ")
        store.saveAccessToken("access-token")
        store.saveActiveTab(3)

        val session = store.load()

        assertEquals("https://jamarr.example", session.serverUrl)
        assertEquals("access-token", session.accessToken)
        assertEquals(3, session.activeTabIndex)
    }

    @Test
    fun clearAccessTokenRemovesOnlyToken() = runTest {
        store.saveServerUrl("https://jamarr.example")
        store.saveAccessToken("token-to-clear")

        store.clearAccessToken()
        val session = store.load()

        assertEquals("https://jamarr.example", session.serverUrl)
        assertEquals("", session.accessToken)
    }

    @Test
    fun clientIdIsStableAfterCreation() = runTest {
        val first = store.getClientId()
        val second = store.getClientId()

        assertEquals(first, second)
        assertNotEquals("", first)
    }
}
