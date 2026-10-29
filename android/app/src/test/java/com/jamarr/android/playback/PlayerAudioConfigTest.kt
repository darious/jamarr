package com.jamarr.android.playback

import androidx.media3.common.C
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PlayerAudioConfigTest {
    @Test
    fun `plays as music media so focus and ducking follow the music rules`() {
        assertEquals(C.USAGE_MEDIA, PlayerAudioConfig.MUSIC.usage)
        assertEquals(C.AUDIO_CONTENT_TYPE_MUSIC, PlayerAudioConfig.MUSIC.contentType)
    }

    @Test
    fun `focus, becoming-noisy and a network wake mode are all on`() {
        assertTrue(PlayerAudioConfig.HANDLE_AUDIO_FOCUS)
        assertTrue(PlayerAudioConfig.HANDLE_BECOMING_NOISY)
        assertEquals(C.WAKE_MODE_NETWORK, PlayerAudioConfig.WAKE_MODE)
    }
}
