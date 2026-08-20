package com.jamarr.android.auth

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.core.stringSetPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.jamarrDataStore by preferencesDataStore(name = "jamarr_settings")

data class StoredSession(
    val serverUrl: String = "",
    val accessToken: String = "",
    val activeTabIndex: Int = 0,
    val useDeviceUpnp: Boolean = false,
)

/** The slice of persistence [com.jamarr.android.data.JamarrCookieJar] needs, so it can be unit-tested without a Context. */
interface CookieStore {
    suspend fun loadCookies(): Set<String>
    suspend fun saveCookies(cookies: Collection<String>)
}

class SettingsStore(private val context: Context) : CookieStore {
    private val serverUrlKey = stringPreferencesKey("server_url")
    private val accessTokenKey = stringPreferencesKey("access_token")
    private val activeTabKey = intPreferencesKey("active_tab")
    private val cookiesKey = stringSetPreferencesKey("cookies_v1")
    private val clientIdKey = stringPreferencesKey("client_id")
    private val useDeviceUpnpKey = booleanPreferencesKey("use_device_upnp")
    private val resumeQueueKey = stringPreferencesKey("resume_queue_v1")

    // Gates background network use (read-ahead now, downloads later) to
    // unmetered networks. Off by default: read-ahead only pulls the track that
    // is about to play anyway, so it costs no more data than playing on.
    private val wifiOnlyKey = booleanPreferencesKey("wifi_only_transfers")

    suspend fun load(): StoredSession {
        val prefs = context.jamarrDataStore.data.first()
        return StoredSession(
            serverUrl = prefs[serverUrlKey].orEmpty(),
            accessToken = prefs[accessTokenKey].orEmpty(),
            activeTabIndex = prefs[activeTabKey] ?: 0,
            useDeviceUpnp = prefs[useDeviceUpnpKey] ?: false,
        )
    }

    suspend fun saveUseDeviceUpnp(enabled: Boolean) {
        context.jamarrDataStore.edit { prefs -> prefs[useDeviceUpnpKey] = enabled }
    }

    fun observeWifiOnlyTransfers(): Flow<Boolean> = context.jamarrDataStore.data
        .map { prefs -> prefs[wifiOnlyKey] ?: false }
        .distinctUntilChanged()

    suspend fun saveWifiOnlyTransfers(enabled: Boolean) {
        context.jamarrDataStore.edit { prefs -> prefs[wifiOnlyKey] = enabled }
    }

    fun observeSession(): Flow<StoredSession> = context.jamarrDataStore.data
        .map { prefs ->
            StoredSession(
                serverUrl = prefs[serverUrlKey].orEmpty(),
                accessToken = prefs[accessTokenKey].orEmpty(),
                activeTabIndex = prefs[activeTabKey] ?: 0,
            )
        }
        .distinctUntilChanged()

    suspend fun saveServerUrl(serverUrl: String) {
        context.jamarrDataStore.edit { prefs ->
            prefs[serverUrlKey] = serverUrl.trim()
        }
    }

    suspend fun saveAccessToken(accessToken: String) {
        context.jamarrDataStore.edit { prefs ->
            prefs[accessTokenKey] = accessToken
        }
    }

    suspend fun clearAccessToken() {
        context.jamarrDataStore.edit { prefs ->
            prefs.remove(accessTokenKey)
        }
    }

    suspend fun saveActiveTab(index: Int) {
        context.jamarrDataStore.edit { prefs ->
            prefs[activeTabKey] = index
        }
    }

    override suspend fun loadCookies(): Set<String> {
        return context.jamarrDataStore.data.first()[cookiesKey].orEmpty()
    }

    override suspend fun saveCookies(cookies: Collection<String>) {
        context.jamarrDataStore.edit { prefs ->
            if (cookies.isEmpty()) prefs.remove(cookiesKey)
            else prefs[cookiesKey] = cookies.toSet()
        }
    }

    /**
     * The last queue, so the car can resume it.
     *
     * Playback resumption runs before any controller has set a queue, so the
     * only thing available at that point is what was written down here.
     */
    suspend fun loadResumeQueue(): String? =
        context.jamarrDataStore.data.first()[resumeQueueKey]

    suspend fun saveResumeQueue(encoded: String?) {
        context.jamarrDataStore.edit { prefs ->
            if (encoded.isNullOrBlank()) prefs.remove(resumeQueueKey)
            else prefs[resumeQueueKey] = encoded
        }
    }

    suspend fun getClientId(): String {
        val prefs = context.jamarrDataStore.data.first()
        val existing = prefs[clientIdKey]
        if (!existing.isNullOrBlank()) return existing
        val newId = UUID.randomUUID().toString()
        context.jamarrDataStore.edit { it[clientIdKey] = newId }
        return newId
    }
}
