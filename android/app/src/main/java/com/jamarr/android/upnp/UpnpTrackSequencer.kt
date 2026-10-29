package com.jamarr.android.upnp

import com.jamarr.android.renderer.QueuedTrack
import kotlinx.coroutines.delay
import java.io.ByteArrayOutputStream
import java.net.URI
import java.net.URISyntaxException
import kotlin.coroutines.cancellation.CancellationException

/** The AVTransport actions the sequencer drives: jUPnP in the app, a fake in tests. */
interface AvTransportPort {
    suspend fun setUri(uri: String, metadata: String)

    suspend fun setNextUri(uri: String, metadata: String)

    suspend fun play()
}

sealed interface LoadResult {
    /** The track is loaded and Play was accepted. */
    data object Playing : LoadResult

    /** The renderer never took the URI; it still has whatever it had before. */
    data class LoadFailed(val message: String) : LoadResult

    /** The URI is loaded, but the renderer refused to start it. */
    data class PlayFailed(val message: String) : LoadResult
}

sealed interface PollOutcome {
    data object None : PollOutcome

    /**
     * The renderer moved onto the staged track by itself. [needsPlay] when it
     * loaded it but stopped instead of carrying on.
     */
    data class Transitioned(val index: Int, val needsPlay: Boolean) : PollOutcome

    /** The current track ran out with nothing staged taking over; [nextIndex] is null at the end of the queue. */
    data class Ended(val nextIndex: Int?) : PollOutcome
}

/**
 * Which queue item a UPnP renderer has loaded, and which one is staged behind
 * it with SetNextAVTransportURI.
 *
 * - [load] only issues Play once SetAVTransportURI succeeded; a failed load
 *   leaves [queue] and [currentIndex] on what the renderer still has.
 * - Once the current track has been seen PLAYING and is within
 *   [stageLeadSeconds] of its end, [syncNext] stages the next item. Staging
 *   late rather than at track start keeps the stream token fresh when the
 *   renderer finally fetches it: tokens are resolved at staging time and are
 *   short-lived for UPnP.
 * - [observe] advances [currentIndex] exactly once when the renderer's
 *   TrackURI turns into the staged URI, without reloading anything, and
 *   falls back to the STOPPED-based advance when nothing took over. A
 *   STOPPED within [postLoadGuardMs] of a load is start-up churn, not the
 *   end of the track; with a track staged, a STOPPED gets [stagedStopGraceMs]
 *   to turn into the staged URI first, as some renderers pass through
 *   STOPPED on their way into it.
 * - Advertised SetNextAVTransportURI support is provisional: a failed SetNext
 *   or [maxMissedTransitions] staged tracks the renderer ignored turn staging
 *   off ([stagingDisabled]) for the rest of the session.
 *
 * Not thread-safe; the controller serialises calls.
 */
