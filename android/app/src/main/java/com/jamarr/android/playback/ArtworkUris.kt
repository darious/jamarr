package com.jamarr.android.playback

/**
 * The `content://` grammar [ArtworkContentProvider] serves, kept free of
 * Android types so validation is unit-tested on the JVM:
 *
 * ```
 *   content://<authority>/art/<sha1>                 one artwork, by hash
 *   content://<authority>/grid/<sha1>,<sha1>[,…]     a 2x2 composite of up to four
 * ```
 *
 * A hash is 40 lowercase hex characters, nothing else: there is no path, no
 * URL and no size in the URI, so a caller holding a grant can only ever ask
 * for artwork the library already identifies by hash.
 */
object ArtworkUris {
    const val PATH_ART = "art"
    const val PATH_GRID = "grid"
    const val MAX_GRID_TILES = 4

    private val sha1 = Regex("^[0-9a-f]{40}$")

    sealed interface Request {
        data class Art(val sha1: String) : Request
        data class Grid(val sha1s: List<String>) : Request
    }

    fun isSha1(value: String): Boolean = sha1.matches(value)

    /** `art/<sha>` or `grid/<a,b,c,d>` from the URI's path segments; null for anything else. */
    fun parse(segments: List<String>): Request? {
        if (segments.size != 2) return null
        val (kind, arg) = segments
        return when (kind) {
            PATH_ART -> arg.lowercase().takeIf(::isSha1)?.let { Request.Art(it) }
            PATH_GRID -> {
                val shas = arg.lowercase().split(',').filter { it.isNotBlank() }.distinct()
                if (shas.isEmpty() || shas.size > MAX_GRID_TILES || !shas.all(::isSha1)) null else Request.Grid(shas)
            }
            else -> null
        }
    }

    fun artPath(sha1: String): String = "$PATH_ART/${sha1.lowercase()}"

    /** Takes the first [MAX_GRID_TILES] distinct hashes, in order, so a folder keeps one cover. */
    fun gridPath(sha1s: List<String>): String? {
        val shas = sha1s.map { it.lowercase() }.filter(::isSha1).distinct().take(MAX_GRID_TILES)
        return if (shas.isEmpty()) null else "$PATH_GRID/${shas.joinToString(",")}"
    }

    /** Cache file name for a grid; stable for the same tiles in the same order. */
    fun gridCacheName(sha1s: List<String>): String = "grid-" + sha1s.joinToString("-") { it.take(12) }
}
