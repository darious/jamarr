@file:OptIn(UnstableApi::class)

package com.jamarr.android.playback

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Rect
import android.net.Uri
import android.os.Bundle
import androidx.annotation.OptIn
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.LibraryResult
import androidx.media3.session.SessionError
import androidx.media3.session.MediaLibraryService.LibraryParams
import androidx.media3.session.MediaLibraryService.MediaLibrarySession
import androidx.media3.session.MediaSession
import com.google.common.collect.ImmutableList
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import com.jamarr.android.data.AlbumDetail
import com.jamarr.android.data.ArtistTrackEntry
import com.jamarr.android.data.JamarrApiClient
import com.jamarr.android.data.PlaylistTrack
import com.jamarr.android.data.SearchTrack
import java.io.ByteArrayOutputStream
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.guava.future

/**
 * Browse tree + tap-to-play for Android Auto.
 *
 * Media id grammar (all strings, treated as opaque by clients):
 *   root
 *   node:favourites | node:fav-artists | node:fav-releases
 *   node:playlists
 *   node:recent | node:recent-artists | node:recent-albums | node:recent-tracks
 *   node:charts | node:added
 *   node:history | node:history-artists | node:history-albums
 *   artist:<mbid>                       browsable -> grouped albums + singles + top folders
 *   album:<mbid>                        browsable -> tracks (drill-in only)
 *   singles:<mbid>                      browsable -> artist's singles tracks
 *   top:<mbid>                          browsable -> artist's most-scrobbled tracks
 *   playlist:<id>                       browsable -> tracks (drill-in only)
 *   track:<id>|p:album:<mbid>           playable, parent encodes siblings
 *   track:<id>|p:playlist:<id>          playable
 *   track:<id>|p:singles:<artist-mbid>  playable, queues artist's singles tracks
 *   track:<id>|p:top:<artist-mbid>      playable, queues artist's most-scrobbled tracks
 *   track:<id>|p:node:recent-tracks     playable, queues sibling recents
 *   track:<id>                          playable, no parent (single-track)
 */
