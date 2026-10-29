package com.jamarr.android.playback

import androidx.media3.common.AudioAttributes
import androidx.media3.common.C

/**
 * How the local ExoPlayer behaves as an audio citizen on the phone.
 *
 * Kept as plain values so the choices are visible in one place and checkable
 * on the JVM; [JamarrPlaybackService] feeds them to `ExoPlayer.Builder`.
 *
 * - [MUSIC]: `USAGE_MEDIA` + `CONTENT_TYPE_MUSIC`. With focus handling on,
 *   ExoPlayer requests `AUDIOFOCUS_GAIN` for this content, ducks on
 *   `LOSS_TRANSIENT_CAN_DUCK` (navigation prompts), pauses on
 *   `LOSS_TRANSIENT` (a call) and resumes on regain, and stops for good on
 *   permanent `LOSS` (another music app). A pause the user makes during a
 *   transient loss clears `playWhenReady`, so regain never overrides it.
 * - [HANDLE_BECOMING_NOISY]: `ACTION_AUDIO_BECOMING_NOISY` (wired or
 *   Bluetooth output disconnecting) pauses instead of letting the track
 *   continue through the loudspeaker.
 * - [WAKE_MODE]: `WAKE_MODE_NETWORK` holds a partial wake lock and a Wi-Fi
 *   lock only while playing (streams come over the network, and a dozing
 *   Wi-Fi radio stalls them); both are released on pause, stop and release.
 *   Needs `android.permission.WAKE_LOCK`, declared in the manifest.
 *
 * Remote renderers are unaffected: UPnP and Cast playback never goes through
 * this player, so a phone call pausing the phone does not pause the renderer,
 * and the phone taking focus does not claim the renderer's queue.
 */
object PlayerAudioConfig {
    val MUSIC: AudioAttributes = AudioAttributes.Builder()
        .setUsage(C.USAGE_MEDIA)
        .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
        .build()

    const val HANDLE_AUDIO_FOCUS = true
    const val HANDLE_BECOMING_NOISY = true

    @C.WakeMode
    const val WAKE_MODE = C.WAKE_MODE_NETWORK
}
