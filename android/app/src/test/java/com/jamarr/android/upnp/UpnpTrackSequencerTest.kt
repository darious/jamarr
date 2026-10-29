package com.jamarr.android.upnp

import com.jamarr.android.renderer.QueuedTrack
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UpnpTrackSequencerTest {

    private class FakePort : AvTransportPort {
        val calls = mutableListOf<String>()
        var failSetUri = false
        var failSetNext = false
        var failPlay = false

        override suspend fun setUri(uri: String, metadata: String) {
            calls += "setUri:$uri"
            if (failSetUri) throw RuntimeException("714 Illegal MIME-type")
        }

        override suspend fun setNextUri(uri: String, metadata: String) {
            calls += "setNext:$uri"
            if (failSetNext) throw RuntimeException("401 Invalid Action")
        }

        override suspend fun play() {
            calls += "play"
            if (failPlay) throw RuntimeException("701 Transition not available")
        }
    }

    private fun track(id: Long, duration: Double = 200.0) = QueuedTrack(
        id = id,
        title = "Track $id",
        artist = "Artist",
        album = "Album",
        mime = "audio/flac",
        durationSeconds = duration,
        streamUrl = "http://jamarr.lan/api/stream/$id?token=old",
        artUrl = null,
    )

    private val queue = listOf(track(1), track(2), track(3))

    private var mints = 0

    /** The sequencer's clock, in ms; loads happen at whatever it reads. */
    private var clock = 0L

    private fun pastLoadGuard() {
        clock += UpnpTrackSequencer.POST_LOAD_GUARD_MS
    }

    private fun sequencer(supportsSetNext: Boolean = true) = UpnpTrackSequencer(
        // Every resolve mints a new token, as /api/stream-url does.
        resolveUri = { "http://jamarr.lan/api/stream/${it.id}?token=t${++mints}" },
        settleMs = 0,
        nowMs = { clock },
    ).apply { attach(supportsSetNext) }

    @Test
    fun failedLoadNeverPlaysAndKeepsTheCurrentTrack() = runTest {
        val port = FakePort()
        val seq = sequencer()
        assertEquals(LoadResult.Playing, seq.load(port, 0, queue))
        port.calls.clear()

        port.failSetUri = true
        val result = seq.load(port, 2)

        assertTrue(result is LoadResult.LoadFailed)
        assertEquals(listOf("setUri:http://jamarr.lan/api/stream/3?token=t2"), port.calls)
        assertEquals(0, seq.currentIndex)
        assertEquals("http://jamarr.lan/api/stream/1?token=t1", seq.currentUri)
    }

    @Test
    fun failedFirstLoadAdoptsNothing() = runTest {
        val port = FakePort().apply { failSetUri = true }
        val seq = sequencer()

        assertTrue(seq.load(port, 1, queue) is LoadResult.LoadFailed)

        assertFalse("play" in port.calls)
        assertEquals(-1, seq.currentIndex)
        assertTrue(seq.queue.isEmpty())
    }

    @Test
    fun playFailureStillAdoptsTheLoadedTrack() = runTest {
        val port = FakePort().apply { failPlay = true }
        val seq = sequencer()

        assertTrue(seq.load(port, 1, queue) is LoadResult.PlayFailed)
        assertEquals(1, seq.currentIndex)
    }

    @Test
    fun stagesNextOnlyWhenPlayingAndNearTheEnd() = runTest {
        val port = FakePort()
        val seq = sequencer()
        seq.load(port, 0, queue)
        port.calls.clear()

        // Not seen PLAYING yet.
        seq.syncNext(port, 190.0, 200.0)
        assertTrue(port.calls.isEmpty())

        assertEquals(PollOutcome.None, seq.observe(seq.currentUri, "PLAYING"))
        seq.syncNext(port, 10.0, 200.0)
        assertTrue("too early: the token would go stale", port.calls.isEmpty())

        seq.syncNext(port, 150.0, 200.0)
        assertEquals(listOf("setNext:http://jamarr.lan/api/stream/2?token=t2"), port.calls)
        assertEquals(1, seq.staged?.index)

        // Already staged: nothing re-sent.
        seq.syncNext(port, 151.0, 200.0)
        assertEquals(1, port.calls.size)
    }

    @Test
    fun stagedTransitionUnderContinuousPlayingAdvancesOnce() = runTest {
        val port = FakePort()
        val seq = sequencer()
        seq.load(port, 0, queue)
        seq.observe(seq.currentUri, "PLAYING")
        seq.syncNext(port, 150.0, 200.0)
        val stagedUri = seq.staged!!.uri
        port.calls.clear()

        // Renderer echoes the URI XML-escaped; still a match.
        val echoed = stagedUri.replace("&", "&amp;")
        assertEquals(PollOutcome.Transitioned(1, needsPlay = false), seq.observe(echoed, "PLAYING"))
        assertEquals(1, seq.currentIndex)
        assertNull(seq.staged)

        repeat(3) { assertEquals(PollOutcome.None, seq.observe(stagedUri, "PLAYING")) }
        assertEquals(1, seq.currentIndex)
        assertTrue("no reload of a track the renderer already started", port.calls.isEmpty())

        // And the one after that gets staged in turn.
        seq.syncNext(port, 150.0, 200.0)
        assertEquals(2, seq.staged?.index)
    }

    @Test
    fun transitionOntoAStoppedStagedTrackAsksForPlay() = runTest {
        val port = FakePort()
        val seq = sequencer()
        seq.load(port, 0, queue)
        seq.observe(seq.currentUri, "PLAYING")
        seq.syncNext(port, 150.0, 200.0)

        assertEquals(PollOutcome.Transitioned(1, needsPlay = true), seq.observe(seq.staged!!.uri, "STOPPED"))
        // Stopped but never seen playing: no STOPPED-based advance on top.
        assertEquals(PollOutcome.None, seq.observe(seq.currentUri, "STOPPED"))
    }

    @Test
    fun stoppedFallbackAdvancesWithoutStaging() = runTest {
        val port = FakePort()
        val seq = sequencer(supportsSetNext = false)
        seq.load(port, 0, queue)
        assertEquals(PollOutcome.None, seq.observe(seq.currentUri, "STOPPED"))
        seq.observe(seq.currentUri, "PLAYING")
        seq.syncNext(port, 199.0, 200.0)
        assertFalse(port.calls.any { it.startsWith("setNext") })

        pastLoadGuard()
        assertEquals(PollOutcome.Ended(1), seq.observe(seq.currentUri, "STOPPED"))
        // Reported once, not on every poll that stays STOPPED.
        assertEquals(PollOutcome.None, seq.observe(seq.currentUri, "STOPPED"))

        seq.load(port, 2)
        seq.observe(seq.currentUri, "PLAYING")
        pastLoadGuard()
        assertEquals(PollOutcome.Ended(null), seq.observe("", "STOPPED"))
    }

    @Test
    fun queueEditDropsAStaleStageAndRestagesTheNewNext() = runTest {
        val port = FakePort()
        val seq = sequencer()
        seq.load(port, 0, queue)
        seq.observe(seq.currentUri, "PLAYING")
        seq.syncNext(port, 150.0, 200.0)
        assertEquals(2L, seq.staged?.trackId)
        port.calls.clear()

        // Track 2 removed: track 3 is next now.
        seq.updateQueue(listOf(track(1), track(3)), 0)
        assertNull(seq.staged)
        seq.syncNext(port, 151.0, 200.0)
        assertEquals(3L, seq.staged?.trackId)
        assertEquals(listOf("setNext:http://jamarr.lan/api/stream/3?token=t3"), port.calls)
        port.calls.clear()

        // Everything after the current track removed: the renderer's slot is cleared.
        seq.updateQueue(listOf(track(1)), 0)
        assertNull(seq.staged)
        seq.syncNext(port, 152.0, 200.0)
        assertEquals(listOf("setNext:"), port.calls)

        // An edit that keeps the staged item next leaves it alone.
        seq.updateQueue(listOf(track(1), track(3)), 0)
        seq.syncNext(port, 153.0, 200.0)
        val staged = seq.staged
        seq.updateQueue(listOf(track(1), track(3), track(4)), 0)
        assertEquals(staged, seq.staged)
    }

    @Test
    fun explicitLoadClearsWhatTheRendererHasStaged() = runTest {
        val port = FakePort()
        val seq = sequencer()
        seq.load(port, 0, queue)
        seq.observe(seq.currentUri, "PLAYING")
        seq.syncNext(port, 150.0, 200.0)
        port.calls.clear()

        seq.load(port, 2)

        assertNull(seq.staged)
        assertEquals(listOf("setUri:http://jamarr.lan/api/stream/3?token=t3", "setNext:", "play"), port.calls)
    }

    @Test
    fun setNextFailureDisablesStagingAndFallsBack() = runTest {
        val port = FakePort().apply { failSetNext = true }
        val seq = sequencer()
        seq.load(port, 0, queue)
        seq.observe(seq.currentUri, "PLAYING")

        seq.syncNext(port, 150.0, 200.0)

        assertTrue(seq.stagingDisabled)
        assertFalse(seq.stagingEnabled)
        assertNull(seq.staged)
        port.calls.clear()
        seq.syncNext(port, 160.0, 200.0)
        assertTrue("no retries once disabled", port.calls.isEmpty())
        pastLoadGuard()
        assertEquals(PollOutcome.Ended(1), seq.observe(seq.currentUri, "STOPPED"))
    }

    @Test
    fun ignoredStagesDisableStagingAfterRepeatedMisses() = runTest {
        val port = FakePort()
        val seq = sequencer()
        seq.load(port, 0, listOf(track(1), track(2), track(3), track(4)))

        repeat(UpnpTrackSequencer.MAX_MISSED_TRANSITIONS) { i ->
            seq.observe(seq.currentUri, "PLAYING")
            seq.syncNext(port, 150.0, 200.0)
            // The renderer accepted SetNext but stopped on the old track anyway.
            pastLoadGuard()
            assertEquals(PollOutcome.None, seq.observe(seq.currentUri, "STOPPED"))
            clock += UpnpTrackSequencer.STAGED_STOP_GRACE_MS
            assertEquals(PollOutcome.Ended(i + 1), seq.observe(seq.currentUri, "STOPPED"))
            seq.load(port, i + 1)
        }

        assertTrue(seq.stagingDisabled)
    }

    @Test
    fun stopForgetsStateAndClearsTheRenderersNextSlot() = runTest {
        val port = FakePort()
        val seq = sequencer()
        seq.load(port, 0, queue)
        seq.observe(seq.currentUri, "PLAYING")
        seq.syncNext(port, 150.0, 200.0)
        port.calls.clear()

        seq.stop(port)

        assertEquals(listOf("setNext:"), port.calls)
        assertEquals(-1, seq.currentIndex)
        assertNull(seq.staged)
        assertEquals(PollOutcome.None, seq.observe("anything", "STOPPED"))
    }

    @Test
    fun unknownDurationStagesAsSoonAsPlaying() = runTest {
        val port = FakePort()
        val seq = sequencer()
        seq.load(port, 0, queue)
        seq.observe(seq.currentUri, "PLAYING")
        assertEquals(1, seq.stageCandidate(positionSeconds = 3.0, durationSeconds = 0.0))
    }

    @Test
    fun withoutAdvertisedSupportNothingIsStaged() = runTest {
        val seq = sequencer(supportsSetNext = false)
        seq.load(FakePort(), 0, queue)
        seq.observe(seq.currentUri, "PLAYING")
        assertNull(seq.stageCandidate(195.0, 200.0))
    }

    // --- A failed load keeps the renderer's staged next track ---

    @Test
    fun failedLoadKeepsTheStagedTrackSoTheTransitionIsStillSeen() = runTest {
        val port = FakePort()
        val seq = sequencer()
        seq.load(port, 0, queue)
        seq.observe(seq.currentUri, "PLAYING")
        seq.syncNext(port, 150.0, 200.0)
        val staged = seq.staged!!

        port.failSetUri = true
        assertTrue(seq.load(port, 2) is LoadResult.LoadFailed)
        assertEquals("the renderer still holds it", staged, seq.staged)
        port.failSetUri = false
        port.calls.clear()

        // The renderer rolls into the staged track it still had.
        assertEquals(PollOutcome.Transitioned(1, needsPlay = false), seq.observe(staged.uri, "PLAYING"))
        assertEquals(1, seq.currentIndex)
        seq.syncNext(port, 150.0, 200.0)
        assertEquals("stages the track after it, not the one already playing", 2, seq.staged?.index)
        assertEquals(listOf("setNext:http://jamarr.lan/api/stream/3?token=t4"), port.calls)
    }

    @Test
    fun failedLoadKeepsTheEndOfTrackFallbackArmed() = runTest {
        val port = FakePort()
        val seq = sequencer(supportsSetNext = false)
        seq.load(port, 0, queue)
        seq.observe(seq.currentUri, "PLAYING")

        port.failSetUri = true
        assertTrue(seq.load(port, 2) is LoadResult.LoadFailed)

        // The old track carries on and ends: still an advance, and no fresh
        // post-load guard from a load that never happened.
        pastLoadGuard()
        assertEquals(PollOutcome.Ended(1), seq.observe(seq.currentUri, "STOPPED"))
    }

    @Test
    fun failedResolveKeepsTheStagedTrackToo() = runTest {
        val port = FakePort()
        var failResolve = false
        val seq = UpnpTrackSequencer(
            resolveUri = { if (failResolve) error("offline") else "http://jamarr.lan/api/stream/${it.id}?token=t${++mints}" },
            settleMs = 0,
            nowMs = { clock },
        ).apply { attach(true) }
        seq.load(port, 0, queue)
        seq.observe(seq.currentUri, "PLAYING")
        seq.syncNext(port, 150.0, 200.0)
        val staged = seq.staged

        failResolve = true
        assertTrue(seq.load(port, 2) is LoadResult.LoadFailed)
        assertEquals(staged, seq.staged)
    }

    // --- TrackURI matching ---

    @Test
    fun sameUriMatchesTheEchoesRenderersSendBack() {
        val ours = "http://192.168.0.22:8112/api/stream/7?token=abc-123_x&quality=lossless"
        assertTrue(UpnpTrackSequencer.sameUri(ours, ours))
        assertTrue(UpnpTrackSequencer.sameUri(ours.replace("&", "&amp;"), ours))
        assertTrue(UpnpTrackSequencer.sameUri(ours.replace("&", "&#38;"), ours))
        assertTrue("re-encoded", UpnpTrackSequencer.sameUri(ours.replace("-", "%2D").replace("_", "%5F"), ours))
        assertTrue(
            "host rewritten",
            UpnpTrackSequencer.sameUri("http://jamarr.local:8112/api/stream/7?token=abc-123_x&quality=lossless", ours),
        )
        assertTrue(
            "query reordered",
            UpnpTrackSequencer.sameUri("http://10.0.0.5/api/stream/7?quality=lossless&token=abc-123_x", ours),
        )
    }

    @Test
    fun sameUriNeverConfusesDifferentTracks() {
        val ours = "http://192.168.0.22:8112/api/stream/7?token=abc"
        assertFalse("other token", UpnpTrackSequencer.sameUri("http://192.168.0.22:8112/api/stream/7?token=abd", ours))
        assertFalse("other track", UpnpTrackSequencer.sameUri("http://192.168.0.22:8112/api/stream/8?token=abc", ours))
        assertFalse("no token", UpnpTrackSequencer.sameUri("http://other/api/stream/7", "http://host/api/stream/7"))
        assertFalse("empty token", UpnpTrackSequencer.sameUri("http://a/api/stream/7?token=", "http://b/api/stream/7?token="))
        assertFalse("malformed", UpnpTrackSequencer.sameUri("http://a/api/stream/7?token=abc%G", ours.replace("192.168.0.22", "b")))
        assertFalse(UpnpTrackSequencer.sameUri("", ours))
        assertFalse(UpnpTrackSequencer.sameUri(ours, null))
    }

    @Test
    fun transitionIsSeenThroughARewrittenHost() = runTest {
        val port = FakePort()
        val seq = sequencer()
        seq.load(port, 0, queue)
        seq.observe(seq.currentUri, "PLAYING")
        seq.syncNext(port, 150.0, 200.0)

        val echoed = seq.staged!!.uri.replace("jamarr.lan", "192.168.0.22:8112")
        assertEquals(PollOutcome.Transitioned(1, needsPlay = false), seq.observe(echoed, "PLAYING"))
    }

    // --- STOPPED handling ---

    @Test
    fun stoppedWithATrackStagedWaitsForTheRendererToTakeIt() = runTest {
        val port = FakePort()
        val seq = sequencer()
        seq.load(port, 0, queue)
        seq.observe(seq.currentUri, "PLAYING")
        seq.syncNext(port, 150.0, 200.0)
        val staged = seq.staged!!
        pastLoadGuard()

        // Passing through STOPPED on the way into the staged URI.
        assertEquals(PollOutcome.None, seq.observe(seq.currentUri, "STOPPED"))
        clock += 1_000
        assertEquals(PollOutcome.None, seq.observe(seq.currentUri, "STOPPED"))
        clock += 1_000
        assertEquals(PollOutcome.Transitioned(1, needsPlay = false), seq.observe(staged.uri, "PLAYING"))
        assertFalse(seq.stagingDisabled)
    }

    @Test
    fun stoppedPastTheGraceIsAMissAndAnEnd() = runTest {
        val port = FakePort()
        val seq = sequencer()
        seq.load(port, 0, queue)
        seq.observe(seq.currentUri, "PLAYING")
        seq.syncNext(port, 150.0, 200.0)
        pastLoadGuard()

        assertEquals(PollOutcome.None, seq.observe(seq.currentUri, "STOPPED"))
        clock += UpnpTrackSequencer.STAGED_STOP_GRACE_MS - 1
        assertEquals(PollOutcome.None, seq.observe(seq.currentUri, "STOPPED"))
        clock += 1
        assertEquals(PollOutcome.Ended(1), seq.observe(seq.currentUri, "STOPPED"))
        assertNull(seq.staged)
        assertEquals(PollOutcome.None, seq.observe(seq.currentUri, "STOPPED"))
    }

    @Test
    fun graceRestartsAfterTheRendererResumes() = runTest {
        val port = FakePort()
        val seq = sequencer()
        seq.load(port, 0, queue)
        seq.observe(seq.currentUri, "PLAYING")
        seq.syncNext(port, 150.0, 200.0)
        pastLoadGuard()

        assertEquals(PollOutcome.None, seq.observe(seq.currentUri, "STOPPED"))
        clock += 2_000
        seq.observe(seq.currentUri, "PLAYING")
        clock += 2_000
        // A fresh STOPPED, not 4s into the first one.
        assertEquals(PollOutcome.None, seq.observe(seq.currentUri, "STOPPED"))
    }

    @Test
    fun stoppedChurnRightAfterALoadIsNotTheEndOfTheTrack() = runTest {
        val port = FakePort()
        val seq = sequencer(supportsSetNext = false)
        seq.load(port, 0, queue)

        clock += 2_000
        seq.observe(seq.currentUri, "PLAYING")
        clock += 1_000
        assertEquals(PollOutcome.None, seq.observe(seq.currentUri, "STOPPED"))
        clock += 1_000
        assertEquals(PollOutcome.None, seq.observe(seq.currentUri, "PLAYING"))
        assertEquals(0, seq.currentIndex)

        // A track that really is that short still ends once the guard is over.
        clock += 1_000
        assertEquals(PollOutcome.None, seq.observe(seq.currentUri, "STOPPED"))
        clock = UpnpTrackSequencer.POST_LOAD_GUARD_MS
        assertEquals(PollOutcome.Ended(1), seq.observe(seq.currentUri, "STOPPED"))
    }

    @Test
    fun loadGuardRestartsOnAStagedTransition() = runTest {
        val port = FakePort()
        val seq = sequencer(supportsSetNext = true)
        seq.load(port, 0, queue)
        seq.observe(seq.currentUri, "PLAYING")
        seq.syncNext(port, 150.0, 200.0)
        pastLoadGuard()
        seq.observe(seq.staged!!.uri, "PLAYING")
        assertEquals(1, seq.currentIndex)

        clock += 1_000
        assertEquals(PollOutcome.None, seq.observe(seq.currentUri, "STOPPED"))
    }

    @Test
    fun adoptingALiveQueueSendsNothingAndStagesTheNextTrackWhenDue() = runTest {
        val port = FakePort()
        val seq = sequencer()
        val liveUri = "http://jamarr.lan/api/stream/2?token=fromBeforeRestart"

        seq.adopt(queue, 1, liveUri, playing = true)

        assertTrue(port.calls.isEmpty())
        assertEquals(1, seq.currentIndex)
        assertEquals(liveUri, seq.currentUri)
        // Still mid-track: nothing to do; near the end: the next track is staged.
        assertEquals(PollOutcome.None, seq.observe(liveUri, "PLAYING"))
        seq.syncNext(port, positionSeconds = 100.0, durationSeconds = 200.0)
        assertTrue(port.calls.isEmpty())
        seq.syncNext(port, positionSeconds = 195.0, durationSeconds = 200.0)
        assertEquals(listOf("setNext:http://jamarr.lan/api/stream/3?token=t1"), port.calls)
        // The renderer rolls onto it: recognised as a transition, no reload.
        assertEquals(PollOutcome.Transitioned(2, needsPlay = false), seq.observe("http://jamarr.lan/api/stream/3?token=t1", "PLAYING"))
    }

    @Test
    fun adoptingThenLoadingClearsAPossiblyStaleNextSlot() = runTest {
        val port = FakePort()
        val seq = sequencer()
        seq.adopt(queue, 0, "http://jamarr.lan/api/stream/1?token=old", playing = true)

        assertEquals(LoadResult.Playing, seq.load(port, 2))

        // The slot the dead process may have staged is cleared before play.
        assertEquals(listOf("setUri:http://jamarr.lan/api/stream/3?token=t1", "setNext:", "play"), port.calls)
    }
}
