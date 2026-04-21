package com.jamarr.android.auth

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.first

private val Context.jamarrDataStore by preferencesDataStore(name = "jamarr_settings")

data class StoredSession(
    val serverUrl: String = "",
    val accessToken: String = "",
)

class SettingsStore(private val context: Context) {
    private val serverUrlKey = stringPreferencesKey("server_url")
    private val accessTokenKey = stringPreferencesKey("access_token")

    suspend fun load(): StoredSession {
        val prefs = context.jamarrDataStore.data.first()
        return StoredSession(
            serverUrl = prefs[serverUrlKey].orEmpty(),
            accessToken = prefs[accessTokenKey].orEmpty(),
        )
    }

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
}
