package com.jamarr.android

import android.app.Application
import com.jamarr.android.auth.SettingsStore
import com.jamarr.android.auth.TokenHolder
import com.jamarr.android.data.JamarrCookieJar
import com.jamarr.android.playback.JamarrMediaCache

class JamarrApplication : Application() {
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

    override fun onCreate() {
        super.onCreate()
        instance = this
        val settingsStore = SettingsStore(this)
        tokenHolder = TokenHolder()
        cookieJar = JamarrCookieJar(settingsStore)
    }

    companion object {
        @Volatile
        private var instance: JamarrApplication? = null

        fun get(): JamarrApplication =
            instance ?: throw IllegalStateException("JamarrApplication not initialized")
    }
}
