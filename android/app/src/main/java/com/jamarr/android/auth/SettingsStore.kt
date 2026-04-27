package com.jamarr.android.auth

import android.content.Context
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
)

class SettingsStore(private val context: Context) {
    private val serverUrlKey = stringPreferencesKey("server_url")
    private val accessTokenKey = stringPreferencesKey("access_token")
    private val activeTabKey = intPreferencesKey("active_tab")
    private val cookiesKey = stringSetPreferencesKey("cookies_v1")
    private val clientIdKey = stringPreferencesKey("client_id")

    suspend fun load(): StoredSession {
        val prefs = context.jamarrDataStore.data.first()
        return StoredSession(
            serverUrl = prefs[serverUrlKey].orEmpty(),
            accessToken = prefs[accessTokenKey].orEmpty(),
            activeTabIndex = prefs[activeTabKey] ?: 0,
        )
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

    suspend fun loadCookies(): Set<String> {
        return context.jamarrDataStore.data.first()[cookiesKey].orEmpty()
    }

    suspend fun saveCookies(cookies: Collection<String>) {
        context.jamarrDataStore.edit { prefs ->
            if (cookies.isEmpty()) prefs.remove(cookiesKey)
            else prefs[cookiesKey] = cookies.toSet()
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
