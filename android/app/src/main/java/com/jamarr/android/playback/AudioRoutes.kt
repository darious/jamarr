package com.jamarr.android.playback

import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build

/**
 * Names the output the platform routes music to — for diagnostics only.
 *
 * API 33+ asks the platform directly for the media route. Earlier releases
 * expose no "current output" query, so the attached outputs are ranked the
 * way the audio policy prefers them (Bluetooth, USB, wired, HDMI, speaker);
 * that heuristic is labelled as such in the returned text.
 */
object AudioRoutes {
    data class Route(val label: String, val type: Int, val exact: Boolean)

    fun describe(audioManager: AudioManager?): Route? {
        if (audioManager == null) return null
        if (Build.VERSION.SDK_INT >= 33) {
            val attrs = AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                .build()
            val routed = runCatching { audioManager.getAudioDevicesForAttributes(attrs) }.getOrNull()
            routed?.firstOrNull()?.let { return Route(label(it), it.type, exact = true) }
        }
        val outputs = runCatching { audioManager.getDevices(AudioManager.GET_DEVICES_OUTPUTS) }
            .getOrNull().orEmpty()
        val best = outputs.minByOrNull { rank(it.type) } ?: return null
        return Route(label(best), best.type, exact = false)
    }

    /** Lower ranks win: the order the platform's default policy picks outputs in. */
    fun rank(type: Int): Int = when (type) {
        AudioDeviceInfo.TYPE_BLUETOOTH_A2DP -> 0
        AudioDeviceInfo.TYPE_USB_HEADSET, AudioDeviceInfo.TYPE_USB_DEVICE, AudioDeviceInfo.TYPE_USB_ACCESSORY -> 1
        AudioDeviceInfo.TYPE_WIRED_HEADPHONES, AudioDeviceInfo.TYPE_WIRED_HEADSET, AudioDeviceInfo.TYPE_LINE_ANALOG -> 2
        AudioDeviceInfo.TYPE_HDMI, AudioDeviceInfo.TYPE_HDMI_ARC, AudioDeviceInfo.TYPE_LINE_DIGITAL -> 3
        AudioDeviceInfo.TYPE_BLUETOOTH_SCO -> 4
        AudioDeviceInfo.TYPE_BUILTIN_SPEAKER -> 5
        AudioDeviceInfo.TYPE_BUILTIN_EARPIECE -> 6
        else -> 9
    }

    fun label(device: AudioDeviceInfo): String {
        val kind = when (device.type) {
            AudioDeviceInfo.TYPE_BLUETOOTH_A2DP -> "Bluetooth"
            AudioDeviceInfo.TYPE_BLUETOOTH_SCO -> "Bluetooth (call audio)"
            AudioDeviceInfo.TYPE_USB_HEADSET, AudioDeviceInfo.TYPE_USB_DEVICE, AudioDeviceInfo.TYPE_USB_ACCESSORY -> "USB"
            AudioDeviceInfo.TYPE_WIRED_HEADPHONES, AudioDeviceInfo.TYPE_WIRED_HEADSET -> "Wired"
            AudioDeviceInfo.TYPE_LINE_ANALOG -> "Line out"
            AudioDeviceInfo.TYPE_LINE_DIGITAL -> "Digital out"
            AudioDeviceInfo.TYPE_HDMI, AudioDeviceInfo.TYPE_HDMI_ARC -> "HDMI"
            AudioDeviceInfo.TYPE_BUILTIN_SPEAKER -> "Speaker"
            AudioDeviceInfo.TYPE_BUILTIN_EARPIECE -> "Earpiece"
            AudioDeviceInfo.TYPE_TELEPHONY -> "Telephony"
            AudioDeviceInfo.TYPE_REMOTE_SUBMIX -> "Remote submix"
            else -> "Output ${device.type}"
        }
        val name = device.productName?.toString()?.trim().orEmpty()
        return if (name.isNotBlank() && !name.equals(Build.MODEL, ignoreCase = true)) "$kind · $name" else kind
    }
}