class UpnpTrackSequencer(
    private val resolveUri: suspend (QueuedTrack) -> String = { it.streamUrl },
    private val stageLeadSeconds: Double = STAGE_LEAD_SECONDS,
    private val maxMissedTransitions: Int = MAX_MISSED_TRANSITIONS,
    private val settleMs: Long = SETTLE_MS,
    private val postLoadGuardMs: Long = POST_LOAD_GUARD_MS,
    private val stagedStopGraceMs: Long = STAGED_STOP_GRACE_MS,
    /** Monotonic milliseconds; injectable for tests. */
    private val nowMs: () -> Long = { System.nanoTime() / 1_000_000 },
) {
    data class Staged(val index: Int, val trackId: Long, val uri: String)

    var queue: List<QueuedTrack> = emptyList()
        private set
    var currentIndex: Int = -1
        private set
    var currentUri: String? = null
        private set
    var staged: Staged? = null
        private set

    /** The renderer advertises SetNextAVTransportURI and has not let us down. */
    var stagingEnabled: Boolean = false
        private set

    /** Set once staging was switched off after a failure, until the next [attach]. */
    var stagingDisabled: Boolean = false
        private set

    /** A URI went to the renderer's next slot and was neither played nor cleared. */
    private var rendererMayHoldNext = false
    private var sawPlaying = false
    private var missedTransitions = 0

    /** When the current track was loaded or rolled into; null when none is. */
    private var trackStartedAtMs: Long? = null

    /** First STOPPED poll while waiting for the renderer to take the staged track. */
    private var stagedStopSinceMs: Long? = null

    /** A (new) renderer: forget everything about the previous one. */
    fun attach(supportsSetNext: Boolean) {
        reset()
        stagingEnabled = supportsSetNext
        stagingDisabled = false
        missedTransitions = 0
    }

    /** Playback stopped: nothing is loaded or staged any more. */
    suspend fun stop(port: AvTransportPort?) {
        val holdsNext = rendererMayHoldNext
        reset()
        if (holdsNext && port != null) clearRendererNext(port)
    }

    private fun reset() {
        queue = emptyList()
        currentIndex = -1
        currentUri = null
        staged = null
        rendererMayHoldNext = false
        sawPlaying = false
        trackStartedAtMs = null
        stagedStopSinceMs = null
    }

    /**
     * Loads [index] of [newQueue] and plays it. The queue and index are
     * adopted only once the renderer accepted the URI; until then the
     * renderer still plays the old track with its staged next behind it, so
     * a failed load leaves that bookkeeping untouched too.
     */
    suspend fun load(port: AvTransportPort, index: Int, newQueue: List<QueuedTrack> = queue): LoadResult {
        val track = newQueue.getOrNull(index) ?: return LoadResult.LoadFailed("No track at position $index")
        val uri = try {
            resolveUri(track)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            return LoadResult.LoadFailed(e.message ?: "Could not resolve the stream URL")
        }
        try {
            port.setUri(uri, DidlLite.build(track.copy(streamUrl = uri)))
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            return LoadResult.LoadFailed(e.message ?: "SetAVTransportURI failed")
        }
        queue = newQueue
        currentIndex = index
        currentUri = uri
        // Whatever was staged belonged to the old position.
        staged = null
        sawPlaying = false
        trackStartedAtMs = nowMs()
        stagedStopSinceMs = null
        // Renderers differ on whether SetAVTransportURI drops the next slot;
        // a stale one would play after this track, so clear it explicitly.
        if (rendererMayHoldNext) {
            rendererMayHoldNext = false
            clearRendererNext(port)
        }
        delay(settleMs)
        return try {
            port.play()
            LoadResult.Playing
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            LoadResult.PlayFailed(e.message ?: "Play failed")
        }
    }

    /**
     * Takes over a queue the renderer is already playing (process restart):
     * nothing is sent to the renderer. [liveUri] is what it reports as its
     * current track, so a later transition is recognised; the next slot is
     * assumed occupied, so the next load clears it rather than trusting it.
     */
    fun adopt(newQueue: List<QueuedTrack>, index: Int, liveUri: String?, playing: Boolean) {
        queue = newQueue
        currentIndex = index.coerceIn(0, (newQueue.size - 1).coerceAtLeast(0))
        currentUri = liveUri
        staged = null
        rendererMayHoldNext = true
        sawPlaying = playing
        trackStartedAtMs = nowMs()
        stagedStopSinceMs = null
        missedTransitions = 0
    }

    /**
     * Replaces the queue around the loaded track (an in-place edit). A staged
     * item that is no longer next is dropped; [syncNext] re-stages or clears.
     */
    fun updateQueue(newQueue: List<QueuedTrack>, newCurrentIndex: Int) {
        queue = newQueue
        currentIndex = newCurrentIndex
        val s = staged ?: return
        val next = newQueue.getOrNull(newCurrentIndex + 1)
        if (next == null || s.index != newCurrentIndex + 1 || next.id != s.trackId) staged = null
    }

    /** The queue index worth staging now, or null. */
    fun stageCandidate(positionSeconds: Double, durationSeconds: Double): Int? {
        if (!stagingEnabled || !sawPlaying || currentIndex < 0) return null
        val next = currentIndex + 1
        val track = queue.getOrNull(next) ?: return null
        val s = staged
        if (s != null && s.index == next && s.trackId == track.id) return null
        if (durationSeconds > 0 && durationSeconds - positionSeconds > stageLeadSeconds) return null
        return next
    }

    /**
     * Brings the renderer's next slot in line with the queue: stages the next
     * item once due, or clears a slot whose item is gone. A failing SetNext
     * turns staging off for the session.
     */
    suspend fun syncNext(port: AvTransportPort, positionSeconds: Double, durationSeconds: Double) {
        val index = stageCandidate(positionSeconds, durationSeconds)
        if (index == null) {
            if (staged == null && rendererMayHoldNext && queue.getOrNull(currentIndex + 1) == null) {
                rendererMayHoldNext = false
                clearRendererNext(port)
            }
            return
        }
        val track = queue[index]
        val uri = try {
            resolveUri(track)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            return // Try again on the next poll.
        }
        if (sameUri(uri, currentUri)) {
            // Indistinguishable from the current track, so a transition could
            // never be recognised; leave this one to the STOPPED fallback.
            staged = Staged(index, track.id, uri)
            return
        }
        try {
            port.setNextUri(uri, DidlLite.build(track.copy(streamUrl = uri)))
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            disableStaging()
            return
        }
        staged = Staged(index, track.id, uri)
        rendererMayHoldNext = true
    }

    /**
     * Reconciles one poll: [trackUri] from GetPositionInfo, [transportState]
     * from GetTransportInfo (null when that call failed).
     */
    fun observe(trackUri: String?, transportState: String?): PollOutcome {
        val s = staged
        if (s != null && trackUri != null && !sameUri(s.uri, currentUri) && sameUri(trackUri, s.uri)) {
            currentIndex = s.index
            currentUri = s.uri
            staged = null
            rendererMayHoldNext = false
            missedTransitions = 0
            sawPlaying = transportState == PLAYING
            trackStartedAtMs = nowMs()
            stagedStopSinceMs = null
            return PollOutcome.Transitioned(s.index, needsPlay = transportState == STOPPED)
        }
        if (transportState == PLAYING) sawPlaying = true
        if (transportState != STOPPED) stagedStopSinceMs = null
        if (transportState == STOPPED && sawPlaying && currentIndex >= 0) {
            val now = nowMs()
            // Start-up churn: some renderers report STOPPED between PLAYING
            // polls while they open the stream. A track that really is this
            // short still ends on the first STOPPED poll after the guard.
            val startedAt = trackStartedAtMs
            if (startedAt != null && now - startedAt < postLoadGuardMs) return PollOutcome.None
            val awaitingStaged = s != null && !sameUri(s.uri, currentUri)
            if (awaitingStaged) {
                val since = stagedStopSinceMs ?: now.also { stagedStopSinceMs = it }
                if (now - since < stagedStopGraceMs) return PollOutcome.None
                // Staged, yet the renderer stopped on the old track. Its next
                // slot may still hold the URI; the following load clears it.
                if (++missedTransitions >= maxMissedTransitions) disableStaging()
            }
            sawPlaying = false
            stagedStopSinceMs = null
            staged = null
            val next = currentIndex + 1
            return PollOutcome.Ended(next.takeIf { it <= queue.lastIndex })
        }
        return PollOutcome.None
    }

    private fun disableStaging() {
        stagingEnabled = false
        stagingDisabled = true
        staged = null
    }

    private suspend fun clearRendererNext(port: AvTransportPort) {
        // Some renderers fault on an empty NextURI; nothing more to do then.
        try {
            port.setNextUri("", "")
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
        }
    }

    companion object {
        const val STAGE_LEAD_SECONDS = 60.0
        const val MAX_MISSED_TRANSITIONS = 2
        const val SETTLE_MS = 300L

        /** The old poll loop's 2s settle plus its 5s STOPPED guard, measured from the load. */
        const val POST_LOAD_GUARD_MS = 7_000L

        /** Matches the server monitor's STAGED_STOP_GRACE_S. */
        const val STAGED_STOP_GRACE_MS = 3_000L
        private const val PLAYING = "PLAYING"
        private const val STOPPED = "STOPPED"

        /**
         * True if a TrackURI the renderer echoed back is the URI we gave it.
         * Renderers return it XML-escaped, percent-re-encoded or with the
         * host rewritten. Every minted stream URL carries a unique `token`,
         * so the same path with the same token is the same URI (as the
         * server's `same_media_uri`, which also requires the path here).
         */
        fun sameUri(a: String?, b: String?): Boolean {
            if (a.isNullOrBlank() || b.isNullOrBlank()) return false
            val x = unescapeXml(a.trim())
            val y = unescapeXml(b.trim())
            if (x == y) return true
            val dx = percentDecode(x)
            val dy = percentDecode(y)
            if (dx != null && dx == dy) return true
            val tx = streamToken(x) ?: return false
            val px = decodedPath(x) ?: return false
            return tx == streamToken(y) && px == decodedPath(y)
        }

        private val XML_ENTITY = Regex("&(amp|lt|gt|quot|apos|#\\d+|#[xX][0-9a-fA-F]+);")

        /** One pass, so `&amp;lt;` becomes `&lt;` and not `<`. */
        private fun unescapeXml(s: String): String = XML_ENTITY.replace(s) { m ->
            when (val e = m.groupValues[1]) {
                "amp" -> "&"
                "lt" -> "<"
                "gt" -> ">"
                "quot" -> "\""
                "apos" -> "'"
                else -> {
                    val code = if (e[1] == 'x' || e[1] == 'X') e.substring(2).toIntOrNull(16) else e.substring(1).toIntOrNull()
                    if (code != null && Character.isValidCodePoint(code)) String(Character.toChars(code)) else m.value
                }
            }
        }

        /** Decodes `%XX` escapes only (a `+` stays a `+`); null when malformed. */
        private fun percentDecode(s: String): String? {
            if ('%' !in s) return s
            val out = ByteArrayOutputStream(s.length)
            var i = 0
            while (i < s.length) {
                val c = s[i]
                if (c == '%') {
                    if (i + 2 >= s.length) return null
                    val b = s.substring(i + 1, i + 3).toIntOrNull(16) ?: return null
                    out.write(b)
                    i += 3
                } else {
                    out.write(c.toString().toByteArray(Charsets.UTF_8))
                    i++
                }
            }
            return out.toString(Charsets.UTF_8.name())
        }

        private fun parse(uri: String): URI? = try {
            URI(uri)
        } catch (_: URISyntaxException) {
            null
        }

        private fun decodedPath(uri: String): String? =
            parse(uri)?.rawPath?.takeIf { it.isNotEmpty() }?.let(::percentDecode)

        private fun streamToken(uri: String): String? {
            val query = parse(uri)?.rawQuery ?: return null
            val raw = query.split('&').firstOrNull { it.startsWith("token=") }?.removePrefix("token=")
            return raw?.let(::percentDecode)?.takeIf { it.isNotEmpty() }
        }
    }
}
