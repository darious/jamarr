package com.jamarr.android.playback

import android.app.PendingIntent
import android.content.Intent
import android.net.Uri
import androidx.annotation.OptIn
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.Timeline
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.datasource.ResolvingDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.MediaLibraryService
import androidx.media3.session.MediaSession
import com.jamarr.android.MainActivity
import com.jamarr.android.auth.SettingsStore
import com.jamarr.android.auth.TokenHolder
import com.jamarr.android.data.JamarrApiClient
import com.jamarr.android.data.JamarrCookieJar
import com.jamarr.android.data.SearchTrack
import java.io.IOException
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking

@OptIn(markerClass = [UnstableApi::class])
class JamarrPlaybackService : MediaLibraryService() {
    private var librarySession: MediaLibrarySession? = null

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val serverUrl = AtomicReference("")
    private lateinit var settingsStore: SettingsStore
    private lateinit var tokenHolder: TokenHolder
    private lateinit var apiClient: JamarrApiClient
    private lateinit var libraryProvider: JamarrLibraryProvider

    override fun onCreate() {
        super.onCreate()

        settingsStore = SettingsStore(applicationContext)
        tokenHolder = TokenHolder()
        val cookieJar = JamarrCookieJar(settingsStore)
        apiClient = JamarrApiClient(
            tokenHolder = tokenHolder,
            cookieJar = cookieJar,
            onTokenRefreshed = { token -> settingsStore.saveAccessToken(token) },
            onRefreshFailed = { settingsStore.clearAccessToken() },
        )

        runBlocking {
            val saved = settingsStore.load()
            serverUrl.set(saved.serverUrl)
            tokenHolder.set(saved.accessToken)
            cookieJar.prime()
        }

        serviceScope.launch {
            settingsStore.observeSession().collectLatest { session ->
                serverUrl.set(session.serverUrl)
                tokenHolder.set(session.accessToken)
            }
        }

        val httpFactory = DefaultHttpDataSource.Factory()
        val resolvingFactory = ResolvingDataSource.Factory(httpFactory) { spec ->
            resolveDataSpec(spec)
        }
        val mediaSourceFactory = DefaultMediaSourceFactory(this)
            .setDataSourceFactory(resolvingFactory)

        val player = ExoPlayer.Builder(this)
            .setMediaSourceFactory(mediaSourceFactory)
            .build()

        val sessionIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

        libraryProvider = JamarrLibraryProvider(
            apiClient = apiClient,
            serverUrlProvider = { serverUrl.get() },
            tokenProvider = { tokenHolder.get() },
            scope = serviceScope,
        )

        librarySession = MediaLibrarySession.Builder(this, player, libraryProvider.callback)
            .setSessionActivity(sessionIntent)
            .build()
    }

    private fun resolveDataSpec(spec: DataSpec): DataSpec {
        val uri = spec.uri
        if (uri.scheme != JAMARR_SCHEME) return spec
        val trackId = uri.lastPathSegment?.toLongOrNull()
            ?: throw IOException("Missing track id in $uri")
        val server = serverUrl.get()
        if (server.isBlank()) throw IOException("Jamarr server URL not set")
        val resolved = runBlocking {
            apiClient.streamUrl(server, tokenHolder.get(), trackId)
        }
        return spec.withUri(Uri.parse(resolved))
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaLibrarySession? {
        return librarySession
    }

    override fun onDestroy() {
        librarySession?.run {
            player.release()
            release()
        }
        librarySession = null
        serviceScope.cancel()
        super.onDestroy()
    }

    companion object {
        const val JAMARR_SCHEME = "jamarr"

        fun trackUri(trackId: Long): Uri =
            Uri.parse("$JAMARR_SCHEME://track/$trackId")
    }
}
