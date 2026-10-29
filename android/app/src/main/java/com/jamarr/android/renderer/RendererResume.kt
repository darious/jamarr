package com.jamarr.android.renderer

import java.util.Base64
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * The phone's context for a queue it is driving on a direct (UPnP) renderer,
 * written down so process death does not lose it while the renderer plays on.
 *
 * Only stable identity and resume metadata are stored: track ids and
 * display fields, never stream URLs (their tokens expire; the controller
 * mints fresh ones when it loads or stages a track). [subject] is the JWT
 * subject of the session that wrote it, so a snapshot never follows a
 * different account on the same phone.
 */
@Serializable
data class RendererResumeTrack(
    val id: Long,
    val title: String = "",
    val artist: String = "",
    val album: String = "",
    val durationSeconds: Double = 0.0,
    val artSha1: String? = null,
)

@Serializable
data class RendererResumeSnapshot(
    val rendererId: String,
    val rendererName: String = "",
    val kind: String = "upnp",
    val tracks: List<RendererResumeTrack> = emptyList(),
    val currentIndex: Int = 0,
    val positionSeconds: Double = 0.0,
    val isPlaying: Boolean = false,
    val savedAtMs: Long = 0L,
    val serverUrl: String = "",
    val subject: String? = null,
) {
    val currentTrack: RendererResumeTrack? get() = tracks.getOrNull(currentIndex)

    /** Clamps what an older build or a truncated write may have left; null when there is nothing to resume. */
    fun sanitised(): RendererResumeSnapshot? {
        if (tracks.isEmpty() || rendererId.isBlank() || kind != "upnp") return null
        val index = currentIndex.coerceIn(0, tracks.size - 1)
        val position = positionSeconds.takeIf { it.isFinite() && it >= 0 } ?: 0.0
        return if (index == currentIndex && position == positionSeconds) this else copy(currentIndex = index, positionSeconds = position)
    }

    companion object {
        private val json = Json { ignoreUnknownKeys = true }

        fun encode(snapshot: RendererResumeSnapshot): String = json.encodeToString(snapshot)

        /** Never throws: a corrupt or stale blob means "nothing to resume". */
        fun decode(raw: String?): RendererResumeSnapshot? {
            if (raw.isNullOrBlank()) return null
            return runCatching { json.decodeFromString<RendererResumeSnapshot>(raw) }.getOrNull()?.sanitised()
        }
    }
}

/** What the renderer was doing when the phone came back. */
sealed interface LiveTransport {
    data class Known(
        val trackUri: String?,
        /** `PLAYING`, `PAUSED_PLAYBACK`, `STOPPED`, `NO_MEDIA_PRESENT`, `TRANSITIONING` or null when unknown. */
        val transportState: String?,
        val positionSeconds: Double,
    ) : LiveTransport

    data object Unreachable : LiveTransport
}

/**
 * The decision the user is asked to make. None of these acts on the renderer
 * by itself: the phone never restarts, replaces or stops what a renderer is
 * playing without a tap.
 */
sealed interface ResumeOffer {
    val snapshot: RendererResumeSnapshot

    /** The renderer is still on our current track: pick the queue back up where it is. */
    data class TakeControl(
        override val snapshot: RendererResumeSnapshot,
        val liveUri: String?,
        val positionSeconds: Double,
        val playing: Boolean,
    ) : ResumeOffer

    /** The renderer is idle: load the queue again at the saved track and position. */
    data class Resume(override val snapshot: RendererResumeSnapshot) : ResumeOffer

    /** The renderer plays something that is not ours (another controller, or a later track we did not see). */
    data class Replace(override val snapshot: RendererResumeSnapshot, val liveUri: String?) : ResumeOffer
}

object RendererResumePolicy {
    const val MAX_AGE_MS = 12 * 60 * 60 * 1000L

    private val streamPath = Regex("""/stream/(\d+)(?:[/?#]|$)""")

    /**
     * Whether a stored snapshot is still worth offering: same server, same
     * account, not too old. Anything else is discarded without a prompt.
     */
    fun validate(snapshot: RendererResumeSnapshot?, nowMs: Long, serverUrl: String, subject: String?): RendererResumeSnapshot? {
        val s = snapshot?.sanitised() ?: return null
        if (nowMs - s.savedAtMs > MAX_AGE_MS || s.savedAtMs > nowMs + 60_000L) return null
        if (s.serverUrl.isNotBlank() && serverUrl.isNotBlank() && s.serverUrl.trimEnd('/') != serverUrl.trimEnd('/')) return null
        if (s.subject != null && subject != null && s.subject != subject) return null
        return s
    }

    /** The track id a Jamarr stream URI names, or null for anything else. */
    fun trackIdOf(uri: String?): Long? {
        if (uri.isNullOrBlank()) return null
        val decoded = runCatching { java.net.URLDecoder.decode(uri, "UTF-8") }.getOrDefault(uri)
        return streamPath.find(decoded)?.groupValues?.get(1)?.toLongOrNull()
    }

    /**
     * Matches the live transport against the snapshot. Null means "not now":
     * the renderer could not be queried, so nothing is offered and the
     * snapshot is kept for a later look.
     */
    fun offer(snapshot: RendererResumeSnapshot, live: LiveTransport): ResumeOffer? {
        val s = snapshot.sanitised() ?: return null
        val known = live as? LiveTransport.Known ?: return null
        val liveTrackId = trackIdOf(known.trackUri)
        val active = known.transportState == "PLAYING" || known.transportState == "PAUSED_PLAYBACK" ||
            known.transportState == "TRANSITIONING"
        if (!active || liveTrackId == null && known.trackUri.isNullOrBlank()) {
            // Stopped, or idle with an empty/unknown URI: nothing is lost by loading ours.
            return if (!active) ResumeOffer.Resume(s) else ResumeOffer.Replace(s, known.trackUri)
        }
        val currentId = s.currentTrack?.id
        if (liveTrackId != null && liveTrackId == currentId) {
            return ResumeOffer.TakeControl(s, known.trackUri, known.positionSeconds, playing = known.transportState != "PAUSED_PLAYBACK")
        }
        // Our queue, but a later track than we last saw (the renderer rolled
        // on via a staged next while the phone was dead): pick it up there.
        val index = s.tracks.indexOfFirst { it.id == liveTrackId }
        if (liveTrackId != null && index >= 0) {
            return ResumeOffer.TakeControl(s.copy(currentIndex = index), known.trackUri, known.positionSeconds, playing = known.transportState != "PAUSED_PLAYBACK")
        }
        return ResumeOffer.Replace(s, known.trackUri)
    }
}

/** The one JWT claim the resume logic needs, read without verifying the token. */
object JwtClaims {
    private val sub = Regex(""""sub"\s*:\s*"?([^",}]+)"?""")

    fun subject(token: String?): String? {
        if (token.isNullOrBlank()) return null
        val parts = token.split('.')
        if (parts.size < 2) return null
        val payload = runCatching {
            String(Base64.getUrlDecoder().decode(parts[1].padEnd((parts[1].length + 3) / 4 * 4, '=')), Charsets.UTF_8)
        }.getOrNull() ?: return null
        return sub.find(payload)?.groupValues?.get(1)?.trim()?.takeIf { it.isNotEmpty() }
    }
}
