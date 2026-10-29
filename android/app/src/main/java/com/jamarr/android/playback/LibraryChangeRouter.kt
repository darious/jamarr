package com.jamarr.android.playback

import com.jamarr.android.data.LibraryChange

/**
 * Maps a [LibraryChange] to the browse cache keys it stales and the folders
 * whose subscribers must be told. Pure Kotlin, so the mapping is unit-tested
 * without a session.
 *
 * Only *affected* folders are notified: a favourite toggle must not make the
 * car refetch Charts. Shared payloads (the Recently Played folders and
 * Recently Added all read `/api/home`) have their key dropped, but a folder
 * whose content did not move is not re-notified.
 */
object LibraryChangeRouter {
    data class Affected(val cacheKeys: Set<String>, val nodeIds: Set<String>)

    fun affected(change: LibraryChange): Affected = when (change) {
        LibraryChange.FavouriteArtists -> Affected(
            cacheKeys = setOf("favourite-artists"),
            nodeIds = setOf(BrowseTree.ID_FAV_ARTISTS),
        )

        LibraryChange.FavouriteReleases -> Affected(
            cacheKeys = setOf("favourite-releases"),
            nodeIds = setOf(BrowseTree.ID_FAV_RELEASES),
        )

        is LibraryChange.Playlist -> Affected(
            cacheKeys = setOf("playlists") + (change.id?.let { setOf("playlist:$it") } ?: emptySet()),
            nodeIds = setOf(BrowseTree.ID_PLAYLISTS) + (change.id?.let { setOf(BrowseTree.playlistId(it)) } ?: emptySet()),
        )

        LibraryChange.History -> Affected(
            cacheKeys = setOf("home", "history-stats", "recent-tracks"),
            nodeIds = setOf(
                BrowseTree.ID_RECENT_ARTISTS,
                BrowseTree.ID_RECENT_ALBUMS,
                BrowseTree.ID_RECENT_TRACKS,
                BrowseTree.ID_HISTORY_ARTISTS,
                BrowseTree.ID_HISTORY_ALBUMS,
            ),
        )
    }

    /** The union for a burst of changes, notified once per folder. */
    fun affected(changes: Collection<LibraryChange>): Affected {
        val keys = mutableSetOf<String>()
        val nodes = mutableSetOf<String>()
        changes.toSet().forEach { c ->
            val a = affected(c)
            keys += a.cacheKeys
            nodes += a.nodeIds
        }
        return Affected(keys, nodes)
    }
}
