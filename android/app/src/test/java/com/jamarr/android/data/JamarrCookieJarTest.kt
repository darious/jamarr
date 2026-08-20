package com.jamarr.android.data

import com.jamarr.android.auth.CookieStore
import kotlinx.coroutines.test.runTest
import okhttp3.Cookie
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class JamarrCookieJarTest {

    private class FakeCookieStore : CookieStore {
        @Volatile var cookies: Set<String> = emptySet()
        override suspend fun loadCookies(): Set<String> = cookies
        override suspend fun saveCookies(cookies: Collection<String>) {
            this.cookies = cookies.toSet()
        }

        /** Persistence is fire-and-forget on an IO scope, so tests wait for it. */
        fun awaitPersisted() {
            val deadline = System.currentTimeMillis() + 2_000
            while (cookies.isEmpty() && System.currentTimeMillis() < deadline) Thread.sleep(10)
        }
    }

    private fun refreshCookie(secure: Boolean): Cookie {
        val flags = if (secure) "; Secure" else ""
        return Cookie.parse(
            "http://192.168.1.107:8111/api/auth/login".toHttpUrl(),
            "jamarr_refresh=tok; Path=/api; HttpOnly; Max-Age=1814400$flags",
        )!!
    }

    @Test
    fun plainCookieOverPlainHttpIsSentBack() = runTest {
        val jar = JamarrCookieJar(FakeCookieStore())
        val login = "http://192.168.1.107:8111/api/auth/login".toHttpUrl()

        jar.saveFromResponse(login, listOf(refreshCookie(secure = false)))

        val sent = jar.loadForRequest("http://192.168.1.107:8111/api/auth/refresh".toHttpUrl())
        assertEquals(listOf("jamarr_refresh"), sent.map { it.name })
    }

    /**
     * The failure behind #272: a Secure cookie issued over plain HTTP is stored
     * but never sent, so every refresh goes out unauthenticated. The server is
     * what stops issuing one; this pins the client behaviour that makes it fatal.
     */
    @Test
    fun secureCookieIsNeverSentOverPlainHttp() = runTest {
        val jar = JamarrCookieJar(FakeCookieStore())
        val login = "http://192.168.1.107:8111/api/auth/login".toHttpUrl()

        jar.saveFromResponse(login, listOf(refreshCookie(secure = true)))

        assertTrue(jar.loadForRequest("http://192.168.1.107:8111/api/auth/refresh".toHttpUrl()).isEmpty())
    }

    @Test
    fun secureCookieOverHttpsKeepsItsFlag() = runTest {
        val jar = JamarrCookieJar(FakeCookieStore())
        val url = "https://jamarr.example/api/auth/login".toHttpUrl()
        val cookie = Cookie.parse(url, "jamarr_refresh=tok; Path=/api; HttpOnly; Secure; Max-Age=1814400")!!

        jar.saveFromResponse(url, listOf(cookie))

        assertTrue(jar.loadForRequest("https://jamarr.example/api/auth/refresh".toHttpUrl()).single().secure)
        assertTrue(jar.loadForRequest("http://jamarr.example/api/auth/refresh".toHttpUrl()).isEmpty())
    }

    @Test
    fun cookieSurvivesAProcessRestart() = runTest {
        val store = FakeCookieStore()
        JamarrCookieJar(store).saveFromResponse(
            "http://192.168.1.107:8111/api/auth/login".toHttpUrl(),
            listOf(refreshCookie(secure = false)),
        )
        store.awaitPersisted()

        val revived = JamarrCookieJar(store)
        revived.prime()

        val sent = revived.loadForRequest("http://192.168.1.107:8111/api/auth/refresh".toHttpUrl())
        assertEquals(listOf("jamarr_refresh"), sent.map { it.name })
    }

    @Test
    fun cookieIsNotSentToOtherPaths() = runTest {
        val jar = JamarrCookieJar(FakeCookieStore())
        jar.saveFromResponse(
            "http://192.168.1.107:8111/api/auth/login".toHttpUrl(),
            listOf(refreshCookie(secure = false)),
        )

        assertTrue(jar.loadForRequest("http://192.168.1.107:8111/health".toHttpUrl()).isEmpty())
        assertTrue(jar.loadForRequest("http://other.host:8111/api/auth/refresh".toHttpUrl()).isEmpty())
    }
}
