package com.jamarr.android.ui.state

import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import com.jamarr.android.data.JamarrApiClient
import com.jamarr.android.playback.JamarrPlaybackController

@Immutable
data class JamarrAppContext(
    val apiClient: JamarrApiClient,
    val playbackController: JamarrPlaybackController,
    val serverUrl: String,
    val accessToken: String,
) {
    fun artworkUrl(artSha1: String?, maxSize: Int = 400): String? =
        apiClient.artworkUrl(serverUrl, artSha1, maxSize)
}

val LocalJamarrContext = staticCompositionLocalOf<JamarrAppContext> {
    error("JamarrAppContext not provided")
}
