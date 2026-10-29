package com.jamarr.android.playback

import androidx.media3.common.PlaybackException

/** What went wrong, in terms a user action can address. */
enum class PlaybackFailureKind {
    /** The stream token or session was rejected (HTTP 401/403). */
    AUTH,
    /** The server says the track is gone (HTTP 404). */
    NOT_FOUND,
    /** Connection, DNS, timeout: the server could not be reached or stalled. */
    NETWORK,
    /** The server answered with a 5xx or a malformed response. */
    SERVER,
    /** Bytes on disk (read-ahead or a download) could not be read. */
    CACHE,
    /** The platform decoder refused or failed on this stream. */
    DECODER,
    /** The AudioTrack could not be opened or written (route change, HAL). */
    AUDIO_OUTPUT,
    /** The container or codec is not something this device plays. */
    UNSUPPORTED,
    UNKNOWN,
}

/** The next step after a terminal player error. */
sealed interface RecoveryAction {
    /**
     * Re-prepare the same item at the same position after [delayMs].
     *
     * [refreshCredentials] drops the cached stream URL so a fresh token is
     * minted; [purgeCache] deletes the track's bytes on disk first so the
     * retry streams them again; [downgradeQuality] steps the quality ladder
     * down before retrying (decoder trouble on an exotic original).
     */
    data class Retry(
        val attempt: Int,
        val delayMs: Long,
        val refreshCredentials: Boolean = false,
        val purgeCache: Boolean = false,
        val downgradeQuality: Boolean = false,
    ) : RecoveryAction

    /** Move on to the next queue item; this one will not play on this device. */
    data object SkipTrack : RecoveryAction

    /** Stop trying; leave the player in its error state for the user to act on. */
    data object GiveUp : RecoveryAction
}

/**
 * Decides what to do when the local player hits a terminal error.
 *
 * Media3 stops the player on any `PlaybackException`; adaptive quality
 * downgrade only reacts to *buffering*, so without this an expired stream
 * token, a flaky LAN or a truncated read-ahead file simply ended playback.
 *
 * Every retry is bounded: at most [maxAttemptsPerTrack] within [windowMs] for
 * one track, at most [maxConsecutiveSkips] unplayable tracks in a row (so a
 * queue of deleted tracks is not raced through), and no retry at all for
 * failures another attempt cannot change. Kept free of Android types so the
 * budget is unit-testable; the service supplies the error code and context.
 */
