package com.jamarr.android.playback

import androidx.media3.common.PlaybackException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PlaybackErrorPolicyTest {

    private fun ctx(
        trackId: Long = 1L,
        httpStatus: Int? = null,
        cacheInvolved: Boolean = false,
        hasNext: Boolean = true,
        canDowngrade: Boolean = false,
    ) = PlaybackErrorPolicy.Context(trackId, httpStatus, cacheInvolved, hasNext, canDowngrade)

    @Test
    fun `http status outranks the media3 error code`() {
        val p = PlaybackErrorPolicy()
        val code = PlaybackException.ERROR_CODE_IO_BAD_HTTP_STATUS
        assertEquals(PlaybackFailureKind.AUTH, p.classify(code, ctx(httpStatus = 401)))
        assertEquals(PlaybackFailureKind.AUTH, p.classify(code, ctx(httpStatus = 403)))
        assertEquals(PlaybackFailureKind.NOT_FOUND, p.classify(code, ctx(httpStatus = 404)))
        assertEquals(PlaybackFailureKind.SERVER, p.classify(code, ctx(httpStatus = 503)))
    }

    @Test
    fun `io errors split by whether the bytes came from disk`() {
        val p = PlaybackErrorPolicy()
        val io = PlaybackException.ERROR_CODE_IO_UNSPECIFIED
        assertEquals(PlaybackFailureKind.NETWORK, p.classify(io, ctx()))
        assertEquals(PlaybackFailureKind.CACHE, p.classify(io, ctx(cacheInvolved = true)))
        assertEquals(
            PlaybackFailureKind.CACHE,
            p.classify(PlaybackException.ERROR_CODE_IO_FILE_NOT_FOUND, ctx()),
        )
        assertEquals(
            PlaybackFailureKind.NETWORK,
            p.classify(PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT, ctx()),
        )
    }

    @Test
    fun `decoder and output failures are told apart from unsupported content`() {
        val p = PlaybackErrorPolicy()
        assertEquals(PlaybackFailureKind.DECODER, p.classify(PlaybackException.ERROR_CODE_DECODER_INIT_FAILED, ctx()))
        assertEquals(
            PlaybackFailureKind.UNSUPPORTED,
            p.classify(PlaybackException.ERROR_CODE_DECODING_FORMAT_UNSUPPORTED, ctx()),
        )
        assertEquals(
            PlaybackFailureKind.AUDIO_OUTPUT,
            p.classify(PlaybackException.ERROR_CODE_AUDIO_TRACK_INIT_FAILED, ctx()),
        )
        assertEquals(
            PlaybackFailureKind.UNSUPPORTED,
            p.classify(PlaybackException.ERROR_CODE_PARSING_CONTAINER_UNSUPPORTED, ctx()),
        )
    }

    @Test
    fun `network failures retry with backoff then give up`() {
        val p = PlaybackErrorPolicy()
        val c = ctx()
        val a1 = p.decide(PlaybackFailureKind.NETWORK, c, 0L)
        val a2 = p.decide(PlaybackFailureKind.NETWORK, c, 2_000L)
        val a3 = p.decide(PlaybackFailureKind.NETWORK, c, 6_000L)
        val a4 = p.decide(PlaybackFailureKind.NETWORK, c, 15_000L)
        assertEquals(RecoveryAction.Retry(1, 1_000L), a1)
        assertEquals(RecoveryAction.Retry(2, 3_000L), a2)
        assertEquals(RecoveryAction.Retry(3, 8_000L), a3)
        assertEquals(RecoveryAction.GiveUp, a4)
    }

    @Test
    fun `the budget is a window, not a lifetime`() {
        val p = PlaybackErrorPolicy()
        val c = ctx()
        repeat(3) { p.decide(PlaybackFailureKind.NETWORK, c, it * 1_000L) }
        assertEquals(RecoveryAction.GiveUp, p.decide(PlaybackFailureKind.NETWORK, c, 10_000L))
        // Two minutes later the old attempts no longer count.
        assertTrue(p.decide(PlaybackFailureKind.NETWORK, c, 130_000L) is RecoveryAction.Retry)
    }

    @Test
    fun `a track that plays again gets its budget back`() {
        val p = PlaybackErrorPolicy()
        val c = ctx()
        repeat(3) { p.decide(PlaybackFailureKind.NETWORK, c, it * 1_000L) }
        p.notePlaying(1L)
        assertEquals(RecoveryAction.Retry(1, 1_000L), p.decide(PlaybackFailureKind.NETWORK, c, 5_000L))
    }

    @Test
    fun `budgets are per track`() {
        val p = PlaybackErrorPolicy()
        repeat(3) { p.decide(PlaybackFailureKind.NETWORK, ctx(trackId = 1L), it * 1_000L) }
        assertEquals(RecoveryAction.GiveUp, p.decide(PlaybackFailureKind.NETWORK, ctx(trackId = 1L), 5_000L))
        assertTrue(p.decide(PlaybackFailureKind.NETWORK, ctx(trackId = 2L), 5_000L) is RecoveryAction.Retry)
    }

    @Test
    fun `auth failures retry with fresh credentials`() {
        val p = PlaybackErrorPolicy()
        val action = p.decide(PlaybackFailureKind.AUTH, ctx(), 0L) as RecoveryAction.Retry
        assertTrue(action.refreshCredentials)
        assertFalse(action.purgeCache)
    }

    @Test
    fun `damaged cache is purged once, then retried plainly`() {
        val p = PlaybackErrorPolicy()
        val first = p.decide(PlaybackFailureKind.CACHE, ctx(), 0L) as RecoveryAction.Retry
        val second = p.decide(PlaybackFailureKind.CACHE, ctx(), 2_000L) as RecoveryAction.Retry
        assertTrue(first.purgeCache)
        assertFalse(second.purgeCache)
    }

    @Test
    fun `missing or unsupported tracks are skipped, not retried`() {
        val p = PlaybackErrorPolicy()
        assertEquals(RecoveryAction.SkipTrack, p.decide(PlaybackFailureKind.NOT_FOUND, ctx(), 0L))
        assertEquals(RecoveryAction.SkipTrack, p.decide(PlaybackFailureKind.UNSUPPORTED, ctx(trackId = 2L), 0L))
        // Last item: nothing to skip to.
        assertEquals(RecoveryAction.GiveUp, p.decide(PlaybackFailureKind.NOT_FOUND, ctx(trackId = 3L, hasNext = false), 0L))
    }

    @Test
    fun `a run of unplayable tracks stops after a few skips`() {
        val p = PlaybackErrorPolicy()
        repeat(3) { i ->
            assertEquals(RecoveryAction.SkipTrack, p.decide(PlaybackFailureKind.NOT_FOUND, ctx(trackId = i.toLong()), 0L))
        }
        assertEquals(RecoveryAction.GiveUp, p.decide(PlaybackFailureKind.NOT_FOUND, ctx(trackId = 9L), 0L))
        // A track that actually plays resets the run.
        p.notePlaying(9L)
        assertEquals(RecoveryAction.SkipTrack, p.decide(PlaybackFailureKind.NOT_FOUND, ctx(trackId = 10L), 0L))
    }

    @Test
    fun `a decoder failure on an original tries a transcoded rung before skipping`() {
        val p = PlaybackErrorPolicy()
        val action = p.decide(PlaybackFailureKind.DECODER, ctx(canDowngrade = true), 0L) as RecoveryAction.Retry
        assertTrue(action.downgradeQuality)
        // Already on the ladder's floor: one plain retry, then skip.
        assertTrue(p.decide(PlaybackFailureKind.DECODER, ctx(trackId = 2L), 0L) is RecoveryAction.Retry)
        assertEquals(RecoveryAction.SkipTrack, p.decide(PlaybackFailureKind.DECODER, ctx(trackId = 2L), 1_000L))
    }

    @Test
    fun `descriptions exist for every kind`() {
        PlaybackFailureKind.entries.forEach { assertTrue(PlaybackErrorPolicy.describe(it).isNotBlank()) }
    }
}
