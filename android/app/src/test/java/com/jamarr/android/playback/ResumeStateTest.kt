package com.jamarr.android.playback

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ResumeStateTest {

    private val queue = ResumeQueue(
        tracks = listOf(
            ResumeTrack("track:1|p:album:x", "One", "Artist", "Album", "https://art/1", 180_000L),
            ResumeTrack("track:2|p:album:x", "Two", "Artist", "Album", "https://art/2", 240_000L),
        ),
        index = 1,
        positionMs = 12_345L,
    )

    @Test
    fun `a queue round-trips`() {
        assertEquals(queue, ResumeQueue.decode(ResumeQueue.encode(queue)))
    }

    @Test
    fun `nothing stored means nothing to resume`() {
        assertNull(ResumeQueue.decode(null))
        assertNull(ResumeQueue.decode(""))
        assertNull(ResumeQueue.decode("   "))
    }

    @Test
    fun `a corrupt blob is not a crash`() {
        // It is read on the resumption path, where throwing would take out the
        // service before it could play anything.
        assertNull(ResumeQueue.decode("{not json"))
        assertNull(ResumeQueue.decode("[]"))
    }

    @Test
    fun `an empty queue is nothing to resume`() {
        assertNull(ResumeQueue.decode(ResumeQueue.encode(ResumeQueue())))
    }

    @Test
    fun `an out-of-range index is clamped, not trusted`() {
        val stale = queue.copy(index = 9, positionMs = -5L)
        val decoded = ResumeQueue.decode(ResumeQueue.encode(stale))
        assertEquals(1, decoded?.index)
        assertEquals(0L, decoded?.positionMs)
    }

    @Test
    fun `unknown fields from a future build are ignored`() {
        val raw = """{"tracks":[{"mediaId":"track:1","title":"One","surprise":true}],"index":0,"positionMs":0}"""
        val decoded = ResumeQueue.decode(raw)
        assertEquals(1, decoded?.tracks?.size)
        assertEquals("track:1", decoded?.tracks?.first()?.mediaId)
        assertEquals(-1L, decoded?.tracks?.first()?.durationMs)
    }
}
