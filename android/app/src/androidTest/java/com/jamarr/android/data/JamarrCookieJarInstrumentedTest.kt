package com.jamarr.android.data

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.jamarr.android.auth.SettingsStore
import kotlinx.coroutines.delay
import kotlinx.coroutines.test.runTest
import okhttp3.Cookie
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class JamarrCookieJarInstrumentedTest {
    private lateinit var settingsStore: SettingsStore

    @Before
    fun setUp() = runTest {
        settingsStore = SettingsStore(InstrumentationRegistry.getInstrumentation().targetContext)
        settingsStore.saveCookies(emptyList())
    }

    @Test
    fun persistsAndPrimesCookies() = runTest {
        val url = "https://jamarr.example/api/auth/login".toHttpUrl()
        val jar = JamarrCookieJar(settingsStore)
        val cookie = Cookie.Builder()
            .name("refresh_token")
            .value("abc")
            .domain("jamarr.example")
            .path("/")
            .expiresAt(System.currentTimeMillis() + 60_000)
            .httpOnly()
            .secure()
            .build()

        jar.saveFromResponse(url, listOf(cookie))
        repeat(20) {
            if (settingsStore.loadCookies().isNotEmpty()) return@repeat
            delay(100)
        }

        val primed = JamarrCookieJar(settingsStore)
        primed.prime()

        assertEquals("abc", primed.loadForRequest("https://jamarr.example/api/me".toHttpUrl()).single().value)
    }

    @Test
    fun filtersSecureCookiesFromHttpRequests() = runTest {
        val jar = JamarrCookieJar(settingsStore)
        val cookie = Cookie.Builder()
            .name("refresh_token")
            .value("secure")
            .domain("jamarr.example")
            .path("/")
            .expiresAt(System.currentTimeMillis() + 60_000)
            .secure()
            .build()

        jar.saveFromResponse("https://jamarr.example/".toHttpUrl(), listOf(cookie))

        assertTrue(jar.loadForRequest("http://jamarr.example/".toHttpUrl()).isEmpty())
        assertEquals("secure", jar.loadForRequest("https://jamarr.example/".toHttpUrl()).single().value)
    }
}
