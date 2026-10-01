package com.jamarr.android.history

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PlayThresholdTrackerTest {
    private var now = 1_000_000L
    private val tracker = PlayThresholdTracker { now }

    private fun tick(trackId: Long?, playing: Boolean = true, offline: Boolean = true, durationMs: Long? = 180_000L) =
        tracker.onTick(trackId, playing, durationMs, offline)

    private fun play(ms: Long, trackId: Long = 1L, offline: Boolean = true, durationMs: Long? = 180_000L): OfflinePlayEvent? {
        var event: OfflinePlayEvent? = null
        var left = ms
        while (left > 0) {
            val step = minOf(500L, left)
            now += step
            left -= step
            tick(trackId, offline = offline, durationMs = durationMs)?.let { event = it }
        }
        return event
    }

    @Test
    fun `threshold matches the server`() {
        assertEquals(30_000L, playThresholdMs(null))
        assertEquals(12_000L, playThresholdMs(60_000L))
        assertEquals(30_000L, playThresholdMs(300_000L))
    }

    @Test
    fun `an offline play is recorded once, from when it started`() {
        val startedAt = now
        tick(1L)

        assertNull(play(29_500))
        val event = play(500)

        assertEquals(OfflinePlayEvent(trackId = 1L, startedAtMs = startedAt, playedMs = 30_000L), event)
        assertNull(play(60_000))
    }

    @Test
    fun `a play that crosses the threshold online is the server's to log`() {
        tick(1L, offline = false)

        assertNull(play(31_000, offline = false))
        // Dropping offline afterwards must not log it a second time.
        assertNull(play(60_000, offline = true))
    }

    @Test
    fun `going offline before the threshold leaves the play to the app`() {
        tick(1L, offline = false)
        assertNull(play(20_000, offline = false))

        assertEquals(1L, play(10_000, offline = true)?.trackId)
    }

    @Test
    fun `paused time does not count`() {
        tick(1L)
        play(20_000)
        tick(1L, playing = false)
        now += 600_000
        tick(1L, playing = false)

        assertNull(play(9_000))
        assertEquals(1L, play(1_500)?.trackId)
    }

    @Test
    fun `a short track needs a fifth of its length`() {
        tick(1L, durationMs = 60_000L)

        assertEquals(1L, play(12_000, durationMs = 60_000L)?.trackId)
    }

    @Test
    fun `a track counts again only after another one plays`() {
        tick(1L)
        play(31_000)
        assertNull(play(200_000))

        tick(2L)
        assertEquals(2L, play(31_000, trackId = 2L)?.trackId)
        tick(1L)
        assertEquals(1L, play(31_000, trackId = 1L)?.trackId)
    }
}
