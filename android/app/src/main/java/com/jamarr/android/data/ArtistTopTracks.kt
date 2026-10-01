package com.jamarr.android.data

/**
 * The artist screen's three Top Tracks lists, named once so the screen and the
 * download sync read the same list the same way. A synced download that ordered
 * or filtered differently from the tab it was started on would drift from what
 * the user saw.
 */
enum class TopTrackList(val key: String, val label: String) {
    MostScrobbled("scrobbled", "Most Scrobbled"),
    MostListened("listened", "Most Listened"),
    Singles("singles", "Singles"),
    ;

    companion object {
        fun fromKey(key: String): TopTrackList? = entries.firstOrNull { it.key == key }
    }
}

/** The list as the web UI orders it; see `ArtistTrackSort.kt`. */
fun ArtistDetail.topTrackEntries(list: TopTrackList): List<ArtistTrackEntry> = when (list) {
    TopTrackList.MostScrobbled -> topTracks
    TopTrackList.MostListened -> mostListened
    TopTrackList.Singles -> singles.sortedSinglesAsc()
}

/**
 * Null when the library does not hold the track: the top-tracks lists come from
 * Last.fm and the server's history, so they can name tracks with no local file.
 */
fun ArtistTrackEntry.toSearchTrack(artistName: String): SearchTrack? {
    val id = localTrackId ?: return null
    return SearchTrack(
        id = id,
        title = displayTitle,
        artist = artistName,
        album = album,
        durationSeconds = durationSeconds,
        artSha1 = artSha1,
        mbReleaseId = mbReleaseId,
    )
}
