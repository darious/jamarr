package com.jamarr.android.playback

/**
 * Media id grammar and static shape of the Android Auto browse tree.
 *
 * Deliberately free of Android types so the whole grammar is unit testable on
 * the JVM — [JamarrLibraryProvider] only turns these ids into `MediaItem`s.
 *
 * Grammar (all strings, opaque to clients):
 * ```
 *   root
 *   node:<name>                         static folder, see NODES
 *   artist:<mbid>                       browsable -> grouped albums + singles + top folders
 *   album:<mbid>                        browsable -> tracks
 *   singles:<mbid>                      browsable -> artist's singles tracks
 *   top:<mbid>                          browsable -> artist's most-scrobbled tracks
 *   playlist:<id>                       browsable -> tracks
 *   playall:<parent>                    playable, queues the whole parent from the top
 *   track:<id>|p:<parent>               playable, parent encodes the siblings to queue
 *   track:<id>                          playable, no siblings
 * ```
 */
object BrowseTree {

    const val ID_ROOT = "root"
    const val ID_FAVOURITES = "node:favourites"
    const val ID_FAV_ARTISTS = "node:fav-artists"
    const val ID_FAV_RELEASES = "node:fav-releases"
    const val ID_PLAYLISTS = "node:playlists"
    const val ID_RECENT = "node:recent"
    const val ID_RECENT_ARTISTS = "node:recent-artists"
    const val ID_RECENT_ALBUMS = "node:recent-albums"
    const val ID_RECENT_TRACKS = "node:recent-tracks"
    const val ID_CHARTS = "node:charts"
    const val ID_ADDED = "node:added"
    const val ID_HISTORY = "node:history"
    const val ID_HISTORY_ALBUMS = "node:history-albums"
    const val ID_HISTORY_ARTISTS = "node:history-artists"

    const val PREFIX_ARTIST = "artist:"
    const val PREFIX_ALBUM = "album:"
    const val PREFIX_PLAYLIST = "playlist:"
    const val PREFIX_TRACK = "track:"
    const val PREFIX_SINGLES = "singles:"
    const val PREFIX_TOP = "top:"
    const val PREFIX_PLAY_ALL = "playall:"

    /** Marks the sibling list handed to the player by a "Play all" row. */
    const val ID_TRACK_LIST = "node:track-list"

    const val GROUP_ALBUMS = "Albums"
    const val GROUP_EPS = "EPs"
    const val GROUP_LIVE = "Live"
    const val GROUP_COMPILATIONS = "Compilations"
    const val GROUP_SINGLE_RELEASES = "Single Releases"
    const val GROUP_APPEARS_ON = "Appears On"
    const val GROUP_SINGLES_TRACKS = "Singles"
    const val GROUP_MOST_SCROBBLED = "Most Scrobbled"

    /**
     * Discography section order. "Appears On" is held back until after the
     * synthetic singles/top-track folders, so it is not in the album loop.
     */
    val ALBUM_GROUP_ORDER = listOf(
        GROUP_ALBUMS,
        GROUP_EPS,
        GROUP_LIVE,
        GROUP_COMPILATIONS,
        GROUP_SINGLE_RELEASES,
    )

    /** A static folder: title plus the ids of its (also static) children. */
    data class Node(val id: String, val title: String, val children: List<String> = emptyList())

    private val NODE_LIST = listOf(
        Node(ID_ROOT, "Jamarr", listOf(ID_FAVOURITES, ID_PLAYLISTS, ID_RECENT, ID_CHARTS, ID_HISTORY, ID_ADDED)),
        Node(ID_FAVOURITES, "Favourites", listOf(ID_FAV_ARTISTS, ID_FAV_RELEASES)),
        Node(ID_FAV_ARTISTS, "Artists"),
        Node(ID_FAV_RELEASES, "Releases"),
        Node(ID_PLAYLISTS, "Playlists"),
        Node(ID_RECENT, "Recently Played", listOf(ID_RECENT_ARTISTS, ID_RECENT_ALBUMS, ID_RECENT_TRACKS)),
        Node(ID_RECENT_ARTISTS, "Artists"),
        Node(ID_RECENT_ALBUMS, "Albums"),
        Node(ID_RECENT_TRACKS, "Tracks"),
        Node(ID_CHARTS, "Charts"),
        Node(ID_ADDED, "Recently Added"),
        Node(ID_HISTORY, "History", listOf(ID_HISTORY_ARTISTS, ID_HISTORY_ALBUMS)),
        Node(ID_HISTORY_ARTISTS, "Artists"),
        Node(ID_HISTORY_ALBUMS, "Albums"),
    )