class PlaybackErrorPolicy(
    private val maxAttemptsPerTrack: Int = MAX_ATTEMPTS_PER_TRACK,
    private val windowMs: Long = WINDOW_MS,
    private val backoffMs: LongArray = BACKOFF_MS,
    private val maxConsecutiveSkips: Int = MAX_CONSECUTIVE_SKIPS,
) {
    private val attempts = mutableMapOf<Long, ArrayDeque<Long>>()
    private var consecutiveSkips = 0

    /** Once per track per error: a damaged read-ahead file is deleted on the first retry only. */
    private val purged = mutableSetOf<Long>()

    /**
     * Context the service gathers about the failing item.
     *
     * [httpStatus] comes from the data source's response, when there was one;
     * [cacheInvolved] is true when the failure surfaced inside the cache layer
     * or the track was fully on disk, which turns an IO error into [PlaybackFailureKind.CACHE].
     */
    data class Context(
        val trackId: Long,
        val httpStatus: Int? = null,
        val cacheInvolved: Boolean = false,
        val hasNext: Boolean = false,
        val canDowngrade: Boolean = false,
    )

    fun classify(errorCode: Int, context: Context): PlaybackFailureKind {
        context.httpStatus?.let { status ->
            when {
                status == 401 || status == 403 -> return PlaybackFailureKind.AUTH
                status == 404 || status == 410 -> return PlaybackFailureKind.NOT_FOUND
                status >= 500 -> return PlaybackFailureKind.SERVER
            }
        }
        return when (errorCode) {
            PlaybackException.ERROR_CODE_IO_BAD_HTTP_STATUS,
            PlaybackException.ERROR_CODE_IO_INVALID_HTTP_CONTENT_TYPE,
            -> PlaybackFailureKind.SERVER

            PlaybackException.ERROR_CODE_IO_FILE_NOT_FOUND,
            PlaybackException.ERROR_CODE_IO_READ_POSITION_OUT_OF_RANGE,
            PlaybackException.ERROR_CODE_IO_NO_PERMISSION,
            -> PlaybackFailureKind.CACHE

            PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_FAILED,
            PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT,
            PlaybackException.ERROR_CODE_IO_CLEARTEXT_NOT_PERMITTED,
            -> PlaybackFailureKind.NETWORK

            PlaybackException.ERROR_CODE_IO_UNSPECIFIED ->
                if (context.cacheInvolved) PlaybackFailureKind.CACHE else PlaybackFailureKind.NETWORK

            PlaybackException.ERROR_CODE_PARSING_CONTAINER_MALFORMED,
            PlaybackException.ERROR_CODE_PARSING_MANIFEST_MALFORMED,
            -> if (context.cacheInvolved) PlaybackFailureKind.CACHE else PlaybackFailureKind.UNSUPPORTED

            PlaybackException.ERROR_CODE_PARSING_CONTAINER_UNSUPPORTED,
            PlaybackException.ERROR_CODE_PARSING_MANIFEST_UNSUPPORTED,
            PlaybackException.ERROR_CODE_DECODING_FORMAT_UNSUPPORTED,
            PlaybackException.ERROR_CODE_DECODING_FORMAT_EXCEEDS_CAPABILITIES,
            -> PlaybackFailureKind.UNSUPPORTED

            PlaybackException.ERROR_CODE_DECODER_INIT_FAILED,
            PlaybackException.ERROR_CODE_DECODER_QUERY_FAILED,
            PlaybackException.ERROR_CODE_DECODING_FAILED,
            -> PlaybackFailureKind.DECODER

            PlaybackException.ERROR_CODE_AUDIO_TRACK_INIT_FAILED,
            PlaybackException.ERROR_CODE_AUDIO_TRACK_WRITE_FAILED,
            PlaybackException.ERROR_CODE_AUDIO_TRACK_OFFLOAD_WRITE_FAILED,
            PlaybackException.ERROR_CODE_AUDIO_TRACK_OFFLOAD_INIT_FAILED,
            -> PlaybackFailureKind.AUDIO_OUTPUT

            else -> PlaybackFailureKind.UNKNOWN
        }
    }

    fun decide(kind: PlaybackFailureKind, context: Context, nowMs: Long): RecoveryAction {
        val trackId = context.trackId
        return when (kind) {
            // Nothing a retry changes: the server has no such track, or the
            // device cannot play this format at all.
            PlaybackFailureKind.NOT_FOUND, PlaybackFailureKind.UNSUPPORTED -> skipOrGiveUp(context)

            PlaybackFailureKind.AUTH -> retryOr(trackId, nowMs, context, refreshCredentials = true) { RecoveryAction.GiveUp }

            PlaybackFailureKind.CACHE -> retryOr(
                trackId, nowMs, context,
                // Delete the damaged bytes once; a second failure means the
                // network copy is bad too, and that is a server problem.
                purgeCache = purged.add(trackId),
            ) { RecoveryAction.GiveUp }

            PlaybackFailureKind.DECODER ->
                if (context.canDowngrade) {
                    retryOr(trackId, nowMs, context, downgradeQuality = true) { skipOrGiveUp(context) }
                } else {
                    // One retry: decoder init is flaky under memory pressure.
                    retryOr(trackId, nowMs, context, limit = 1) { skipOrGiveUp(context) }
                }

            PlaybackFailureKind.NETWORK, PlaybackFailureKind.SERVER, PlaybackFailureKind.AUDIO_OUTPUT ->
                retryOr(trackId, nowMs, context) { RecoveryAction.GiveUp }

            PlaybackFailureKind.UNKNOWN -> retryOr(trackId, nowMs, context, limit = 1) { RecoveryAction.GiveUp }
        }
    }

    /** Playback is healthy again: the track's budget is forgiven. */
    fun notePlaying(trackId: Long) {
        attempts.remove(trackId)
        purged.remove(trackId)
        consecutiveSkips = 0
    }

    fun attemptCount(trackId: Long, nowMs: Long): Int = recentAttempts(trackId, nowMs).size

    private fun skipOrGiveUp(context: Context): RecoveryAction {
        if (!context.hasNext || consecutiveSkips >= maxConsecutiveSkips) return RecoveryAction.GiveUp
        consecutiveSkips++
        return RecoveryAction.SkipTrack
    }

    private inline fun retryOr(
        trackId: Long,
        nowMs: Long,
        context: Context,
        refreshCredentials: Boolean = false,
        purgeCache: Boolean = false,
        downgradeQuality: Boolean = false,
        limit: Int = maxAttemptsPerTrack,
        exhausted: () -> RecoveryAction,
    ): RecoveryAction {
        val recent = recentAttempts(trackId, nowMs)
        if (recent.size >= minOf(limit, maxAttemptsPerTrack)) return exhausted()
        recent.addLast(nowMs)
        val attempt = recent.size
        return RecoveryAction.Retry(
            attempt = attempt,
            delayMs = backoffMs[(attempt - 1).coerceIn(0, backoffMs.lastIndex)],
            refreshCredentials = refreshCredentials,
            purgeCache = purgeCache,
            downgradeQuality = downgradeQuality,
        )
    }

    private fun recentAttempts(trackId: Long, nowMs: Long): ArrayDeque<Long> {
        val list = attempts.getOrPut(trackId) { ArrayDeque() }
        while (list.isNotEmpty() && nowMs - list.first() >= windowMs) list.removeFirst()
        return list
    }

    companion object {
        const val MAX_ATTEMPTS_PER_TRACK = 3
        const val WINDOW_MS = 120_000L
        val BACKOFF_MS = longArrayOf(1_000L, 3_000L, 8_000L)
        const val MAX_CONSECUTIVE_SKIPS = 3

        /** User-facing summary for a failure kind. */
        fun describe(kind: PlaybackFailureKind): String = when (kind) {
            PlaybackFailureKind.AUTH -> "Sign-in expired"
            PlaybackFailureKind.NOT_FOUND -> "Track not on server"
            PlaybackFailureKind.NETWORK -> "Server unreachable"
            PlaybackFailureKind.SERVER -> "Server error"
            PlaybackFailureKind.CACHE -> "Damaged cached data"
            PlaybackFailureKind.DECODER -> "Decoder failed"
            PlaybackFailureKind.AUDIO_OUTPUT -> "Audio output failed"
            PlaybackFailureKind.UNSUPPORTED -> "Format not supported on this device"
            PlaybackFailureKind.UNKNOWN -> "Playback failed"
        }
    }
}
