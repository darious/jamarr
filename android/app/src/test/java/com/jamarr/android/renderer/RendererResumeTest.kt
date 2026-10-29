package com.jamarr.android.renderer

import java.util.Base64
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RendererResumeTest {
    private val now = 1_700_000_000_000L
    private val snapshot = RendererResumeSnapshot(
        rendererId = "upnp:uuid:naim-1",
        rendererName = "Living room",
        tracks = listOf(
            RendererResumeTrack(11, "One", "A", "Album", 200.0),
            RendererResumeTrack(12, "Two", "A", "Album", 210.0),
            RendererResumeTrack(13, "Three", "A", "Album", 220.0),
        ),
        currentIndex = 1,
        positionSeconds = 42.5,
        isPlaying = true,
        savedAtMs = now - 60_000L,
        serverUrl = "http://192.168.1.107:8111",
        subject = "3",
    )

    @Test
    fun `a snapshot round-trips and tolerates corruption`() {
        assertEquals(snapshot, RendererResumeSnapshot.decode(RendererResumeSnapshot.encode(snapshot)))
        assertNull(RendererResumeSnapshot.decode(null))
        assertNull(RendererResumeSnapshot.decode("{nope"))
        assertNull(RendererResumeSnapshot.decode(RendererResumeSnapshot.encode(snapshot.copy(tracks = emptyList()))))
        val clamped = RendererResumeSnapshot.decode(RendererResumeSnapshot.encode(snapshot.copy(currentIndex = 9, positionSeconds = -1.0)))
        assertEquals(2, clamped?.currentIndex)
        assertEquals(0.0, clamped?.positionSeconds)
        // No stream URL is ever stored.
        assertTrue(!RendererResumeSnapshot.encode(snapshot).contains("token"))
    }

    @Test
    fun `validation drops stale, other-server and other-account snapshots`() {
        val subject = "3"
        assertNotNull(RendererResumePolicy.validate(snapshot, now, "http://192.168.1.107:8111/", subject))
        assertNull(RendererResumePolicy.validate(snapshot.copy(savedAtMs = now - RendererResumePolicy.MAX_AGE_MS - 1), now, snapshot.serverUrl, subject))
        assertNull(RendererResumePolicy.validate(snapshot, now, "https://jamarr.example.com", subject))
        assertNull(RendererResumePolicy.validate(snapshot, now, snapshot.serverUrl, "7"))
        // An unknown subject on either side cannot prove a mismatch.
        assertNotNull(RendererResumePolicy.validate(snapshot.copy(subject = null), now, snapshot.serverUrl, subject))
        assertNull(RendererResumePolicy.validate(null, now, snapshot.serverUrl, subject))
    }

    @Test
    fun `stream uris are recognised by track id, whatever host and token`() {
        assertEquals(12L, RendererResumePolicy.trackIdOf("http://192.168.1.107:8112/api/stream/12?token=abc"))
        assertEquals(12L, RendererResumePolicy.trackIdOf("http%3A%2F%2Fh%2Fapi%2Fstream%2F12%3Ftoken%3Dx"))
        assertNull(RendererResumePolicy.trackIdOf("http://radio.example/stream.mp3"))
        assertNull(RendererResumePolicy.trackIdOf(null))
    }

    @Test
    fun `a renderer still on our track offers take-control at its live position`() {
        val live = LiveTransport.Known("http://h:8112/api/stream/12?token=new", "PLAYING", 61.0)
        val offer = RendererResumePolicy.offer(snapshot, live) as ResumeOffer.TakeControl
        assertEquals(1, offer.snapshot.currentIndex)
        assertEquals(61.0, offer.positionSeconds, 0.0)
        assertTrue(offer.playing)
        val paused = RendererResumePolicy.offer(snapshot, live.copy(transportState = "PAUSED_PLAYBACK")) as ResumeOffer.TakeControl
        assertTrue(!paused.playing)
    }

    @Test
    fun `a renderer that rolled onto a later queue track is picked up there`() {
        val live = LiveTransport.Known("http://h/api/stream/13?token=new", "PLAYING", 5.0)
        val offer = RendererResumePolicy.offer(snapshot, live) as ResumeOffer.TakeControl
        assertEquals(2, offer.snapshot.currentIndex)
    }

    @Test
    fun `an idle renderer offers a plain resume, a foreign stream a replace`() {
        assertTrue(RendererResumePolicy.offer(snapshot, LiveTransport.Known(null, "STOPPED", 0.0)) is ResumeOffer.Resume)
        assertTrue(RendererResumePolicy.offer(snapshot, LiveTransport.Known("", "NO_MEDIA_PRESENT", 0.0)) is ResumeOffer.Resume)
        val foreign = RendererResumePolicy.offer(snapshot, LiveTransport.Known("http://radio.example/live", "PLAYING", 0.0))
        assertTrue(foreign is ResumeOffer.Replace)
        // One of ours, but not in this queue: still someone else's session.
        assertTrue(RendererResumePolicy.offer(snapshot, LiveTransport.Known("http://h/api/stream/999?token=x", "PLAYING", 0.0)) is ResumeOffer.Replace)
    }

    @Test
    fun `an unreachable renderer is not an offer`() {
        assertNull(RendererResumePolicy.offer(snapshot, LiveTransport.Unreachable))
    }

    @Test
    fun `the jwt subject is read without verification`() {
        val payload = Base64.getUrlEncoder().withoutPadding().encodeToString("""{"sub":"3","exp":1}""".toByteArray())
        assertEquals("3", JwtClaims.subject("eyJhbGciOiJIUzI1NiJ9.$payload.sig"))
        assertNull(JwtClaims.subject("not-a-jwt"))
        assertNull(JwtClaims.subject(""))
    }
}
