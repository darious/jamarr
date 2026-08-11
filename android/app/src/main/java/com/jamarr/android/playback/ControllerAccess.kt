package com.jamarr.android.playback

/**
 * Who may bind to the media session.
 *
 * The service is exported (it has to be — the car host, Assistant and the
 * system media controls all live in other processes), and media3 accepts every
 * connection by default. That would let any installed app browse the whole
 * library and drive playback, so connections are filtered here instead.
 *
 * Kept free of Android types for unit testing; [JamarrPlaybackService] feeds it
 * the values from `MediaSession.ControllerInfo`.
 */
object ControllerAccess {

    /**
     * Media browsers we expect to see. Package names are unique per device, so
     * an allowlist is meaningful on its own — but it is only honoured when the
     * platform verified the caller really owns the name it claims.
     */
    val ALLOWED_PACKAGES: Set<String> = setOf(
        "com.google.android.projection.gearhead", // Android Auto
        "com.google.android.gms", // Play services (Auto/Assistant plumbing)
        "com.google.android.googlequicksearchbox", // Assistant
        "com.google.android.carassistant", // Assistant in the car
        "com.google.android.autosimulator", // Desktop Head Unit
        "com.google.android.wearable.app", // Wear companion
        "com.android.bluetooth", // Bluetooth AVRCP controls
        "com.android.systemui", // System media controls
        "android",
    )

    /**
     * Legacy controllers below API 28 arrive without a resolvable package name;
     * media3 substitutes this sentinel. Rejecting it would break media button
     * handling on those devices, so it is allowed and logged by the caller.
     */
    const val LEGACY_UNKNOWN_PACKAGE = "android.media.session.MediaController"

    data class Caller(
        val packageName: String,
        val uid: Int,
        /** `ControllerInfo.isTrusted()` — system-level media control permission. */
        val trusted: Boolean,
        /** `ControllerInfo.isPackageNameVerified()` — platform confirmed the name. */
        val packageNameVerified: Boolean,
    )

    fun isAllowed(caller: Caller, selfPackage: String, selfUid: Int): Boolean = when {
        caller.uid == selfUid -> true
        caller.packageName == selfPackage -> true
        // Notification listeners, the system media session stack, media buttons.
        caller.trusted -> true
        caller.packageName == LEGACY_UNKNOWN_PACKAGE -> true
        caller.packageName in ALLOWED_PACKAGES -> caller.packageNameVerified
        else -> false
    }
}
