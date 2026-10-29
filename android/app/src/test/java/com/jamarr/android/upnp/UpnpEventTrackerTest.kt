package com.jamarr.android.upnp

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UpnpEventTrackerTest {

    private var now = 1_000_000L
    private val tracker = UpnpEventTracker { now }

    private val uriA = "http://192.0.2.2:8112/api/stream/900?token=aaa&x=1"
    private val uriB = "http://192.0.2.2:8112/api/stream/901?token=bbb"

    private fun avtLastChange(vararg values: Pair<String, String>): String =
        "<Event xmlns=\"urn:schemas-upnp-org:metadata-1-0/AVT/\"><InstanceID val=\"0\">" +
            values.joinToString("") { (k, v) -> "<$k val=\"${v.replace("&", "&amp;")}\"/>" } +
            "</InstanceID></Event>"

    private fun healthy() {
        tracker.onEstablished(AV_TRANSPORT)
        tracker.onEvent(
            AV_TRANSPORT,
            LastChangeParser.parse(avtLastChange("TransportState" to "PLAYING", "CurrentTrackURI" to uriA)),
        )
    }

    @Test
    fun parsesInstanceZeroMasterChannelAndEntities() {
        val xml = "<Event xmlns=\"urn:schemas-upnp-org:metadata-1-0/RCS/\">" +
            "<InstanceID val=\"1\"><Volume channel=\"Master\" val=\"99\"/></InstanceID>" +
            "<InstanceID val=\"0\"><Volume channel=\"LF\" val=\"5\"/><Volume channel=\"Master\" val=\"30\"/>" +
            "<Mute channel='Master' val='1'/><rcs:PresetNameList val=\"FactoryDefaults\"/>" +
            "<AVTransportURI val=\"http://h/s?a=1&amp;b=&amp;lt;\"/></InstanceID></Event>"
        val values = LastChangeParser.parse(xml)
        assertEquals("30", values["Volume"])
        assertEquals("1", values["Mute"])
        assertEquals("FactoryDefaults", values["PresetNameList"])
        assertEquals("http://h/s?a=1&b=&lt;", values["AVTransportURI"]) // one decoding pass
        assertTrue(LastChangeParser.parse(null).isEmpty())
        assertTrue(LastChangeParser.parse("not xml").isEmpty())
    }

    @Test
    fun healthyOnlyAfterEstablishedAndInitialEvent() {
        assertFalse(tracker.avt.healthy)
        assertEquals(UpnpEventTracker.POLL_INTERVAL_MS, tracker.pollIntervalMs())
        tracker.onEstablished(AV_TRANSPORT)
        assertFalse(tracker.avt.healthy)
        tracker.onEvent(AV_TRANSPORT, mapOf("TransportState" to "PLAYING"))
        assertTrue(tracker.avt.healthy)
        assertEquals(UpnpEventTracker.EVENT_POLL_INTERVAL_MS, tracker.pollIntervalMs())
    }

    @Test
    fun initialEventBeforeEstablishedCallbackStillCounts() {
        tracker.onEvent(AV_TRANSPORT, mapOf("TransportState" to "STOPPED"))
        tracker.onEstablished(AV_TRANSPORT)
        assertTrue(tracker.avt.healthy)
    }

    @Test
    fun transportAndTrackUriChangesBumpGeneration() {
        healthy()
        assertEquals("PLAYING", tracker.transportState)
        assertEquals(uriA, tracker.trackUri)
        val gen = tracker.generation
        assertFalse(tracker.onEvent(AV_TRANSPORT, mapOf("TransportState" to "PLAYING")))
        assertTrue(tracker.onEvent(AV_TRANSPORT, mapOf("CurrentTrackURI" to uriB)))
        assertEquals(uriB, tracker.trackUri)
        assertEquals(gen + 1, tracker.generation)
        assertTrue(tracker.onEvent(AV_TRANSPORT, mapOf("TransportState" to "PAUSED_PLAYBACK")))
        assertEquals("PAUSED_PLAYBACK", tracker.transportState)
    }

    @Test
    fun remoteVolumeAndMuteAreScaled() {
        tracker.onEstablished(RENDERING_CONTROL)
        tracker.onEvent(RENDERING_CONTROL, mapOf("Volume" to "25", "Mute" to "0"), maxVolume = 50)
        assertEquals(50, tracker.volumePercent)
        assertEquals(false, tracker.muted)
        assertTrue(tracker.rc.healthy)
        tracker.onEvent(RENDERING_CONTROL, mapOf("Mute" to "true"))
        assertEquals(true, tracker.muted)
    }

    @Test
    fun lostSubscriptionFallsBackUntilAFreshInitialEvent() {
        healthy()
        tracker.onLost(AV_TRANSPORT, "RENEWAL_FAILED", failure = true)
        assertFalse(tracker.avt.healthy)
        assertEquals(1, tracker.avt.failures)
        assertEquals(UpnpEventTracker.POLL_INTERVAL_MS, tracker.pollIntervalMs())
        tracker.onEstablished(AV_TRANSPORT)
        assertFalse(tracker.avt.healthy)
        assertEquals(0, tracker.avt.failures)
        tracker.onEvent(AV_TRANSPORT, mapOf("TransportState" to "PLAYING"))
        assertTrue(tracker.avt.healthy)
    }

    @Test
    fun watchdogMismatchesMarkEventsUnreliable() {
        healthy()
        // A poll racing a fresh event is not evidence of a missed one.
        assertFalse(tracker.notePoll("STOPPED", uriA))
        now += 5_000
        assertFalse(tracker.notePoll("TRANSITIONING", uriA)) // ~PLAYING
        assertTrue(tracker.notePoll("STOPPED", uriA))
        assertEquals("STOPPED", tracker.transportState) // polled value adopted
        assertTrue(tracker.avt.healthy)
        assertFalse(tracker.notePoll("STOPPED", uriA)) // agreement resets
        assertTrue(tracker.notePoll("STOPPED", uriB))
        assertTrue(tracker.notePoll("PLAYING", uriB))
        assertTrue(tracker.avt.unreliable)
        assertFalse(tracker.avt.healthy)
        // A fresh subscription clears it.
        tracker.onLost(AV_TRANSPORT, "re-subscribing", failure = false)
        tracker.onEstablished(AV_TRANSPORT)
        tracker.onEvent(AV_TRANSPORT, mapOf("TransportState" to "PLAYING"))
        assertTrue(tracker.avt.healthy)
    }

    @Test
    fun sameUriIgnoresEscaping() {
        healthy()
        now += 5_000
        assertFalse(tracker.notePoll("PLAYING", uriA.replace("&", "&amp;")))
    }

    @Test
    fun clearForgetsEverything() {
        healthy()
        tracker.onEstablished(RENDERING_CONTROL)
        tracker.onEvent(RENDERING_CONTROL, mapOf("Volume" to "40"))
        tracker.clear()
        assertFalse(tracker.avt.healthy)
        assertFalse(tracker.rc.healthy)
        assertNull(tracker.transportState)
        assertNull(tracker.trackUri)
        assertNull(tracker.volumePercent)
    }
}
