@file:OptIn(UnstableApi::class)

package com.jamarr.android.playback

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Rect
import android.net.Uri
import android.os.Bundle
import android.util.Log
import androidx.annotation.OptIn
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.LibraryResult
import androidx.media3.session.MediaLibraryService.LibraryParams
import androidx.media3.session.MediaLibraryService.MediaLibrarySession
import androidx.media3.session.MediaSession
import androidx.media3.session.SessionError
import com.google.common.collect.ImmutableList
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import com.jamarr.android.data.AlbumDetail
import com.jamarr.android.data.ArtistDetail
import com.jamarr.android.data.ArtistTrackEntry
import com.jamarr.android.data.HistoryStats
import com.jamarr.android.data.HomeContent
import com.jamarr.android.data.JamarrApiClient
import com.jamarr.android.data.JamarrApiException
import com.jamarr.android.data.PlaylistDetail
import com.jamarr.android.data.PlaylistSummary
import com.jamarr.android.data.SearchTrack
import com.jamarr.android.data.sortedReleasesDesc
import com.jamarr.android.data.sortedSinglesAsc
import java.io.ByteArrayOutputStream
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.guava.future
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit

/**
 * Browse tree + tap-to-play for Android Auto.
 *
 * The media id grammar and the static folder layout live in [BrowseTree]; this
 * class turns those ids into `MediaItem`s and answers the session callbacks.
 *
 * Two rules shape the code:
 *
 * - **Content is fetched as rows, not as items.** A node builds a light
 *   [Row] list first, the browser's page window is applied, and only that page
 *   is turned into `MediaItem`s. Artwork — the expensive part — is therefore
 *   only ever fetched for items the car actually asked for.
 * - **Failures are errors, not empty folders.** A node that cannot load
 *   returns a `LibraryResult` error so the car can say so and retry, instead
 *   of rendering an empty list that looks like an empty library.
 */