    private val NODES: Map<String, Node> = NODE_LIST.associateBy { it.id }

    /**
     * Every static folder, root included — so `onGetItem` can resolve a node
     * the browser asks about directly (restoring a browse stack), not just the
     * six children of root.
     */
    fun node(id: String): Node? = NODES[id]

    /** Every static folder id, for invalidating the whole tree at once. */
    fun staticNodeIds(): List<String> = NODE_LIST.map { it.id }

    fun artistId(mbid: String): String = "$PREFIX_ARTIST$mbid"

    fun albumId(mbid: String): String = "$PREFIX_ALBUM$mbid"

    fun playlistId(id: Long): String = "$PREFIX_PLAYLIST$id"

    fun singlesId(artistMbid: String): String = "$PREFIX_SINGLES$artistMbid"

    fun topId(artistMbid: String): String = "$PREFIX_TOP$artistMbid"

    fun playAllId(parentId: String): String = "$PREFIX_PLAY_ALL$parentId"

    fun trackId(trackId: Long, parentId: String?): String =
        if (parentId.isNullOrBlank()) "$PREFIX_TRACK$trackId" else "$PREFIX_TRACK$trackId|p:$parentId"

    /** Splits `track:<id>|p:<parent>` into its two halves. */
    fun splitTrackParent(mediaId: String): Pair<String, String?> {
        val pipe = mediaId.indexOf('|')
        if (pipe < 0) return mediaId to null
        val parent = mediaId.substring(pipe + 1).removePrefix("p:").takeIf { it.isNotBlank() }
        return mediaId.substring(0, pipe) to parent
    }

    /** The numeric track id of a `track:` media id, or null for anything else. */
    fun trackIdOf(mediaId: String): Long? {
        if (!mediaId.startsWith(PREFIX_TRACK)) return null
        val (trackPart, _) = splitTrackParent(mediaId)
        return trackPart.removePrefix(PREFIX_TRACK).toLongOrNull()
    }

    fun parentOf(mediaId: String): String? = splitTrackParent(mediaId).second

    /** The folder a "Play all" row plays, e.g. `playall:album:x` -> `album:x`. */
    fun playAllTarget(mediaId: String): String? =
        if (mediaId.startsWith(PREFIX_PLAY_ALL)) {
            mediaId.removePrefix(PREFIX_PLAY_ALL).takeIf { it.isNotBlank() }
        } else {
            null
        }

    fun playlistIdOf(mediaId: String): Long? =
        if (mediaId.startsWith(PREFIX_PLAYLIST)) {
            mediaId.removePrefix(PREFIX_PLAYLIST).toLongOrNull()
        } else {
            null
        }

    /**
     * Applies the browser's page window.
     *
     * Media3 forwards `EXTRA_PAGE`/`EXTRA_PAGE_SIZE` from legacy browsers
     * (Android Auto is one) and only falls back to `(0, MAX_VALUE)` when the
     * browser sends no options — so a provider that ignores them serves the
     * whole list for every page and the car shows duplicates.
     */
    fun <T> page(items: List<T>, page: Int, pageSize: Int): List<T> {
        if (page < 0 || pageSize <= 0) return items
        // Long arithmetic: page * pageSize overflows Int for pageSize=MAX_VALUE.
        val from = page.toLong() * pageSize.toLong()
        if (from >= items.size) return emptyList()
        val to = minOf(from + pageSize.toLong(), items.size.toLong())
        return items.subList(from.toInt(), to.toInt())
    }

    /** Discography section a release belongs to. */
    fun albumGroupTitle(type: String?, releaseType: String?): String {
        if (type.equals("appears_on", ignoreCase = true)) return GROUP_APPEARS_ON
        return when ((releaseType ?: "album").lowercase().trim()) {
            "ep" -> GROUP_EPS
            "live" -> GROUP_LIVE
            "compilation" -> GROUP_COMPILATIONS
            "single" -> GROUP_SINGLE_RELEASES
            else -> GROUP_ALBUMS
        }
    }
}
