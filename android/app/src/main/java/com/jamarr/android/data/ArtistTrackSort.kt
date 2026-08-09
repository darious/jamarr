package com.jamarr.android.data

/**
 * Ordering helpers for the artist screen's lists. Shared by the artist screen and
 * the media-browse tree so both present the same order as the web UI.
 *
 * Most Scrobbled and Most Listened keep the server's order (top_track.rank and
 * plays DESC respectively) — the web client does not re-sort them either. Only
 * singles get re-sorted, because the server returns them newest-first.
 *
 * Discography releases arrive from /api/albums in no useful order, so every
 * consumer has to sort them itself.
 */

/** Singles, oldest release first; undated entries last. Stable. */
fun List<ArtistTrackEntry>.sortedSinglesAsc(): List<ArtistTrackEntry> =
    sortedWith(
        compareBy<ArtistTrackEntry> { it.date.isNullOrBlank() }
            .thenBy { it.date ?: "" },
    )

/** Releases, newest first; undated entries last. Stable. */
fun List<AlbumDetail>.sortedReleasesDesc(): List<AlbumDetail> =
    sortedWith(
        compareBy<AlbumDetail> { it.releaseSortKey.isEmpty() }
            .thenByDescending { it.releaseSortKey },
    )

/**
 * Both fields hold an ISO date, so they order lexicographically. `year` is the
 * fallback only because a few rows carry it without a full `release_date`.
 */
private val AlbumDetail.releaseSortKey: String
    get() = releaseDate?.takeIf { it.isNotBlank() } ?: year?.takeIf { it.isNotBlank() } ?: ""
