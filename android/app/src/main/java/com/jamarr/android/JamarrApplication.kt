package com.jamarr.android

import android.app.Application
import coil3.ImageLoader
import coil3.PlatformContext
import coil3.SingletonImageLoader
import com.jamarr.android.auth.SettingsStore
import com.jamarr.android.auth.TokenHolder
import com.jamarr.android.data.ConnectivityMonitor
import com.jamarr.android.data.JamarrApiClient
import com.jamarr.android.data.JamarrCookieJar
import com.jamarr.android.download.JamarrDownloads
import com.jamarr.android.download.OfflineArtworkInterceptor
import com.jamarr.android.download.OfflineArtworkStore
import com.jamarr.android.history.OfflinePlays
import com.jamarr.android.playback.JamarrMediaCache
import java.io.File

class JamarrApplication : Application(), SingletonImageLoader.Factory {
    lateinit var tokenHolder: TokenHolder
        private set
    lateinit var cookieJar: JamarrCookieJar
        private set

    /**
     * `SimpleCache` allows a single instance per directory per process, so the
     * caches are created once here and shared. Lazy so the disk index is only
     * opened by processes that actually play something.
     */
    val mediaCache: JamarrMediaCache by lazy { JamarrMediaCache(this) }

    /** Download engine and its metadata store; see `JamarrDownloads`. */
    val downloads: JamarrDownloads by lazy { JamarrDownloads(this) }

    /** Cover art for downloads, served to Coil ahead of the network. */
    val artworkStore: OfflineArtworkStore by lazy { OfflineArtworkStore(File(filesDir, "art")) }

    /** Plays made offline, held until the server can take them. */
    val offlinePlays: OfflinePlays by lazy { OfflinePlays(this) }

    /** Online/offline state, shared by the UI and the download sync. */
    val connectivity: ConnectivityMonitor by lazy {
        // Unauthenticated: the probe only ever calls /api/health.
        val probeClient = JamarrApiClient()
        ConnectivityMonitor(this, SettingsStore(this)) { url -> probeClient.isServerReachable(url) }
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
        val settingsStore = SettingsStore(this)
        tokenHolder = TokenHolder()
        cookieJar = JamarrCookieJar(settingsStore)
    }

    override fun newImageLoader(context: PlatformContext): ImageLoader =
        ImageLoader.Builder(context)
            .components { add(OfflineArtworkInterceptor(artworkStore)) }
            .build()

    companion object {
        @Volatile
        private var instance: JamarrApplication? = null

        fun get(): JamarrApplication =
            instance ?: throw IllegalStateException("JamarrApplication not initialized")
    }
}
