package com.jamarr.android.playback

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ControllerAccessTest {

    private val self = "com.jamarr.android"
    private val selfUid = 10123

    private fun caller(
        packageName: String,
        uid: Int = 10999,
        trusted: Boolean = false,
        verified: Boolean = true,
    ) = ControllerAccess.Caller(packageName, uid, trusted, verified)

    private fun allowed(caller: ControllerAccess.Caller) =
        ControllerAccess.isAllowed(caller, self, selfUid)

    @Test
    fun `our own app connects`() {
        assertTrue(allowed(caller(self, uid = selfUid)))
        // Same uid, different package name (shared uid): still us.
        assertTrue(allowed(caller("com.jamarr.android.debug", uid = selfUid)))
    }

    @Test
    fun `android auto and assistant connect`() {
        assertTrue(allowed(caller("com.google.android.projection.gearhead")))
        assertTrue(allowed(caller("com.google.android.carassistant")))
        assertTrue(allowed(caller("com.google.android.googlequicksearchbox")))
    }

    @Test
    fun `system media controls connect`() {
        assertTrue(allowed(caller("com.android.systemui", uid = 1000)))
        assertTrue(allowed(caller("com.android.bluetooth", uid = 1002)))
    }

    @Test
    fun `a platform-trusted controller connects whatever it is called`() {
        // Notification listeners and the media button dispatcher arrive this way.
        assertTrue(allowed(caller("com.example.assistant", trusted = true)))
    }

    @Test
    fun `an unknown app is rejected`() {
        // The service is exported, so without this any installed app could
        // browse the library and drive playback.
        assertFalse(allowed(caller("com.example.snooper")))
        assertFalse(allowed(caller("com.example.snooper", verified = true)))
    }

    @Test
    fun `an unverified package name cannot borrow the allowlist`() {
        assertFalse(allowed(caller("com.google.android.projection.gearhead", verified = false)))
    }

    @Test
    fun `legacy controllers with no resolvable package are allowed`() {
        // Below API 28 the platform does not tell us who called; rejecting the
        // sentinel would break media buttons on those devices.
        assertTrue(allowed(caller(ControllerAccess.LEGACY_UNKNOWN_PACKAGE, verified = false)))
    }
}
