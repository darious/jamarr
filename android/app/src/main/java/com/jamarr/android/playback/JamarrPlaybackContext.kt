package com.jamarr.android.playback

import com.jamarr.android.data.JamarrApiClient

object JamarrPlaybackContext {
    @Volatile
    var serverUrl: String = ""

    @Volatile
    var apiClient: JamarrApiClient? = null
}
