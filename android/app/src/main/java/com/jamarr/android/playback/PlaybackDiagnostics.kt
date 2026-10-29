package com.jamarr.android.playback

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** One line of the playback diagnostic log. Everything in it is safe to show or copy. */
data class DiagnosticEntry(
    val atMs: Long,
    val trackId: Long,
    val quality: String,
    /** Where the bytes were coming from: `download`, `read-ahead` or `network`. */
    val source: String,
    val kind: PlaybackFailureKind?,
    /** `PlaybackException` error code name, e.g. `ERROR_CODE_IO_NETWORK_CONNECTION_FAILED`. */
    val errorCode: String?,
    val httpStatus: Int?,
    /** Exception text with tokens and signed URLs stripped. */
    val message: String?,
    /** `offline`, `metered` or `unmetered`. */
    val network: String,
    val outputRoute: String?,
    /** What was done about it: `retry 1/3 in 1s`, `skipped`, `gave up`, `recovered`. */
    val stage: String,
)

/**
 * Bounded record of playback failures and what the app did about them.
 *
 * Kept in memory only, newest last, capped at [capacity] entries. Nothing is
 * sent anywhere: [exportText] formats it for the user to copy from the
 * playback-details screen, which is the explicit export path.
 */
class PlaybackDiagnostics(private val capacity: Int = DEFAULT_CAPACITY) {
    private val lock = Any()
    private val ring = ArrayDeque<DiagnosticEntry>()
    private val _entries = MutableStateFlow<List<DiagnosticEntry>>(emptyList())
    val entries: StateFlow<List<DiagnosticEntry>> = _entries.asStateFlow()

    fun record(entry: DiagnosticEntry) {
        synchronized(lock) {
            ring.addLast(entry.copy(message = entry.message?.let(Redaction::scrub)))
            while (ring.size > capacity) ring.removeFirst()
            _entries.value = ring.toList()
        }
    }

    fun clear() {
        synchronized(lock) {
            ring.clear()
            _entries.value = emptyList()
        }
    }

    fun exportText(): String = _entries.value.joinToString("\n") { e ->
        buildString {
            append(e.atMs).append(' ')
            append("track=").append(e.trackId).append(' ')
            append("quality=").append(e.quality).append(' ')
            append("source=").append(e.source).append(' ')
            append("network=").append(e.network).append(' ')
            e.outputRoute?.let { append("route=").append(it).append(' ') }
            e.kind?.let { append("kind=").append(it.name).append(' ') }
            e.errorCode?.let { append("code=").append(it).append(' ') }
            e.httpStatus?.let { append("http=").append(it).append(' ') }
            append("stage=").append(e.stage)
            e.message?.takeIf { it.isNotBlank() }?.let { append(" :: ").append(it) }
        }
    }

    companion object {
        const val DEFAULT_CAPACITY = 40
    }
}

/**
 * Strips credentials out of free text before it is stored or shown.
 *
 * Stream URLs carry a signed `token=` query parameter and API errors can echo
 * an `Authorization` header; neither belongs in a log a user might paste into
 * an issue.
 */
object Redaction {
    private val tokenParam = Regex("""([?&](?:token|access_token|refresh_token)=)[^&\s"']+""", RegexOption.IGNORE_CASE)
    private val bearer = Regex("""(Bearer\s+)[A-Za-z0-9._~+/=-]+""")
    private val jwt = Regex("""\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b""")

    fun scrub(text: String): String = text
        .replace(tokenParam) { m -> m.groupValues[1] + "…" }
        .replace(bearer) { m -> m.groupValues[1] + "…" }
        .replace(jwt, "…")
}
