package com.jamarr.android.data

/**
 * Ordering helpers for the artist top-track lists. Shared by the artist screen and
 * the media-browse tree so both present the same order as the web UI.
 *
 * Most Scrobbled and Most Listened keep the server's order (top_track.rank and
 * plays DESC respectively) — the web client does not re-sort them either. Only
 * singles get re-sorted, because the server returns them newest-first.
 */

/** Singles, oldest release first; undated entries last. Stable. */
fun List<ArtistTrackEntry>.sortedSinglesAsc(): List<ArtistTrackEntry> =
    sortedWith(
        compareBy<ArtistTrackEntry> { it.date.isNullOrBlank() }
            .thenBy { it.date ?: "" },
    )
