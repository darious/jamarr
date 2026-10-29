package com.jamarr.android.playback

import androidx.media3.common.Player
import androidx.media3.session.CommandButton
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class MediaButtonPolicyTest {
    private fun state(
        shuffle: Boolean = false,
        repeat: Int = Player.REPEAT_MODE_OFF,
        favourite: Boolean? = null,
        albumKnown: Boolean = true,
        online: Boolean = true,
    ) = MediaButtonPolicy.State(shuffle, repeat, favourite, albumKnown, online)

    @Test
    fun `shuffle and repeat icons follow the player state`() {
        val off = MediaButtonPolicy.buttons(state())
        assertEquals(CommandButton.ICON_SHUFFLE_OFF, off[0].icon)
        assertEquals(CommandButton.ICON_REPEAT_OFF, off[1].icon)

        val on = MediaButtonPolicy.buttons(state(shuffle = true, repeat = Player.REPEAT_MODE_ONE))
        assertEquals(CommandButton.ICON_SHUFFLE_ON, on[0].icon)
        assertEquals(CommandButton.ICON_REPEAT_ONE, on[1].icon)
        assertEquals(CommandButton.ICON_REPEAT_ALL, MediaButtonPolicy.buttons(state(repeat = Player.REPEAT_MODE_ALL))[1].icon)
    }

    @Test
    fun `the favourite button acts on the album and reflects its state`() {
        val unknown = MediaButtonPolicy.buttons(state(favourite = null))
        assertEquals(MediaButtonPolicy.CMD_TOGGLE_FAVOURITE_ALBUM, unknown[2].command)
        assertEquals(CommandButton.ICON_HEART_UNFILLED, unknown[2].icon)
        assertEquals("Favourite album", unknown[2].label)

        val favourite = MediaButtonPolicy.buttons(state(favourite = true))
        assertEquals(CommandButton.ICON_HEART_FILLED, favourite[2].icon)
        assertEquals("Remove album from favourites", favourite[2].label)
    }

    @Test
    fun `no favourite button offline or without an album`() {
        assertNull(MediaButtonPolicy.buttons(state(online = false)).firstOrNull { it.command == MediaButtonPolicy.CMD_TOGGLE_FAVOURITE_ALBUM })
        assertNull(MediaButtonPolicy.buttons(state(albumKnown = false)).firstOrNull { it.command == MediaButtonPolicy.CMD_TOGGLE_FAVOURITE_ALBUM })
        assertEquals(2, MediaButtonPolicy.buttons(state(online = false)).size)
    }

    @Test
    fun `repeat cycles off, all, one`() {
        assertEquals(Player.REPEAT_MODE_ALL, MediaButtonPolicy.nextRepeatMode(Player.REPEAT_MODE_OFF))
        assertEquals(Player.REPEAT_MODE_ONE, MediaButtonPolicy.nextRepeatMode(Player.REPEAT_MODE_ALL))
        assertEquals(Player.REPEAT_MODE_OFF, MediaButtonPolicy.nextRepeatMode(Player.REPEAT_MODE_ONE))
    }
}
