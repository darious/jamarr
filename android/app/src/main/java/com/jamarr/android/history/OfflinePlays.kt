package com.jamarr.android.history

import android.content.Context
import android.util.Log
import com.jamarr.android.JamarrApplication
import com.jamarr.android.auth.SettingsStore
import com.jamarr.android.data.JamarrApiClient
import com.jamarr.android.data.OfflinePlayUpload
import java.time.Instant
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Plays made offline: written down as they happen, uploaded to
 * `POST /api/history/offline` once the server is reachable again.
 *
 * Uploads happen on app start (when online) and on every reconnect. A batch
 * is deleted locally only after the server answers, and the server ignores a
 * play it already holds, so a lost response just means the batch is sent
 * again — never a lost or doubled play.
 */
class OfflinePlays(context: Context) {
    private val appContext = context.applicationContext
    private val app = appContext as JamarrApplication
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val settingsStore = SettingsStore(appContext)
    private val uploadLock = Mutex()
    private val dao = OfflinePlayDatabase.build(appContext).pendingPlayDao()

    private val apiClient = JamarrApiClient(
        tokenHolder = app.tokenHolder,
        cookieJar = app.cookieJar,
        onTokenRefreshed = { token -> settingsStore.saveAccessToken(token) },
        onRefreshFailed = { settingsStore.clearAccessToken() },
        onForceLogout = {
            settingsStore.clearAccessToken()
            app.cookieJar.clear()
        },
    )

    init {
        scope.launch {
            if (!app.connectivity.state.value.isOffline) upload()
            app.connectivity.reconnected.collect { upload() }
        }
    }

    fun record(event: OfflinePlayEvent) {
        scope.launch {
            dao.insert(
                PendingPlayEntity(
                    trackId = event.trackId,
                    playedAtMs = event.startedAtMs,
                    msPlayed = event.playedMs,
                ),
            )
        }
    }

    /** Sends everything pending, oldest first, stopping at the first failure. */
    suspend fun upload() = uploadLock.withLock {
        val session = settingsStore.load()
        if (app.tokenHolder.get().isBlank()) app.tokenHolder.set(session.accessToken)
        if (session.serverUrl.isBlank() || app.tokenHolder.get().isBlank()) return@withLock
        app.cookieJar.prime()
        val clientId = settingsStore.getClientId()
        while (true) {
            val batch = dao.oldest(BATCH_SIZE)
            if (batch.isEmpty()) return@withLock
            val result = runCatching {
                apiClient.uploadOfflinePlays(
                    serverUrl = session.serverUrl,
                    clientId = clientId,
                    plays = batch.map {
                        OfflinePlayUpload(
                            trackId = it.trackId,
                            playedAt = Instant.ofEpochMilli(it.playedAtMs).toString(),
                            msPlayed = it.msPlayed,
                        )
                    },
                )
            }.onFailure { Log.w(TAG, "Offline play upload failed", it) }.getOrNull()
                ?: return@withLock
            Log.i(TAG, "Uploaded offline plays: $result")
            dao.delete(batch.map { it.id })
        }
    }

    companion object {
        private const val TAG = "OfflinePlays"
        private const val BATCH_SIZE = 500
    }
}
