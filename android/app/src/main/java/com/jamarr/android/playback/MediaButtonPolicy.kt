package com.jamarr.android.playback

import androidx.media3.common.Player
import androidx.media3.session.CommandButton

/**
 * Which extra controls the media session offers, and in what state.
 *
 * Android Auto, the notification and Wear render these from the session's
 * media button preferences; the host decides where (and whether) each one
 * appears, so the list is kept short and in priority order. Pure Kotlin so
 * the state logic is unit-testable; the service turns specs into
 * `CommandButton`s.
 *
 * Favourites follow Jamarr's model: albums and artists can be favourites,
 * tracks cannot, so the one favourite control acts on the playing track's
 * album and only appears when that album is known and the server reachable.
 */
object MediaButtonPolicy {
    const val CMD_TOGGLE_SHUFFLE = "com.jamarr.android.TOGGLE_SHUFFLE"
    const val CMD_CYCLE_REPEAT = "com.jamarr.android.CYCLE_REPEAT"
    const val CMD_TOGGLE_FAVOURITE_ALBUM = "com.jamarr.android.TOGGLE_FAVOURITE_ALBUM"

    val COMMANDS: List<String> = listOf(CMD_TOGGLE_SHUFFLE, CMD_CYCLE_REPEAT, CMD_TOGGLE_FAVOURITE_ALBUM)

    /** `MediaItem` extra carrying the album id a track belongs to, when known. */
    const val EXTRA_ALBUM_MBID = "com.jamarr.android.ALBUM_MBID"

    data class ButtonSpec(
        val command: String,
        /** A `CommandButton.ICON_*` constant. */
        val icon: Int,
        val label: String,
        val enabled: Boolean = true,
    )

    data class State(
        val shuffle: Boolean,
        @Player.RepeatMode val repeatMode: Int,
        /** Null when the album is unknown or the favourite state has not loaded. */
        val favouriteAlbum: Boolean?,
        val albumKnown: Boolean,
        val online: Boolean,
    )

    fun buttons(state: State): List<ButtonSpec> {
        val out = mutableListOf<ButtonSpec>()
        out += ButtonSpec(
            command = CMD_TOGGLE_SHUFFLE,
            icon = if (state.shuffle) CommandButton.ICON_SHUFFLE_ON else CommandButton.ICON_SHUFFLE_OFF,
            label = if (state.shuffle) "Shuffle on" else "Shuffle off",
        )
        out += ButtonSpec(
            command = CMD_CYCLE_REPEAT,
            icon = when (state.repeatMode) {
                Player.REPEAT_MODE_ALL -> CommandButton.ICON_REPEAT_ALL
                Player.REPEAT_MODE_ONE -> CommandButton.ICON_REPEAT_ONE
                else -> CommandButton.ICON_REPEAT_OFF
            },
            label = when (state.repeatMode) {
                Player.REPEAT_MODE_ALL -> "Repeat all"
                Player.REPEAT_MODE_ONE -> "Repeat one"
                else -> "Repeat off"
            },
        )
        // Offline the toggle could only fail; a track with no album has
        // nothing to favourite. Neither case shows a dead button.
        if (state.albumKnown && state.online) {
            out += ButtonSpec(
                command = CMD_TOGGLE_FAVOURITE_ALBUM,
                icon = if (state.favouriteAlbum == true) CommandButton.ICON_HEART_FILLED else CommandButton.ICON_HEART_UNFILLED,
                label = if (state.favouriteAlbum == true) "Remove album from favourites" else "Favourite album",
            )
        }
        return out
    }

    @Player.RepeatMode
    fun nextRepeatMode(@Player.RepeatMode current: Int): Int = when (current) {
        Player.REPEAT_MODE_OFF -> Player.REPEAT_MODE_ALL
        Player.REPEAT_MODE_ALL -> Player.REPEAT_MODE_ONE
        else -> Player.REPEAT_MODE_OFF
    }
}
