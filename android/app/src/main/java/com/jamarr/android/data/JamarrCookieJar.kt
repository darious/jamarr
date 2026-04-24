package com.jamarr.android.data

import com.jamarr.android.auth.SettingsStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl

class JamarrCookieJar(
    private val settingsStore: SettingsStore,
) : CookieJar {

    @Serializable
    private data class StoredCookie(
        val name: String,
        val value: String,
        val expiresAt: Long,
        val domain: String,
        val path: String,
        val secure: Boolean,
        val httpOnly: Boolean,
        val hostOnly: Boolean,
    )

    private val lock = Any()
    private val store = mutableMapOf<String, MutableList<Cookie>>()
    private val json = Json { ignoreUnknownKeys = true }
    private val persistScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    suspend fun prime() {
        val stored = settingsStore.loadCookies()
        val now = System.currentTimeMillis()
        synchronized(lock) {
            store.clear()
            for (raw in stored) {
                val parsed = runCatching { json.decodeFromString<StoredCookie>(raw) }.getOrNull()
                    ?: continue
                if (parsed.expiresAt <= now) continue
                val builder = Cookie.Builder()
                    .name(parsed.name)
                    .value(parsed.value)
                    .expiresAt(parsed.expiresAt)
                    .path(parsed.path)
                if (parsed.hostOnly) builder.hostOnlyDomain(parsed.domain)
                else builder.domain(parsed.domain)
                if (parsed.secure) builder.secure()
                if (parsed.httpOnly) builder.httpOnly()
                store.getOrPut(parsed.domain) { mutableListOf() }.add(builder.build())
            }
        }
    }

    override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
        if (cookies.isEmpty()) return
        val now = System.currentTimeMillis()
        synchronized(lock) {
            for (incoming in cookies) {
                val bucket = store.getOrPut(incoming.domain) { mutableListOf() }
                bucket.removeAll { it.name == incoming.name && it.path == incoming.path && it.domain == incoming.domain }
                if (incoming.expiresAt > now) bucket.add(incoming)
            }
        }
        persist()
    }

    override fun loadForRequest(url: HttpUrl): List<Cookie> {
        val now = System.currentTimeMillis()
        val host = url.host
        val result = mutableListOf<Cookie>()
        synchronized(lock) {
            for ((domain, list) in store) {
                val matchesHost = if (list.any { it.hostOnly }) {
                    host == domain
                } else {
                    host == domain || host.endsWith(".$domain")
                }
                if (!matchesHost) continue
                for (cookie in list) {
                    if (cookie.expiresAt <= now) continue
                    if (cookie.secure && !url.isHttps) continue
                    if (!pathMatches(url.encodedPath, cookie.path)) continue
                    result.add(cookie)
                }
            }
        }
        return result
    }

    suspend fun clear() {
        synchronized(lock) { store.clear() }
        settingsStore.saveCookies(emptyList())
    }

    private fun pathMatches(requestPath: String, cookiePath: String): Boolean {
        if (cookiePath == "/" || requestPath == cookiePath) return true
        if (!requestPath.startsWith(cookiePath)) return false
        return cookiePath.endsWith("/") || requestPath.getOrNull(cookiePath.length) == '/'
    }

    private fun persist() {
        val snapshot: List<String>
        synchronized(lock) {
            snapshot = store.values.asSequence().flatten().map { c ->
                json.encodeToString(
                    StoredCookie(
                        name = c.name,
                        value = c.value,
                        expiresAt = c.expiresAt,
                        domain = c.domain,
                        path = c.path,
                        secure = c.secure,
                        httpOnly = c.httpOnly,
                        hostOnly = c.hostOnly,
                    )
                )
            }.toList()
        }
        persistScope.launch { settingsStore.saveCookies(snapshot) }
    }
}
