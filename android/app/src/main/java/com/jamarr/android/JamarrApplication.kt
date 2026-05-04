package com.jamarr.android

import android.app.Application
import com.jamarr.android.auth.SettingsStore
import com.jamarr.android.auth.TokenHolder
import com.jamarr.android.data.JamarrCookieJar

class JamarrApplication : Application() {
    lateinit var tokenHolder: TokenHolder
        private set
    lateinit var cookieJar: JamarrCookieJar
        private set

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