class JamarrLibraryProvider(
    private val apiClient: JamarrApiClient,
    private val serverUrlProvider: () -> String,
    private val tokenProvider: () -> String,
    private val scope: CoroutineScope,
) {
    @OptIn(UnstableApi::class)
    val callback: MediaLibrarySession.Callback = object : MediaLibrarySession.Callback {

        override fun onGetLibraryRoot(
            session: MediaLibrarySession,
            browser: MediaSession.ControllerInfo,
            params: LibraryParams?,
        ): ListenableFuture<LibraryResult<MediaItem>> {
            return Futures.immediateFuture(
                LibraryResult.ofItem(rootBrowsable(), params),
            )
        }

        override fun onGetItem(
            session: MediaLibrarySession,
            browser: MediaSession.ControllerInfo,
            mediaId: String,
        ): ListenableFuture<LibraryResult<MediaItem>> = scope.future {
            val item = buildItem(mediaId)
            if (item != null) LibraryResult.ofItem(item, null)
            else LibraryResult.ofError(SessionError.ERROR_BAD_VALUE)
        }

        override fun onGetChildren(
            session: MediaLibrarySession,
            browser: MediaSession.ControllerInfo,
            parentId: String,
            page: Int,
            pageSize: Int,
            params: LibraryParams?,
        ): ListenableFuture<LibraryResult<ImmutableList<MediaItem>>> = scope.future {
            if (!authenticated()) {
                return@future LibraryResult.ofItemList(
                    ImmutableList.of(signInPlaceholder()),
                    params,
                )
            }
            val children = runCatching { childrenFor(parentId) }
                .getOrElse { emptyList() }
            LibraryResult.ofItemList(ImmutableList.copyOf(children), params)
        }

        override fun onAddMediaItems(
            mediaSession: MediaSession,
            controller: MediaSession.ControllerInfo,
            mediaItems: List<MediaItem>,
        ): ListenableFuture<List<MediaItem>> = scope.future {
            expandForPlayback(mediaItems).items
        }

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

    // ----- browse tree --------------------------------------------------

    private suspend fun childrenFor(parentId: String): List<MediaItem> = when (parentId) {
        ID_ROOT -> rootChildren()
        ID_FAVOURITES -> favouriteChildren()
        ID_FAV_ARTISTS -> favouriteArtists()
        ID_FAV_RELEASES -> favouriteReleases()
        ID_PLAYLISTS -> playlists()
        ID_RECENT -> recentlyPlayedChildren()
        ID_RECENT_ARTISTS -> recentlyPlayedArtists()
        ID_RECENT_ALBUMS -> recentlyPlayedAlbums()
        ID_RECENT_TRACKS -> recentlyPlayedTracks()
        ID_CHARTS -> chartAlbums()
        ID_ADDED -> recentlyAddedAlbums()
        ID_HISTORY -> historyChildren()
        ID_HISTORY_ALBUMS -> historyAlbums()
        ID_HISTORY_ARTISTS -> historyArtists()
        else -> when {
            parentId.startsWith(PREFIX_ARTIST) -> artistContent(parentId.removePrefix(PREFIX_ARTIST))
            parentId.startsWith(PREFIX_ALBUM) -> albumTracks(parentId.removePrefix(PREFIX_ALBUM))
            parentId.startsWith(PREFIX_SINGLES) -> artistSinglesTrackItems(parentId.removePrefix(PREFIX_SINGLES))
            parentId.startsWith(PREFIX_TOP) -> artistTopTrackItems(parentId.removePrefix(PREFIX_TOP))
            parentId.startsWith(PREFIX_PLAYLIST) -> playlistTracks(
                parentId.removePrefix(PREFIX_PLAYLIST).toLongOrNull() ?: return emptyList(),
            )
            else -> emptyList()
        }
    }

    private fun rootBrowsable(): MediaItem = browsable(ID_ROOT, "Jamarr")

    private fun rootChildren(): List<MediaItem> = listOf(
        browsable(ID_FAVOURITES, "Favourites"),
        browsable(ID_PLAYLISTS, "Playlists"),
        browsable(ID_RECENT, "Recently Played"),
        browsable(ID_CHARTS, "Charts"),
        browsable(ID_HISTORY, "History"),
        browsable(ID_ADDED, "Recently Added"),
    )

    private fun favouriteChildren(): List<MediaItem> = listOf(
        browsable(ID_FAV_ARTISTS, "Artists"),
        browsable(ID_FAV_RELEASES, "Releases"),
    )

    private fun recentlyPlayedChildren(): List<MediaItem> = listOf(
        browsable(ID_RECENT_ARTISTS, "Artists"),
        browsable(ID_RECENT_ALBUMS, "Albums"),
        browsable(ID_RECENT_TRACKS, "Tracks"),
    )

    private fun historyChildren(): List<MediaItem> = listOf(
        browsable(ID_HISTORY_ARTISTS, "Artists"),
        browsable(ID_HISTORY_ALBUMS, "Albums"),
    )

    // ----- data-backed nodes -------------------------------------------

    private suspend fun favouriteArtists(): List<MediaItem> {
        val server = serverUrlProvider()
        val results = runCatching { apiClient.favoriteArtists(server, tokenProvider()) }
            .getOrDefault(emptyList())
        return artworkParallel(results.map { it.artSha1 }) { idx, art ->
            val a = results[idx]
            artistItem(mbid = a.mbid, name = a.name, artBytes = art)
        }
    }

    private suspend fun favouriteReleases(): List<MediaItem> {
        val server = serverUrlProvider()
        val results = runCatching { apiClient.favoriteReleases(server, tokenProvider()) }
            .getOrDefault(emptyList())
            .sortedByDescending { it.year ?: "" }
        return artworkParallel(results.map { it.artSha1 }) { idx, art ->
            val r = results[idx]
            albumItem(
                albumMbid = r.albumMbid,
                title = r.title,
                artist = r.artistName,
                year = r.year,
                artBytes = art,
            )
        }
    }

    private suspend fun playlists(): List<MediaItem> {
        val server = serverUrlProvider()
        val results = runCatching { apiClient.playlists(server, tokenProvider()) }
            .getOrDefault(emptyList())
        return coroutineScope {
            results.map { p ->
                async {
                    val art = gridArtwork(p.thumbnails)
                    playlistItem(id = p.id, name = p.name, trackCount = p.trackCount, artBytes = art)
                }
            }.awaitAll()
        }
    }

    private suspend fun recentlyPlayedArtists(): List<MediaItem> {
        val server = serverUrlProvider()
        val home = runCatching { apiClient.home(server, tokenProvider(), limit = 30) }
            .getOrNull() ?: return emptyList()
        val artists = home.recentlyPlayedArtists
        return artworkParallel(artists.map { it.artSha1 }) { idx, art ->
            val a = artists[idx]
            artistItem(mbid = a.mbid, name = a.name, artBytes = art)
        }
    }

    private suspend fun recentlyPlayedAlbums(): List<MediaItem> {
        val server = serverUrlProvider()
        val home = runCatching { apiClient.home(server, tokenProvider(), limit = 30) }
            .getOrNull() ?: return emptyList()
        val albums = home.recentlyPlayedAlbums
        return artworkParallel(albums.map { it.artSha1 }) { idx, art ->
            val a = albums[idx]
            albumItem(
                albumMbid = a.albumMbid ?: a.mbReleaseId ?: a.mbid,
                title = a.album,
                artist = a.artistName,
                year = a.year,
                artBytes = art,
            )
        }
    }

    private suspend fun recentlyPlayedTracks(): List<MediaItem> {
        val server = serverUrlProvider()
        val tracks = runCatching {
            apiClient.recentlyPlayedTracks(server, tokenProvider(), limit = 50)
        }.getOrDefault(emptyList())
        return artworkParallel(tracks.map { it.artSha1 }) { idx, art ->
            val t = tracks[idx]
            trackItem(track = t, parentId = ID_RECENT_TRACKS, artBytes = art)
        }
    }

    private suspend fun recentlyAddedAlbums(): List<MediaItem> {
        val server = serverUrlProvider()
        val home = runCatching { apiClient.home(server, tokenProvider(), limit = 30) }
            .getOrNull() ?: return emptyList()
        val albums = home.recentlyAddedAlbums
        return artworkParallel(albums.map { it.artSha1 }) { idx, art ->
            val a = albums[idx]
            albumItem(
                albumMbid = a.albumMbid ?: a.mbReleaseId ?: a.mbid,
                title = a.album,
                artist = a.artistName,
                year = a.year,
                artBytes = art,
            )
        }
    }

    private suspend fun chartAlbums(): List<MediaItem> {
        val server = serverUrlProvider()
        val results = runCatching { apiClient.chart(server, tokenProvider()) }
            .getOrDefault(emptyList())
            .filter { it.inLibrary }
        return artworkParallel(results.map { it.artSha1 }) { idx, art ->
            val c = results[idx]
            albumItem(
                albumMbid = c.localAlbumMbid ?: c.releaseMbid ?: c.releaseGroupMbid,
                title = "${c.position}. ${c.localTitle ?: c.title}",
                artist = c.localArtist ?: c.artist,
                year = null,
                artBytes = art,
            )
        }
    }

    private suspend fun historyAlbums(): List<MediaItem> {
        val server = serverUrlProvider()
        val stats = runCatching { apiClient.historyStats(server, tokenProvider()) }
            .getOrNull() ?: return emptyList()
        val albums = stats.albums
        return artworkParallel(albums.map { it.artSha1 }) { idx, art ->
            val a = albums[idx]
            albumItem(
                albumMbid = a.mbReleaseId,
                title = a.displayTitle,
                artist = a.artist,
                year = null,
                artBytes = art,
            )
        }
    }

    private suspend fun historyArtists(): List<MediaItem> {
        val server = serverUrlProvider()
        val stats = runCatching { apiClient.historyStats(server, tokenProvider()) }
            .getOrNull() ?: return emptyList()
        val artists = stats.artists
        return artworkParallel(artists.map { it.artSha1 }) { idx, art ->
            val a = artists[idx]
            artistItem(mbid = a.resolvedMbid, name = a.displayName, artBytes = art)
        }
    }

    private suspend fun artistContent(mbid: String): List<MediaItem> {
        if (mbid.isBlank()) return emptyList()
        val server = serverUrlProvider()
        val tok = tokenProvider()
        val (detail, rawAlbums) = coroutineScope {
            val d = async { runCatching { apiClient.artistDetail(server, tok, mbid = mbid) }.getOrNull() }
            val a = async { runCatching { apiClient.artistAlbums(server, tok, mbid) }.getOrDefault(emptyList()) }
            d.await() to a.await()
        }

        val grouped = rawAlbums.groupBy { albumGroupTitle(it) }
        val singlesTracks = detail?.singles.orEmpty()
            .sortedSinglesAsc()
            .mapNotNull { it.toSearchTrack(detail!!.name) }
        val topTracks = detail?.topTracks.orEmpty()
            .sortedScrobbledDesc()
            .mapNotNull { it.toSearchTrack(detail!!.name) }

        val sections = mutableListOf<List<MediaItem>>()
        for (group in ALBUM_GROUP_ORDER) {
            // Hold "Appears On" until after the synthetic singles/top-tracks rows.
            if (group == GROUP_APPEARS_ON) continue
            val list = grouped[group] ?: continue
            val sorted = list.sortedByDescending { it.releaseDate ?: it.year ?: "" }
            sections.add(buildAlbumGroup(sorted, group))
        }

        if (singlesTracks.isNotEmpty()) {
            sections.add(
                listOf(
                    trackListFolderItem(
                        mediaId = "${PREFIX_SINGLES}$mbid",
                        title = GROUP_SINGLES_TRACKS,
                        artist = detail?.name,
                        trackCount = singlesTracks.size,
                        artBytes = gridArtwork(singlesTracks.map { it.artSha1 }),
                        groupTitle = GROUP_SINGLES_TRACKS,
                    ),
                ),
            )
        }
        if (topTracks.isNotEmpty()) {
            sections.add(
                listOf(
                    trackListFolderItem(
                        mediaId = "${PREFIX_TOP}$mbid",
                        title = GROUP_MOST_SCROBBLED,
                        artist = detail?.name,
                        trackCount = topTracks.size,
                        artBytes = gridArtwork(topTracks.map { it.artSha1 }),
                        groupTitle = GROUP_MOST_SCROBBLED,
                    ),
                ),
            )
        }

        grouped[GROUP_APPEARS_ON]?.let { list ->
            val sorted = list.sortedByDescending { it.releaseDate ?: it.year ?: "" }
            sections.add(buildAlbumGroup(sorted, GROUP_APPEARS_ON))
        }

        return sections.flatten()
    }

    /**
     * Composite up to 4 random distinct artworks from [shas] into a 2x2 grid,
     * matching the playlist-cover style used in the phone UI. Returns the
     * single-tile bytes if only one source artwork is available, or null if
     * none could be fetched.
     */
    private suspend fun gridArtwork(shas: List<String?>, size: Int = ART_MAX_SIZE): ByteArray? {
        val server = serverUrlProvider()
        if (server.isBlank()) return null
        val candidates = shas.filterNotNull()
            .filter { it.isNotBlank() }
            .distinct()
            .shuffled()
            .take(4)
        if (candidates.isEmpty()) return null

        val fetched = coroutineScope {
            candidates.map { sha -> async { apiClient.fetchArtworkBytes(server, sha, size) } }.awaitAll()
        }.filterNotNull()
        if (fetched.isEmpty()) return null
        if (fetched.size == 1) return fetched[0]

        val tiles = fetched.mapNotNull { BitmapFactory.decodeByteArray(it, 0, it.size) }
        if (tiles.isEmpty()) return null
        if (tiles.size == 1) return fetched[0]

        // Pad to 4 quadrants by repeating earlier tiles.
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
        padded.forEachIndexed { i, bm -> canvas.drawBitmap(bm, null, rects[i], paint) }

        val baos = ByteArrayOutputStream()
        out.compress(Bitmap.CompressFormat.JPEG, 90, baos)
        return baos.toByteArray()
    }

    private suspend fun artistSinglesTrackItems(mbid: String): List<MediaItem> {
        val tracks = artistSinglesTracks(mbid)
        return artworkParallel(tracks.map { it.artSha1 }) { idx, art ->
            trackItem(track = tracks[idx], parentId = "${PREFIX_SINGLES}$mbid", artBytes = art)
        }
    }

    private suspend fun artistTopTrackItems(mbid: String): List<MediaItem> {
        val tracks = artistTopTracks(mbid)
        return artworkParallel(tracks.map { it.artSha1 }) { idx, art ->
            trackItem(track = tracks[idx], parentId = "${PREFIX_TOP}$mbid", artBytes = art)
        }
    }

    private fun albumGroupTitle(a: AlbumDetail): String {
        if (a.type.equals("appears_on", ignoreCase = true)) return GROUP_APPEARS_ON
        return when ((a.releaseType ?: "album").lowercase().trim()) {
            "ep" -> GROUP_EPS
            "live" -> GROUP_LIVE
            "compilation" -> GROUP_COMPILATIONS
            "single" -> GROUP_SINGLE_RELEASES
            else -> GROUP_ALBUMS
        }
    }

    private suspend fun buildAlbumGroup(albums: List<AlbumDetail>, groupTitle: String): List<MediaItem> {
        return artworkParallel(albums.map { it.artSha1 }) { idx, art ->
            val a = albums[idx]
            albumItem(
                albumMbid = a.albumMbid ?: a.mbReleaseId,
                title = a.album,
                artist = a.artistName,
                year = a.year,
                artBytes = art,
                groupTitle = groupTitle,
            )
        }
    }

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

    private suspend fun artistSinglesTracks(mbid: String): List<SearchTrack> {
        if (mbid.isBlank()) return emptyList()
        val detail = runCatching {
            apiClient.artistDetail(serverUrlProvider(), tokenProvider(), mbid = mbid)
        }.getOrNull() ?: return emptyList()
        return detail.singles.sortedSinglesAsc().mapNotNull { it.toSearchTrack(detail.name) }
    }

    private suspend fun artistTopTracks(mbid: String): List<SearchTrack> {
        if (mbid.isBlank()) return emptyList()
        val detail = runCatching {
            apiClient.artistDetail(serverUrlProvider(), tokenProvider(), mbid = mbid)
        }.getOrNull() ?: return emptyList()
        return detail.topTracks.sortedScrobbledDesc().mapNotNull { it.toSearchTrack(detail.name) }
    }

    private fun List<ArtistTrackEntry>.sortedSinglesAsc(): List<ArtistTrackEntry> =
        sortedWith(
            compareBy<ArtistTrackEntry> { it.date.isNullOrBlank() }
                .thenBy { it.date ?: "" },
        )

    private fun List<ArtistTrackEntry>.sortedScrobbledDesc(): List<ArtistTrackEntry> =
        sortedWith(
            compareBy<ArtistTrackEntry> { it.popularity == null }
                .thenByDescending { it.popularity ?: 0 },
        )

    private suspend fun albumTracks(mbid: String): List<MediaItem> {
        if (mbid.isBlank()) return emptyList()
        val server = serverUrlProvider()
        val tracks = runCatching {
            apiClient.albumTracks(server, tokenProvider(), albumMbid = mbid)
        }.getOrDefault(emptyList())
        return artworkParallel(tracks.map { it.artSha1 }) { idx, art ->
            val t = tracks[idx]
            trackItem(
                track = t,
                parentId = "${PREFIX_ALBUM}$mbid",
                artBytes = art,
            )
        }
    }

    private suspend fun playlistTracks(playlistId: Long): List<MediaItem> {
        val server = serverUrlProvider()
        val detail = runCatching {
            apiClient.playlistDetail(server, tokenProvider(), playlistId)
        }.getOrNull() ?: return emptyList()
        val tracks = detail.tracks
        return artworkParallel(tracks.map { it.artSha1 }) { idx, art ->
            val t = tracks[idx]
            playlistTrackItem(
                track = t,
                parentId = "${PREFIX_PLAYLIST}$playlistId",
                artBytes = art,
            )
        }
    }

    // ----- single-item lookup ------------------------------------------

    private suspend fun buildItem(mediaId: String): MediaItem? = when {
        mediaId == ID_ROOT -> rootBrowsable()
        mediaId.startsWith("node:") -> rootChildren().firstOrNull { it.mediaId == mediaId }
        mediaId.startsWith(PREFIX_TRACK) -> reconstructTrackItem(mediaId)
        mediaId.startsWith(PREFIX_ALBUM) -> albumItem(
            albumMbid = mediaId.removePrefix(PREFIX_ALBUM),
            title = "Album",
            artist = null,
            year = null,
            artBytes = null,
        )
        mediaId.startsWith(PREFIX_PLAYLIST) -> {
            val id = mediaId.removePrefix(PREFIX_PLAYLIST).toLongOrNull()
            id?.let { playlistItem(it, "Playlist", 0, null) }
        }
        mediaId.startsWith(PREFIX_SINGLES) -> trackListFolderItem(
            mediaId = mediaId,
            title = GROUP_SINGLES_TRACKS,
            artist = null,
            trackCount = 0,
            artBytes = null,
        )
        mediaId.startsWith(PREFIX_TOP) -> trackListFolderItem(
            mediaId = mediaId,
            title = GROUP_MOST_SCROBBLED,
            artist = null,
            trackCount = 0,
            artBytes = null,
        )
        else -> null
    }

    private fun reconstructTrackItem(mediaId: String): MediaItem {
        // mediaId form: track:<id>[|p:<parent>]
        val (trackPart, _) = splitTrackParent(mediaId)
        val trackId = trackPart.removePrefix(PREFIX_TRACK).toLongOrNull() ?: 0L
        return MediaItem.Builder()
            .setMediaId(mediaId)
            .setUri(JamarrPlaybackService.trackUri(trackId))
            .setMediaMetadata(
                MediaMetadata.Builder()
                    .setIsPlayable(true)
                    .setIsBrowsable(false)
                    .build(),
            )
            .build()
    }

    // ----- tap-to-play expansion ---------------------------------------

    data class Expansion(val items: List<MediaItem>, val startIndex: Int?)

    private suspend fun expandForPlayback(incoming: List<MediaItem>): Expansion {
        if (incoming.isEmpty()) return Expansion(emptyList(), null)
        if (incoming.size > 1) {
            // Multiple items handed to us - just fill URIs; controller picks startIndex.
            return Expansion(incoming.map { fillTrackUri(it) }, null)
        }
        val single = incoming.first()
        val mediaId = single.mediaId
        return when {
            mediaId.startsWith(PREFIX_TRACK) -> expandTrack(single)
            mediaId.startsWith(PREFIX_ALBUM) -> expandAlbum(mediaId.removePrefix(PREFIX_ALBUM))
            mediaId.startsWith(PREFIX_PLAYLIST) -> expandPlaylist(
                mediaId.removePrefix(PREFIX_PLAYLIST).toLongOrNull() ?: return Expansion(emptyList(), null),
            )
            else -> Expansion(listOf(fillTrackUri(single)), 0)
        }
    }

    private suspend fun expandTrack(item: MediaItem): Expansion {
        val (trackPart, parent) = splitTrackParent(item.mediaId)
        val trackId = trackPart.removePrefix(PREFIX_TRACK).toLongOrNull()
            ?: return Expansion(listOf(fillTrackUri(item)), 0)
        if (parent == null) return Expansion(listOf(fillTrackUri(item)), 0)
        return when {
            parent.startsWith("album:") -> {
                val mbid = parent.removePrefix("album:")
                val siblings = albumTracks(mbid)
                val idx = siblings.indexOfFirst {
                    it.mediaId.removePrefix(PREFIX_TRACK).substringBefore("|").toLongOrNull() == trackId
                }
                if (siblings.isEmpty() || idx < 0) Expansion(listOf(fillTrackUri(item)), 0)
                else Expansion(siblings, idx)
            }
            parent.startsWith("playlist:") -> {
                val plId = parent.removePrefix("playlist:").toLongOrNull()
                    ?: return Expansion(listOf(fillTrackUri(item)), 0)
                val siblings = playlistTracks(plId)
                val idx = siblings.indexOfFirst {
                    it.mediaId.removePrefix(PREFIX_TRACK).substringBefore("|").toLongOrNull() == trackId
                }
                if (siblings.isEmpty() || idx < 0) Expansion(listOf(fillTrackUri(item)), 0)
                else Expansion(siblings, idx)
            }
            parent == ID_RECENT_TRACKS -> {
                val siblings = recentlyPlayedTracks()
                val idx = siblings.indexOfFirst {
                    it.mediaId.removePrefix(PREFIX_TRACK).substringBefore("|").toLongOrNull() == trackId
                }
                if (siblings.isEmpty() || idx < 0) Expansion(listOf(fillTrackUri(item)), 0)
                else Expansion(siblings, idx)
            }
            parent.startsWith(PREFIX_SINGLES) -> {
                val artistMbid = parent.removePrefix(PREFIX_SINGLES)
                val tracks = artistSinglesTracks(artistMbid)
                expandFromTrackList(tracks, trackId, item)
            }
            parent.startsWith(PREFIX_TOP) -> {
                val artistMbid = parent.removePrefix(PREFIX_TOP)
                val tracks = artistTopTracks(artistMbid)
                expandFromTrackList(tracks, trackId, item)
            }
            else -> Expansion(listOf(fillTrackUri(item)), 0)
        }
    }

    private suspend fun expandAlbum(mbid: String): Expansion {
        val tracks = albumTracks(mbid)
        return Expansion(tracks, if (tracks.isEmpty()) null else 0)
    }

    private suspend fun expandFromTrackList(
        tracks: List<SearchTrack>,
        startTrackId: Long,
        fallback: MediaItem,
    ): Expansion {
        if (tracks.isEmpty()) return Expansion(listOf(fillTrackUri(fallback)), 0)
        val idx = tracks.indexOfFirst { it.id == startTrackId }
        if (idx < 0) return Expansion(listOf(fillTrackUri(fallback)), 0)
        val items = artworkParallel(tracks.map { it.artSha1 }) { i, art ->
            trackItem(track = tracks[i], parentId = "node:track-list", artBytes = art)
        }
        return Expansion(items, idx)
    }

    private suspend fun expandPlaylist(playlistId: Long): Expansion {
        val tracks = playlistTracks(playlistId)
        return Expansion(tracks, if (tracks.isEmpty()) null else 0)
    }

    private fun fillTrackUri(item: MediaItem): MediaItem {
        if (item.localConfiguration != null) return item
        if (!item.mediaId.startsWith(PREFIX_TRACK)) return item
        val (trackPart, _) = splitTrackParent(item.mediaId)
        val trackId = trackPart.removePrefix(PREFIX_TRACK).toLongOrNull() ?: return item
        return MediaItem.Builder()
            .setMediaId(item.mediaId)
            .setUri(JamarrPlaybackService.trackUri(trackId))
            .setMediaMetadata(item.mediaMetadata)
            .setRequestMetadata(item.requestMetadata)
            .build()
    }

    private fun splitTrackParent(mediaId: String): Pair<String, String?> {
        val pipe = mediaId.indexOf('|')
        if (pipe < 0) return mediaId to null
        val trackPart = mediaId.substring(0, pipe)
        val rest = mediaId.substring(pipe + 1)
        val parent = rest.removePrefix("p:").takeIf { it.isNotBlank() }
        return trackPart to parent
    }

    // ----- artwork helpers ---------------------------------------------

    private suspend fun <T> artworkParallel(
        artSha1s: List<String?>,
        build: (Int, ByteArray?) -> T,
    ): List<T> = coroutineScope {
        val server = serverUrlProvider()
        val deferred = artSha1s.map { sha ->
            async {
                if (sha.isNullOrBlank() || server.isBlank()) null
                else apiClient.fetchArtworkBytes(server, sha, ART_MAX_SIZE)
            }
        }
        val resolved = deferred.awaitAll()
        resolved.mapIndexed { idx, art -> build(idx, art) }
    }

    // ----- builders -----------------------------------------------------

    private fun browsable(id: String, title: String): MediaItem = MediaItem.Builder()
        .setMediaId(id)
        .setMediaMetadata(
            MediaMetadata.Builder()
                .setTitle(title)
                .setIsBrowsable(true)
                .setIsPlayable(false)
                .setMediaType(MediaMetadata.MEDIA_TYPE_FOLDER_MIXED)
                .build(),
        )
        .build()

    private fun signInPlaceholder(): MediaItem = MediaItem.Builder()
        .setMediaId("placeholder:sign-in")
        .setMediaMetadata(
            MediaMetadata.Builder()
                .setTitle("Sign in on phone to use Jamarr")
                .setIsBrowsable(false)
                .setIsPlayable(false)
                .build(),
        )
        .build()

    private fun artistItem(mbid: String?, name: String, artBytes: ByteArray?): MediaItem {
        val id = if (!mbid.isNullOrBlank()) "${PREFIX_ARTIST}$mbid"
        else "$PREFIX_ARTIST_NAMED${name.hashCode()}"
        val md = MediaMetadata.Builder()
            .setTitle(name)
            .setIsBrowsable(true)
            .setIsPlayable(false)
            .setMediaType(MediaMetadata.MEDIA_TYPE_ARTIST)
        if (artBytes != null) md.setArtworkData(artBytes, MediaMetadata.PICTURE_TYPE_FRONT_COVER)
        return MediaItem.Builder()
            .setMediaId(id)
            .setMediaMetadata(md.build())
            .build()
    }

    private fun albumItem(
        albumMbid: String?,
        title: String,
        artist: String?,
        year: String?,
        artBytes: ByteArray?,
        groupTitle: String? = null,
    ): MediaItem {
        val id = if (!albumMbid.isNullOrBlank()) "${PREFIX_ALBUM}$albumMbid"
        else "$PREFIX_ALBUM_NAMED${(title + (artist ?: "")).hashCode()}"
        val md = MediaMetadata.Builder()
            .setTitle(title)
            .setArtist(artist)
            .setAlbumTitle(title)
            .setAlbumArtist(artist)
            .setIsBrowsable(true)
            .setIsPlayable(false)
            .setMediaType(MediaMetadata.MEDIA_TYPE_ALBUM)
        if (!year.isNullOrBlank()) md.setSubtitle(year)
        if (artBytes != null) md.setArtworkData(artBytes, MediaMetadata.PICTURE_TYPE_FRONT_COVER)
        groupExtras(groupTitle)?.let { md.setExtras(it) }
        return MediaItem.Builder()
            .setMediaId(id)
            .setMediaMetadata(md.build())
            .build()
    }

    private fun playlistItem(id: Long, name: String, trackCount: Int, artBytes: ByteArray?): MediaItem {
        val md = MediaMetadata.Builder()
            .setTitle(name)
            .setIsBrowsable(true)
            .setIsPlayable(false)
            .setMediaType(MediaMetadata.MEDIA_TYPE_PLAYLIST)
        if (trackCount > 0) md.setSubtitle("$trackCount tracks")
        if (artBytes != null) md.setArtworkData(artBytes, MediaMetadata.PICTURE_TYPE_FRONT_COVER)
        return MediaItem.Builder()
            .setMediaId("${PREFIX_PLAYLIST}$id")
            .setMediaMetadata(md.build())
            .build()
    }

    private fun trackItem(
        track: SearchTrack,
        parentId: String,
        artBytes: ByteArray?,
        groupTitle: String? = null,
    ): MediaItem {
        val finalId = "${PREFIX_TRACK}${track.id}|p:$parentId"
        val md = MediaMetadata.Builder()
            .setTitle(track.title)
            .setArtist(track.artist)
            .setAlbumTitle(track.album)
            .setIsBrowsable(false)
            .setIsPlayable(true)
            .setMediaType(MediaMetadata.MEDIA_TYPE_MUSIC)
        if (artBytes != null) md.setArtworkData(artBytes, MediaMetadata.PICTURE_TYPE_FRONT_COVER)
        groupExtras(groupTitle)?.let { md.setExtras(it) }
        return MediaItem.Builder()
            .setMediaId(finalId)
            .setUri(JamarrPlaybackService.trackUri(track.id))
            .setMediaMetadata(md.build())
            .build()
    }

    private fun trackListFolderItem(
        mediaId: String,
        title: String,
        artist: String?,
        trackCount: Int,
        artBytes: ByteArray?,
        groupTitle: String? = null,
    ): MediaItem {
        val md = MediaMetadata.Builder()
            .setTitle(title)
            .setArtist(artist)
            .setAlbumTitle(title)
            .setAlbumArtist(artist)
            .setIsBrowsable(true)
            .setIsPlayable(false)
            .setMediaType(MediaMetadata.MEDIA_TYPE_ALBUM)
        if (trackCount > 0) md.setSubtitle("$trackCount tracks")
        if (artBytes != null) md.setArtworkData(artBytes, MediaMetadata.PICTURE_TYPE_FRONT_COVER)
        groupExtras(groupTitle)?.let { md.setExtras(it) }
        return MediaItem.Builder()
            .setMediaId(mediaId)
            .setMediaMetadata(md.build())
            .build()
    }

    private fun groupExtras(groupTitle: String?): Bundle? {
        val title = groupTitle?.takeIf { it.isNotBlank() } ?: return null
        return Bundle().apply { putString(GROUP_TITLE_KEY, title) }
    }

    private fun playlistTrackItem(track: PlaylistTrack, parentId: String, artBytes: ByteArray?): MediaItem {
        val md = MediaMetadata.Builder()
            .setTitle(track.title)
            .setArtist(track.artist)
            .setAlbumTitle(track.album)
            .setIsBrowsable(false)
            .setIsPlayable(true)
            .setMediaType(MediaMetadata.MEDIA_TYPE_MUSIC)
        if (artBytes != null) md.setArtworkData(artBytes, MediaMetadata.PICTURE_TYPE_FRONT_COVER)
        return MediaItem.Builder()
            .setMediaId("${PREFIX_TRACK}${track.trackId}|p:$parentId")
            .setUri(JamarrPlaybackService.trackUri(track.trackId))
            .setMediaMetadata(md.build())
            .build()
    }

    private fun authenticated(): Boolean =
        tokenProvider().isNotBlank() && serverUrlProvider().isNotBlank()

    companion object {
        private const val ART_MAX_SIZE = 400

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
        const val PREFIX_ARTIST_NAMED = "artist-named:"
        const val PREFIX_ALBUM = "album:"
        const val PREFIX_ALBUM_NAMED = "album-named:"
        const val PREFIX_PLAYLIST = "playlist:"
        const val PREFIX_TRACK = "track:"
        const val PREFIX_SINGLES = "singles:"
        const val PREFIX_TOP = "top:"

        // AAOS group title hint key — items sharing the same value render under
        // a section header. See developer.android.com/training/cars/media#group_items.
        private const val GROUP_TITLE_KEY = "android.media.browse.CONTENT_STYLE_GROUP_TITLE_HINT"

        private const val GROUP_ALBUMS = "Albums"
        private const val GROUP_EPS = "EPs"
        private const val GROUP_LIVE = "Live"
        private const val GROUP_COMPILATIONS = "Compilations"
        private const val GROUP_SINGLE_RELEASES = "Single Releases"
        private const val GROUP_APPEARS_ON = "Appears On"
        private const val GROUP_SINGLES_TRACKS = "Singles"
        private const val GROUP_MOST_SCROBBLED = "Most Scrobbled"

        private val ALBUM_GROUP_ORDER = listOf(
            GROUP_ALBUMS,
            GROUP_EPS,
            GROUP_LIVE,
            GROUP_COMPILATIONS,
            GROUP_SINGLE_RELEASES,
            GROUP_APPEARS_ON,
        )
    }
}