class JamarrLibraryProvider(
    private val apiClient: JamarrApiClient,
    private val credentials: suspend () -> Credentials,
    private val scope: CoroutineScope,
    cacheTtlMs: Long = CACHE_TTL_MS,
) {
    /** Server + token, resolved once the service has finished loading settings. */
    data class Credentials(val serverUrl: String, val token: String) {
        val authenticated: Boolean get() = serverUrl.isNotBlank() && token.isNotBlank()
    }

    /**
     * Set by the service once the session exists, so content changes can be
     * pushed to subscribed browsers.
     */
    @Volatile
    var session: MediaLibrarySession? = null

    private val cache = TtlCache(cacheTtlMs)

    /** Bounds artwork fan-out; OkHttp queues past 5 per host anyway. */
    private val artworkGate = Semaphore(ARTWORK_CONCURRENCY)

    /**
     * Thin adapter over the suspend functions below.
     *
     * The session and controller arguments are not used by any of these, which
     * is what lets the browse behaviour be exercised directly in tests without
     * standing up a session and a player.
     */
    val callback: MediaLibrarySession.Callback = object : MediaLibrarySession.Callback {

        override fun onGetLibraryRoot(
            session: MediaLibrarySession,
            browser: MediaSession.ControllerInfo,
            params: LibraryParams?,
        ): ListenableFuture<LibraryResult<MediaItem>> =
            Futures.immediateFuture(rootResult(params))

        override fun onGetItem(
            session: MediaLibrarySession,
            browser: MediaSession.ControllerInfo,
            mediaId: String,
        ): ListenableFuture<LibraryResult<MediaItem>> = scope.future { itemResult(mediaId) }

        override fun onGetChildren(
            session: MediaLibrarySession,
            browser: MediaSession.ControllerInfo,
            parentId: String,
            page: Int,
            pageSize: Int,
            params: LibraryParams?,
        ): ListenableFuture<LibraryResult<ImmutableList<MediaItem>>> = scope.future {
            childrenResult(parentId, page, pageSize, params)
        }

        /**
         * Resolve only.
         *
         * Sibling expansion belongs to [onSetMediaItems]: "add to queue" of a
         * single track must add one track, not the album it came from.
         */
        override fun onAddMediaItems(
            mediaSession: MediaSession,
            controller: MediaSession.ControllerInfo,
            mediaItems: List<MediaItem>,
        ): ListenableFuture<List<MediaItem>> = scope.future { resolveForQueue(mediaItems) }

        override fun onSetMediaItems(
            mediaSession: MediaSession,
            controller: MediaSession.ControllerInfo,
            mediaItems: List<MediaItem>,
            startIndex: Int,
            startPositionMs: Long,
        ): ListenableFuture<MediaSession.MediaItemsWithStartPosition> = scope.future {
            val (items, resolvedStart) = expandForPlayback(mediaItems)
            val safeStart = resolvedStart ?: startIndex.coerceIn(0, (items.size - 1).coerceAtLeast(0))
            MediaSession.MediaItemsWithStartPosition(items, safeStart, startPositionMs)
        }
    }

    /**
     * Makes items playable without changing what was asked for — adding one
     * track to the queue must add exactly that track.
     */
    fun resolveForQueue(mediaItems: List<MediaItem>): List<MediaItem> =
        mediaItems.map { fillTrackUri(it) }

    fun rootResult(params: LibraryParams? = null): LibraryResult<MediaItem> =
        LibraryResult.ofItem(browsableNode(BrowseTree.ID_ROOT), params)

    suspend fun itemResult(mediaId: String): LibraryResult<MediaItem> {
        val item = try {
            buildItem(mediaId)
        } catch (e: Exception) {
            Log.w(TAG, "Failed to load item $mediaId", e)
            return LibraryResult.ofError(errorCodeFor(e))
        }
        return if (item != null) {
            LibraryResult.ofItem(item, null)
        } else {
            LibraryResult.ofError(SessionError.ERROR_BAD_VALUE)
        }
    }

    suspend fun childrenResult(
        parentId: String,
        page: Int,
        pageSize: Int,
        params: LibraryParams? = null,
    ): LibraryResult<ImmutableList<MediaItem>> {
        val creds = credentials()
        if (!creds.authenticated) {
            return LibraryResult.ofItemList(ImmutableList.of(signInPlaceholder()), params)
        }
        val rows = try {
            rowsFor(parentId, creds)
        } catch (e: Exception) {
            // An empty list here would render as an empty library; the browser
            // can only offer a retry if it is told this was a failure.
            Log.w(TAG, "Failed to load children of $parentId", e)
            return LibraryResult.ofError(errorCodeFor(e))
        }
        val window = BrowseTree.page(rows, page, pageSize)
        return LibraryResult.ofItemList(
            ImmutableList.copyOf(buildItems(window, creds, forBrowse = true)),
            params,
        )
    }

    /**
     * Re-publishes the tree after a sign-in, sign-out or server change.
     *
     * Browsers cache subscription results, so without this the car keeps
     * showing "Sign in on phone" until it is disconnected and reconnected.
     */
    fun onSessionChanged() {
        scope.launch(Dispatchers.Main) {
            cache.invalidateAll()
            val current = session ?: return@launch
            for (id in BrowseTree.staticNodeIds()) {
                runCatching { current.notifyChildrenChanged(id, Int.MAX_VALUE, null) }
                    .onFailure { Log.w(TAG, "notifyChildrenChanged($id) failed", it) }
            }
        }
    }

    // ----- rows ---------------------------------------------------------

    /**
     * One browse entry, before any artwork or `MediaItem` exists.
     *
     * Rows are cheap enough to build (and cache) for a whole node; items are
     * not, which is what makes paging worth applying between the two.
     */
    private data class Row(
        val mediaId: String,
        val title: String,
        val browsable: Boolean,
        val mediaType: Int,
        val subtitle: String? = null,
        val artist: String? = null,
        val album: String? = null,
        val artSha1: String? = null,
        /** Sources for a composite folder cover, most relevant first. */
        val artShas: List<String> = emptyList(),
        val group: String? = null,
        val trackId: Long? = null,
        val durationMs: Long? = null,
    )

    private suspend fun rowsFor(parentId: String, creds: Credentials): List<Row> = when (parentId) {
        BrowseTree.ID_ROOT,
        BrowseTree.ID_FAVOURITES,
        BrowseTree.ID_RECENT,
        BrowseTree.ID_HISTORY,
        -> staticChildRows(parentId)

        BrowseTree.ID_FAV_ARTISTS -> favouriteArtistRows(creds)
        BrowseTree.ID_FAV_RELEASES -> favouriteReleaseRows(creds)
        BrowseTree.ID_PLAYLISTS -> playlistRows(creds)
        BrowseTree.ID_RECENT_ARTISTS -> recentArtistRows(creds)
        BrowseTree.ID_RECENT_ALBUMS -> recentAlbumRows(creds)
        BrowseTree.ID_RECENT_TRACKS -> recentTrackRows(creds)
        BrowseTree.ID_CHARTS -> chartRows(creds)
        BrowseTree.ID_ADDED -> recentlyAddedRows(creds)
        BrowseTree.ID_HISTORY_ALBUMS -> historyAlbumRows(creds)
        BrowseTree.ID_HISTORY_ARTISTS -> historyArtistRows(creds)

        else -> when {
            parentId.startsWith(BrowseTree.PREFIX_ARTIST) ->
                artistRows(parentId.removePrefix(BrowseTree.PREFIX_ARTIST), creds)

            parentId.startsWith(BrowseTree.PREFIX_ALBUM) ->
                withPlayAll(parentId, albumTrackRows(parentId.removePrefix(BrowseTree.PREFIX_ALBUM), parentId, creds))

            parentId.startsWith(BrowseTree.PREFIX_SINGLES) ->
                withPlayAll(parentId, singlesTrackRows(parentId.removePrefix(BrowseTree.PREFIX_SINGLES), creds))

            parentId.startsWith(BrowseTree.PREFIX_TOP) ->
                withPlayAll(parentId, topTrackRows(parentId.removePrefix(BrowseTree.PREFIX_TOP), creds))

            parentId.startsWith(BrowseTree.PREFIX_PLAYLIST) -> {
                val id = BrowseTree.playlistIdOf(parentId) ?: return emptyList()
                withPlayAll(parentId, playlistTrackRows(id, creds))
            }

            else -> emptyList()
        }
    }

    private fun staticChildRows(parentId: String): List<Row> =
        BrowseTree.node(parentId)?.children.orEmpty().mapNotNull { childId ->
            BrowseTree.node(childId)?.let { child ->
                Row(
                    mediaId = child.id,
                    title = child.title,
                    browsable = true,
                    mediaType = MediaMetadata.MEDIA_TYPE_FOLDER_MIXED,
                )
            }
        }

    /** Prepends the "Play all" row to a folder of tracks. */
    private fun withPlayAll(parentId: String, tracks: List<Row>): List<Row> {
        if (tracks.isEmpty()) return tracks
        val playAll = Row(
            mediaId = BrowseTree.playAllId(parentId),
            title = PLAY_ALL_TITLE,
            browsable = false,
            mediaType = MediaMetadata.MEDIA_TYPE_MUSIC,
            subtitle = trackCountLabel(tracks.size),
            artShas = tracks.mapNotNull { it.artSha1 },
        )
        return listOf(playAll) + tracks
    }

    // ----- data-backed rows ---------------------------------------------

    private suspend fun favouriteArtistRows(creds: Credentials): List<Row> =
        cache.get("favourite-artists") { apiClient.favoriteArtists(creds.serverUrl, creds.token) }
            .filter { it.mbid.isNotBlank() }
            .map { artistRow(mbid = it.mbid, name = it.name, artSha1 = it.artSha1) }

    private suspend fun favouriteReleaseRows(creds: Credentials): List<Row> =
        cache.get("favourite-releases") { apiClient.favoriteReleases(creds.serverUrl, creds.token) }
            .sortedByDescending { it.year ?: "" }
            .filter { it.albumMbid.isNotBlank() }
            .map {
                albumRow(
                    albumMbid = it.albumMbid,
                    title = it.title,
                    artist = it.artistName,
                    year = it.year,
                    artSha1 = it.artSha1,
                )
            }

    private suspend fun playlistRows(creds: Credentials): List<Row> =
        cache.get("playlists") { apiClient.playlists(creds.serverUrl, creds.token) }
            .map { playlistRow(it) }

    private suspend fun recentArtistRows(creds: Credentials): List<Row> =
        home(creds).recentlyPlayedArtists
            .filter { !it.mbid.isNullOrBlank() }
            .map { artistRow(mbid = it.mbid!!, name = it.name, artSha1 = it.artSha1) }

    private suspend fun recentAlbumRows(creds: Credentials): List<Row> =
        home(creds).recentlyPlayedAlbums.mapNotNull { a ->
            val mbid = a.albumMbid ?: a.mbReleaseId ?: a.mbid ?: return@mapNotNull null
            albumRow(
                albumMbid = mbid,
                title = a.album,
                artist = a.artistName,
                year = a.year,
                artSha1 = a.artSha1,
            )
        }

    private suspend fun recentlyAddedRows(creds: Credentials): List<Row> =
        home(creds).recentlyAddedAlbums.mapNotNull { a ->
            val mbid = a.albumMbid ?: a.mbReleaseId ?: a.mbid ?: return@mapNotNull null
            albumRow(
                albumMbid = mbid,
                title = a.album,
                artist = a.artistName,
                year = a.year,
                artSha1 = a.artSha1,
            )
        }

    private suspend fun recentTrackRows(creds: Credentials): List<Row> =
        recentTracks(creds).map { trackRow(it, BrowseTree.ID_RECENT_TRACKS) }

    private suspend fun chartRows(creds: Credentials): List<Row> =
        cache.get("chart") { apiClient.chart(creds.serverUrl, creds.token) }
            .filter { it.inLibrary }
            .mapNotNull { c ->
                val mbid = c.localAlbumMbid ?: c.releaseMbid ?: c.releaseGroupMbid
                    ?: return@mapNotNull null
                albumRow(
                    albumMbid = mbid,
                    title = "${c.position}. ${c.localTitle ?: c.title}",
                    artist = c.localArtist ?: c.artist,
                    year = null,
                    artSha1 = c.artSha1,
                )
            }

    private suspend fun historyAlbumRows(creds: Credentials): List<Row> =
        historyStats(creds).albums.mapNotNull { a ->
            val mbid = a.mbReleaseId ?: return@mapNotNull null
            albumRow(
                albumMbid = mbid,
                title = a.displayTitle,
                artist = a.artist,
                year = null,
                artSha1 = a.artSha1,
            )
        }

    private suspend fun historyArtistRows(creds: Credentials): List<Row> =
        historyStats(creds).artists.mapNotNull { a ->
            val mbid = a.resolvedMbid?.takeIf { it.isNotBlank() } ?: return@mapNotNull null
            artistRow(mbid = mbid, name = a.displayName, artSha1 = a.artSha1)
        }

    private suspend fun artistRows(mbid: String, creds: Credentials): List<Row> {
        if (mbid.isBlank()) return emptyList()
        val (detail, rawAlbums) = coroutineScope {
            val d = async { artistDetail(mbid, creds) }
            val a = async {
                cache.get("artist-albums:$mbid") {
                    apiClient.artistAlbums(creds.serverUrl, creds.token, mbid)
                }
            }
            d.await() to a.await()
        }

        val grouped = rawAlbums.groupBy { BrowseTree.albumGroupTitle(it.type, it.releaseType) }
        val singles = detail?.singleTracks().orEmpty()
        val top = detail?.topTrackList().orEmpty()

        val rows = mutableListOf<Row>()
        for (group in BrowseTree.ALBUM_GROUP_ORDER) {
            val list = grouped[group] ?: continue
            rows += list.sortedReleasesDesc().mapNotNull { albumGroupRow(it, group) }
        }
        if (singles.isNotEmpty()) {
            rows += trackFolderRow(
                mediaId = BrowseTree.singlesId(mbid),
                title = BrowseTree.GROUP_SINGLES_TRACKS,
                artist = detail?.name,
                tracks = singles,
            )
        }
        if (top.isNotEmpty()) {
            rows += trackFolderRow(
                mediaId = BrowseTree.topId(mbid),
                title = BrowseTree.GROUP_MOST_SCROBBLED,
                artist = detail?.name,
                tracks = top,
            )
        }
        // Held back so it lands after the synthetic track folders.
        grouped[BrowseTree.GROUP_APPEARS_ON]?.let { list ->
            rows += list.sortedReleasesDesc().mapNotNull {
                albumGroupRow(it, BrowseTree.GROUP_APPEARS_ON)
            }
        }
        return rows
    }

    private suspend fun albumTrackRows(mbid: String, parentId: String, creds: Credentials): List<Row> {
        if (mbid.isBlank()) return emptyList()
        return albumTracks(mbid, creds).map { trackRow(it, parentId) }
    }

    private suspend fun playlistTrackRows(playlistId: Long, creds: Credentials): List<Row> {
        val parentId = BrowseTree.playlistId(playlistId)
        return playlistDetail(playlistId, creds).tracks.map { t ->
            Row(
                mediaId = BrowseTree.trackId(t.trackId, parentId),
                title = t.title,
                browsable = false,
                mediaType = MediaMetadata.MEDIA_TYPE_MUSIC,
                artist = t.artist,
                album = t.album,
                artSha1 = t.artSha1,
                trackId = t.trackId,
                durationMs = t.durationSeconds.toMillis(),
            )
        }
    }

    private suspend fun singlesTrackRows(artistMbid: String, creds: Credentials): List<Row> =
        artistSinglesTracks(artistMbid, creds).map { trackRow(it, BrowseTree.singlesId(artistMbid)) }

    private suspend fun topTrackRows(artistMbid: String, creds: Credentials): List<Row> =
        artistTopTracks(artistMbid, creds).map { trackRow(it, BrowseTree.topId(artistMbid)) }

    // ----- cached API reads ---------------------------------------------
    //
    // Sibling nodes share payloads: the three Recently Played folders and
    // Recently Added are one /api/home response, and an artist's discography,
    // Singles and Most Scrobbled folders are one artist detail.

    private suspend fun home(creds: Credentials): HomeContent =
        cache.get("home") { apiClient.home(creds.serverUrl, creds.token, limit = HOME_LIMIT) }

    private suspend fun historyStats(creds: Credentials): HistoryStats =
        cache.get("history-stats") { apiClient.historyStats(creds.serverUrl, creds.token) }

    private suspend fun artistDetail(mbid: String, creds: Credentials): ArtistDetail? =
        cache.get("artist:$mbid") {
            ArtistDetailHolder(apiClient.artistDetail(creds.serverUrl, creds.token, mbid = mbid))
        }.value

    private suspend fun albumTracks(mbid: String, creds: Credentials): List<SearchTrack> =
        cache.get("album-tracks:$mbid") {
            apiClient.albumTracks(creds.serverUrl, creds.token, albumMbid = mbid)
        }

    private suspend fun playlistDetail(id: Long, creds: Credentials): PlaylistDetail =
        cache.get("playlist:$id") { apiClient.playlistDetail(creds.serverUrl, creds.token, id) }

    private suspend fun recentTracks(creds: Credentials): List<SearchTrack> =
        cache.get("recent-tracks") {
            apiClient.recentlyPlayedTracks(creds.serverUrl, creds.token, limit = RECENT_TRACK_LIMIT)
        }

    private suspend fun artistSinglesTracks(mbid: String, creds: Credentials): List<SearchTrack> {
        if (mbid.isBlank()) return emptyList()
        return artistDetail(mbid, creds)?.singleTracks().orEmpty()
    }

    private suspend fun artistTopTracks(mbid: String, creds: Credentials): List<SearchTrack> {
        if (mbid.isBlank()) return emptyList()
        return artistDetail(mbid, creds)?.topTrackList().orEmpty()
    }

    /** `TtlCache` stores non-null values; artist detail is legitimately nullable. */
    private class ArtistDetailHolder(val value: ArtistDetail?)

    private fun ArtistDetail.singleTracks(): List<SearchTrack> =
        singles.sortedSinglesAsc().mapNotNull { it.toSearchTrack(name) }

    /** Server order is `top_track.rank`, matching the web UI and artist screen. */
    private fun ArtistDetail.topTrackList(): List<SearchTrack> =
        topTracks.mapNotNull { it.toSearchTrack(name) }

    private fun ArtistTrackEntry.toSearchTrack(artistName: String): SearchTrack? {
        val tid = localTrackId ?: return null
        return SearchTrack(
            id = tid,
            title = displayTitle,
            artist = artistName,
            album = album,
            mbReleaseId = mbReleaseId,
            durationSeconds = durationSeconds,
            artSha1 = artSha1,
        )
    }

    // ----- row builders --------------------------------------------------

    private fun artistRow(mbid: String, name: String, artSha1: String?) = Row(
        mediaId = BrowseTree.artistId(mbid),
        title = name,
        browsable = true,
        mediaType = MediaMetadata.MEDIA_TYPE_ARTIST,
        artSha1 = artSha1,
    )

    private fun albumRow(
        albumMbid: String,
        title: String,
        artist: String?,
        year: String?,
        artSha1: String?,
        group: String? = null,
    ) = Row(
        mediaId = BrowseTree.albumId(albumMbid),
        title = title,
        browsable = true,
        mediaType = MediaMetadata.MEDIA_TYPE_ALBUM,
        subtitle = listOfNotNull(artist?.takeIf { it.isNotBlank() }, year?.takeIf { it.isNotBlank() })
            .joinToString(" • ")
            .takeIf { it.isNotBlank() },
        artist = artist,
        album = title,
        artSha1 = artSha1,
        group = group,
    )

    private fun albumGroupRow(album: AlbumDetail, group: String): Row? {
        val mbid = album.albumMbid ?: album.mbReleaseId ?: return null
        return albumRow(
            albumMbid = mbid,
            title = album.album,
            artist = album.artistName,
            year = album.year,
            artSha1 = album.artSha1,
            group = group,
        )
    }

    private fun playlistRow(playlist: PlaylistSummary) = Row(
        mediaId = BrowseTree.playlistId(playlist.id),
        title = playlist.name,
        browsable = true,
        mediaType = MediaMetadata.MEDIA_TYPE_PLAYLIST,
        subtitle = trackCountLabel(playlist.trackCount),
        artShas = playlist.thumbnails,
    )

    private fun trackFolderRow(
        mediaId: String,
        title: String,
        artist: String?,
        tracks: List<SearchTrack>,
    ) = Row(
        mediaId = mediaId,
        title = title,
        browsable = true,
        mediaType = MediaMetadata.MEDIA_TYPE_ALBUM,
        subtitle = trackCountLabel(tracks.size),
        artist = artist,
        album = title,
        artShas = tracks.mapNotNull { it.artSha1 },
        group = title,
    )

    private fun trackRow(track: SearchTrack, parentId: String?) = Row(
        mediaId = BrowseTree.trackId(track.id, parentId),
        title = track.title,
        browsable = false,
        mediaType = MediaMetadata.MEDIA_TYPE_MUSIC,
        artist = track.artist,
        album = track.album,
        artSha1 = track.artSha1,
        trackId = track.id,
        durationMs = track.durationSeconds.toMillis(),
    )

    private fun trackCountLabel(count: Int): String? = when {
        count <= 0 -> null
        count == 1 -> "1 track"
        else -> "$count tracks"
    }

    private fun Double?.toMillis(): Long? =
        this?.takeIf { it > 0 }?.let { (it * 1000).toLong() }

    // ----- single-item lookup --------------------------------------------

    private suspend fun buildItem(mediaId: String): MediaItem? {
        BrowseTree.node(mediaId)?.let { return browsableNode(mediaId) }
        val creds = credentials()
        return when {
            mediaId.startsWith(BrowseTree.PREFIX_TRACK) -> reconstructTrackItem(mediaId, creds)

            mediaId.startsWith(BrowseTree.PREFIX_ALBUM) -> {
                val mbid = mediaId.removePrefix(BrowseTree.PREFIX_ALBUM)
                val tracks = if (creds.authenticated) albumTracks(mbid, creds) else emptyList()
                val first = tracks.firstOrNull()
                buildItem(
                    albumRow(
                        albumMbid = mbid,
                        title = first?.album ?: "Album",
                        artist = first?.artist,
                        year = null,
                        artSha1 = first?.artSha1,
                    ),
                    creds,
                    forBrowse = false,
                    artBytes = null,
                )
            }

            mediaId.startsWith(BrowseTree.PREFIX_PLAYLIST) -> {
                val id = BrowseTree.playlistIdOf(mediaId) ?: return null
                val detail = if (creds.authenticated) playlistDetail(id, creds) else null
                buildItem(
                    Row(
                        mediaId = mediaId,
                        title = detail?.name ?: "Playlist",
                        browsable = true,
                        mediaType = MediaMetadata.MEDIA_TYPE_PLAYLIST,
                        subtitle = trackCountLabel(detail?.trackCount ?: 0),
                        artShas = detail?.tracks.orEmpty().mapNotNull { it.artSha1 },
                    ),
                    creds,
                    forBrowse = false,
                    artBytes = null,
                )
            }

            mediaId.startsWith(BrowseTree.PREFIX_ARTIST) -> {
                val mbid = mediaId.removePrefix(BrowseTree.PREFIX_ARTIST)
                val detail = if (creds.authenticated) artistDetail(mbid, creds) else null
                buildItem(
                    artistRow(mbid = mbid, name = detail?.name ?: "Artist", artSha1 = detail?.artSha1),
                    creds,
                    forBrowse = false,
                    artBytes = null,
                )
            }

            mediaId.startsWith(BrowseTree.PREFIX_SINGLES) -> folderItem(
                mediaId,
                BrowseTree.GROUP_SINGLES_TRACKS,
                artistSinglesTracks(mediaId.removePrefix(BrowseTree.PREFIX_SINGLES), creds),
                creds,
            )

            mediaId.startsWith(BrowseTree.PREFIX_TOP) -> folderItem(
                mediaId,
                BrowseTree.GROUP_MOST_SCROBBLED,
                artistTopTracks(mediaId.removePrefix(BrowseTree.PREFIX_TOP), creds),
                creds,
            )

            mediaId.startsWith(BrowseTree.PREFIX_PLAY_ALL) -> buildItem(
                Row(
                    mediaId = mediaId,
                    title = PLAY_ALL_TITLE,
                    browsable = false,
                    mediaType = MediaMetadata.MEDIA_TYPE_MUSIC,
                ),
                creds,
                forBrowse = false,
                artBytes = null,
            )

            else -> null
        }
    }

    private suspend fun folderItem(
        mediaId: String,
        title: String,
        tracks: List<SearchTrack>,
        creds: Credentials,
    ): MediaItem = buildItem(
        trackFolderRow(mediaId = mediaId, title = title, artist = null, tracks = tracks),
        creds,
        forBrowse = false,
        artBytes = null,
    )

    private fun browsableNode(id: String): MediaItem {
        val node = BrowseTree.node(id) ?: BrowseTree.Node(id, id)
        return MediaItem.Builder()
            .setMediaId(node.id)
            .setMediaMetadata(
                MediaMetadata.Builder()
                    .setTitle(node.title)
                    .setIsBrowsable(true)
                    .setIsPlayable(false)
                    .setMediaType(MediaMetadata.MEDIA_TYPE_FOLDER_MIXED)
                    .build(),
            )
            .build()
    }

    private fun signInPlaceholder(): MediaItem = MediaItem.Builder()
        .setMediaId(ID_SIGN_IN)
        .setMediaMetadata(
            MediaMetadata.Builder()
                .setTitle("Sign in on phone to use Jamarr")
                .setIsBrowsable(false)
                .setIsPlayable(false)
                .build(),
        )
        .build()

    /**
     * Rebuilds a track item from its id alone.
     *
     * Reached when a browser resolves a stored media id (playback resumption,
     * a restored browse stack). The cached sibling list usually still holds the
     * metadata, so the now-playing screen is not left blank.
     */
    private suspend fun reconstructTrackItem(mediaId: String, creds: Credentials): MediaItem {
        val trackId = BrowseTree.trackIdOf(mediaId) ?: 0L
        val parent = BrowseTree.parentOf(mediaId)
        val known = if (creds.authenticated && parent != null) {
            runCatching { siblingTracks(parent, creds) }.getOrNull()
                ?.firstOrNull { it.id == trackId }
        } else {
            null
        }
        val row = known?.let { trackRow(it, parent) }
            ?: Row(
                mediaId = mediaId,
                title = "",
                browsable = false,
                mediaType = MediaMetadata.MEDIA_TYPE_MUSIC,
                trackId = trackId,
            )
        return buildItem(row.copy(mediaId = mediaId), creds, forBrowse = false, artBytes = null)
    }

    // ----- tap-to-play expansion -----------------------------------------

    data class Expansion(val items: List<MediaItem>, val startIndex: Int?)

    suspend fun expandForPlayback(incoming: List<MediaItem>): Expansion {
        if (incoming.isEmpty()) return Expansion(emptyList(), null)
        if (incoming.size > 1) {
            // Several items handed over at once — the controller picks the start.
            return Expansion(incoming.map { fillTrackUri(it) }, null)
        }
        val single = incoming.first()
        val mediaId = single.mediaId
        // Voice search arrives as an item with a query and no media id. Search
        // is not implemented; failing here tells the caller so, where handing
        // the player a URI-less item would just break playback silently.
        if (!single.requestMetadata.searchQuery.isNullOrBlank() && mediaId.isBlank()) {
            throw UnsupportedOperationException("Search is not supported")
        }
        val creds = credentials()
        if (!creds.authenticated) return Expansion(listOf(fillTrackUri(single)), 0)

        return runCatching {
            when {
                mediaId.startsWith(BrowseTree.PREFIX_PLAY_ALL) -> {
                    val target = BrowseTree.playAllTarget(mediaId)
                        ?: return@runCatching Expansion(emptyList(), null)
                    val tracks = siblingTracks(target, creds)
                    Expansion(queueItems(tracks, target, creds), if (tracks.isEmpty()) null else 0)
                }

                mediaId.startsWith(BrowseTree.PREFIX_TRACK) -> expandTrack(single, creds)

                mediaId.startsWith(BrowseTree.PREFIX_ALBUM) ||
                    mediaId.startsWith(BrowseTree.PREFIX_PLAYLIST) ||
                    mediaId.startsWith(BrowseTree.PREFIX_SINGLES) ||
                    mediaId.startsWith(BrowseTree.PREFIX_TOP) -> {
                    val tracks = siblingTracks(mediaId, creds)
                    Expansion(queueItems(tracks, mediaId, creds), if (tracks.isEmpty()) null else 0)
                }

                else -> Expansion(listOf(fillTrackUri(single)), 0)
            }
        }.getOrElse { e ->
            Log.w(TAG, "Failed to expand $mediaId for playback", e)
            Expansion(listOf(fillTrackUri(single)), 0)
        }
    }

    private suspend fun expandTrack(item: MediaItem, creds: Credentials): Expansion {
        val trackId = BrowseTree.trackIdOf(item.mediaId)
            ?: return Expansion(listOf(fillTrackUri(item)), 0)
        val parent = BrowseTree.parentOf(item.mediaId)
            ?: return Expansion(listOf(fillTrackUri(item)), 0)
        val siblings = siblingTracks(parent, creds)
        val index = siblings.indexOfFirst { it.id == trackId }
        if (siblings.isEmpty() || index < 0) return Expansion(listOf(fillTrackUri(item)), 0)
        return Expansion(queueItems(siblings, parent, creds), index)
    }

    /** The track list a media id queues, or empty when it queues nothing. */
    private suspend fun siblingTracks(parentId: String, creds: Credentials): List<SearchTrack> = when {
        parentId.startsWith(BrowseTree.PREFIX_ALBUM) ->
            albumTracks(parentId.removePrefix(BrowseTree.PREFIX_ALBUM), creds)

        parentId.startsWith(BrowseTree.PREFIX_PLAYLIST) ->
            BrowseTree.playlistIdOf(parentId)?.let { id ->
                playlistDetail(id, creds).tracks.map { t ->
                    SearchTrack(
                        id = t.trackId,
                        title = t.title,
                        artist = t.artist,
                        album = t.album,
                        durationSeconds = t.durationSeconds,
                        artSha1 = t.artSha1,
                    )
                }
            }.orEmpty()

        parentId.startsWith(BrowseTree.PREFIX_SINGLES) ->
            artistSinglesTracks(parentId.removePrefix(BrowseTree.PREFIX_SINGLES), creds)

        parentId.startsWith(BrowseTree.PREFIX_TOP) ->
            artistTopTracks(parentId.removePrefix(BrowseTree.PREFIX_TOP), creds)

        parentId == BrowseTree.ID_RECENT_TRACKS -> recentTracks(creds)

        else -> emptyList()
    }

    /**
     * Queue items never carry artwork bytes: the browser does not render them,
     * so fetching art here only delays the first note. The artwork *URI* is
     * still set, which is what the notification and now-playing screen use.
     */
    private suspend fun queueItems(
        tracks: List<SearchTrack>,
        parentId: String,
        creds: Credentials,
    ): List<MediaItem> = buildItems(tracks.map { trackRow(it, parentId) }, creds, forBrowse = false)

    private fun fillTrackUri(item: MediaItem): MediaItem {
        if (item.localConfiguration != null) return item
        val trackId = BrowseTree.trackIdOf(item.mediaId) ?: return item
        return item.buildUpon()
            .setUri(JamarrPlaybackService.trackUri(trackId))
            .build()
    }

    // ----- item building --------------------------------------------------

    private suspend fun buildItems(
        rows: List<Row>,
        creds: Credentials,
        forBrowse: Boolean,
    ): List<MediaItem> {
        if (rows.isEmpty()) return emptyList()
        val artwork = if (ArtworkPolicy.embedsBytes(creds.serverUrl, forBrowse)) {
            fetchArtwork(rows, creds)
        } else {
            List(rows.size) { null }
        }
        return rows.mapIndexed { index, row -> buildItem(row, creds, forBrowse, artwork[index]) }
    }

    private suspend fun fetchArtwork(rows: List<Row>, creds: Credentials): List<ByteArray?> =
        coroutineScope {
            rows.map { row ->
                async {
                    artworkGate.withPermit {
                        when {
                            row.artSha1 != null -> apiClient.fetchArtworkBytes(
                                creds.serverUrl,
                                row.artSha1,
                                ArtworkPolicy.ART_SIZE_PX,
                            )

                            row.artShas.isNotEmpty() -> gridArtwork(row.artShas, creds)
                            else -> null
                        }
                    }
                }
            }.awaitAll()
        }

    private fun buildItem(
        row: Row,
        creds: Credentials,
        forBrowse: Boolean,
        artBytes: ByteArray?,
    ): MediaItem {
        val metadata = MediaMetadata.Builder()
            .setTitle(row.title)
            .setIsBrowsable(row.browsable)
            .setIsPlayable(!row.browsable)
            .setMediaType(row.mediaType)
        row.artist?.takeIf { it.isNotBlank() }?.let {
            metadata.setArtist(it)
            metadata.setAlbumArtist(it)
        }
        row.album?.takeIf { it.isNotBlank() }?.let { metadata.setAlbumTitle(it) }
        row.durationMs?.let { metadata.setDurationMs(it) }

        // A subtitle is only rendered when displayTitle is set: media3 falls
        // back to (title, artist, album) from MediaMetadataCompat's preferred
        // description order otherwise, and drops our subtitle on the floor.
        row.subtitle?.takeIf { it.isNotBlank() }?.let {
            metadata.setDisplayTitle(row.title)
            metadata.setSubtitle(it)
        }

        artworkUri(row, creds)?.let { metadata.setArtworkUri(it) }
        if (artBytes != null) {
            metadata.setArtworkData(artBytes, MediaMetadata.PICTURE_TYPE_FRONT_COVER)
        }
        extrasFor(row, forBrowse)?.let { metadata.setExtras(it) }

        val builder = MediaItem.Builder()
            .setMediaId(row.mediaId)
            .setMediaMetadata(metadata.build())
        row.trackId?.takeIf { it > 0L }?.let { builder.setUri(JamarrPlaybackService.trackUri(it)) }
        return builder.build()
    }

    private fun artworkUri(row: Row, creds: Credentials): Uri? {
        val sha = row.artSha1 ?: row.artShas.firstOrNull() ?: return null
        if (sha.isBlank() || creds.serverUrl.isBlank()) return null
        val url = apiClient.artworkUrl(creds.serverUrl, sha, ArtworkPolicy.ART_SIZE_PX) ?: return null
        return runCatching { Uri.parse(url) }.getOrNull()
    }

    private fun extrasFor(row: Row, forBrowse: Boolean): Bundle? {
        val group = row.group?.takeIf { forBrowse && it.isNotBlank() } ?: return null
        return Bundle().apply { putString(GROUP_TITLE_KEY, group) }
    }

    /**
     * Composites up to four covers into a 2x2 grid, matching the playlist
     * covers in the phone UI. Sources are taken in order rather than shuffled
     * so a folder keeps the same cover between visits.
     */
    private suspend fun gridArtwork(shas: List<String>, creds: Credentials): ByteArray? {
        if (creds.serverUrl.isBlank()) return null
        val size = ArtworkPolicy.ART_SIZE_PX
        val candidates = shas.filter { it.isNotBlank() }.distinct().take(4)
        if (candidates.isEmpty()) return null

        val fetched = coroutineScope {
            candidates.map { sha ->
                async { apiClient.fetchArtworkBytes(creds.serverUrl, sha, size) }
            }.awaitAll()
        }.filterNotNull()
        if (fetched.isEmpty()) return null
        if (fetched.size == 1) return fetched[0]

        val tiles = fetched.mapNotNull { BitmapFactory.decodeByteArray(it, 0, it.size) }
        if (tiles.size <= 1) {
            tiles.forEach { it.recycle() }
            return fetched[0]
        }

        // Pad to four quadrants by repeating earlier tiles.
        val padded = when (tiles.size) {
            2 -> listOf(tiles[0], tiles[1], tiles[1], tiles[0])
            3 -> listOf(tiles[0], tiles[1], tiles[2], tiles[0])
            else -> tiles.take(4)
        }

        val out = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(out)
        val half = size / 2
        val rects = listOf(
            Rect(0, 0, half, half),
            Rect(half, 0, size, half),
            Rect(0, half, half, size),
            Rect(half, half, size, size),
        )
        val paint = Paint(Paint.FILTER_BITMAP_FLAG or Paint.ANTI_ALIAS_FLAG)
        padded.forEachIndexed { i, bitmap -> canvas.drawBitmap(bitmap, null, rects[i], paint) }

        val stream = ByteArrayOutputStream()
        out.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, stream)
        out.recycle()
        tiles.forEach { it.recycle() }
        return stream.toByteArray()
    }

    private fun errorCodeFor(error: Throwable): Int = when {
        error is JamarrApiException && (error.statusCode == 401 || error.statusCode == 403) ->
            SessionError.ERROR_SESSION_AUTHENTICATION_EXPIRED

        error is JamarrApiException && error.statusCode == 404 -> SessionError.ERROR_BAD_VALUE
        else -> SessionError.ERROR_IO
    }

    companion object {
        private const val TAG = "JamarrLibraryProvider"

        const val ID_SIGN_IN = "placeholder:sign-in"
        const val PLAY_ALL_TITLE = "Play all"

        // AAOS group title hint — items sharing a value render under one header.
        // See developer.android.com/training/cars/media#group_items.
        private const val GROUP_TITLE_KEY = "android.media.browse.CONTENT_STYLE_GROUP_TITLE_HINT"

        private const val CACHE_TTL_MS = 45_000L
        private const val ARTWORK_CONCURRENCY = 4
        private const val JPEG_QUALITY = 90
        private const val HOME_LIMIT = 30
        private const val RECENT_TRACK_LIMIT = 50
    }
}
