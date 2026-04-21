package com.jamarr.android.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class LoginRequest(
    val username: String,
    val password: String,
)

@Serializable
data class LoginResponse(
    @SerialName("access_token")
    val accessToken: String,
    @SerialName("token_type")
    val tokenType: String = "bearer",
)

@Serializable
data class SearchResponse(
    val artists: List<SearchArtist> = emptyList(),
    val albums: List<SearchAlbum> = emptyList(),
    val tracks: List<SearchTrack> = emptyList(),
)

@Serializable
data class SearchArtist(
    val name: String,
    val mbid: String? = null,
    @SerialName("image_url")
    val imageUrl: String? = null,
    @SerialName("art_sha1")
    val artSha1: String? = null,
)

@Serializable
data class SearchAlbum(
    val title: String,
    val artist: String,
    val mbid: String? = null,
    @SerialName("art_sha1")
    val artSha1: String? = null,
)

@Serializable
data class SearchTrack(
    val id: Long,
    val title: String,
    val artist: String? = null,
    val album: String? = null,
    @SerialName("mb_release_id")
    val mbReleaseId: String? = null,
    @SerialName("duration_seconds")
    val durationSeconds: Double? = null,
    @SerialName("art_sha1")
    val artSha1: String? = null,
)

@Serializable
data class StreamUrlResponse(
    val url: String,
)

data class HomeContent(
    val newReleases: List<HomeAlbum> = emptyList(),
    val recentlyAddedAlbums: List<HomeAlbum> = emptyList(),
    val recentlyPlayedAlbums: List<HomeAlbum> = emptyList(),
    val discoverArtists: List<HomeArtist> = emptyList(),
    val recentlyPlayedArtists: List<HomeArtist> = emptyList(),
)

@Serializable
data class HomeAlbum(
    val album: String,
    @SerialName("artist_name")
    val artistName: String,
    @SerialName("art_sha1")
    val artSha1: String? = null,
    @SerialName("is_hires")
    val isHires: Int = 0,
    val year: String? = null,
    @SerialName("track_count")
    val trackCount: Int? = null,
    @SerialName("total_duration")
    val totalDuration: Double? = null,
    val mbid: String? = null,
    @SerialName("mb_release_id")
    val mbReleaseId: String? = null,
    @SerialName("album_mbid")
    val albumMbid: String? = null,
    @SerialName("artist_mbid")
    val artistMbid: String? = null,
)

@Serializable
data class HomeArtist(
    val mbid: String? = null,
    val name: String,
    @SerialName("image_url")
    val imageUrl: String? = null,
    @SerialName("art_sha1")
    val artSha1: String? = null,
    val bio: String? = null,
)

@Serializable
data class ArtistDetail(
    val mbid: String? = null,
    val name: String,
    @SerialName("image_url") val imageUrl: String? = null,
    @SerialName("art_sha1") val artSha1: String? = null,
    val bio: String? = null,
    @SerialName("primary_album_count") val primaryAlbumCount: Int = 0,
    @SerialName("appears_on_album_count") val appearsOnAlbumCount: Int = 0,
    val listens: Int = 0,
    @SerialName("lastfm_url") val lastfmUrl: String? = null,
    @SerialName("musicbrainz_url") val musicbrainzUrl: String? = null,
    @SerialName("wikipedia_url") val wikipediaUrl: String? = null,
    @SerialName("discogs_url") val discogsUrl: String? = null,
    @SerialName("spotify_url") val spotifyUrl: String? = null,
    @SerialName("tidal_url") val tidalUrl: String? = null,
    @SerialName("qobuz_url") val qobuzUrl: String? = null,
    val homepage: String? = null,
    @SerialName("top_tracks") val topTracks: List<ArtistTrackEntry> = emptyList(),
    @SerialName("most_listened") val mostListened: List<ArtistTrackEntry> = emptyList(),
    val singles: List<ArtistTrackEntry> = emptyList(),
    @SerialName("similar_artists") val similarArtists: List<SimilarArtist> = emptyList(),
    val genres: List<ArtistGenre> = emptyList(),
)

@Serializable
data class ArtistTrackEntry(
    val name: String? = null,
    val title: String? = null,
    val album: String? = null,
    @SerialName("local_track_id") val localTrackId: Long? = null,
    @SerialName("art_sha1") val artSha1: String? = null,
    @SerialName("mb_release_id") val mbReleaseId: String? = null,
    @SerialName("duration_seconds") val durationSeconds: Double? = null,
    val plays: Int? = null,
    val popularity: Int? = null,
) {
    val displayTitle: String get() = title ?: name ?: "Untitled"
}

@Serializable
data class SimilarArtist(
    val name: String,
    val mbid: String? = null,
    @SerialName("image_url") val imageUrl: String? = null,
    @SerialName("art_sha1") val artSha1: String? = null,
    @SerialName("in_library") val inLibrary: Boolean = false,
    @SerialName("external_url") val externalUrl: String? = null,
)

@Serializable
data class ArtistGenre(val name: String, val count: Int = 0)

@Serializable
data class AlbumDetail(
    val album: String,
    @SerialName("artist_name") val artistName: String? = null,
    @SerialName("album_mbid") val albumMbid: String? = null,
    @SerialName("mb_release_id") val mbReleaseId: String? = null,
    @SerialName("release_date") val releaseDate: String? = null,
    val year: String? = null,
    @SerialName("release_type") val releaseType: String? = null,
    @SerialName("peak_chart_position") val peakChartPosition: Int? = null,
    @SerialName("track_count") val trackCount: Int? = null,
    @SerialName("total_duration") val totalDuration: Double? = null,
    @SerialName("is_hires") val isHires: Int = 0,
    val label: String? = null,
    @SerialName("art_sha1") val artSha1: String? = null,
    val listens: Int = 0,
    val type: String? = null,
    val artists: List<AlbumArtistRef> = emptyList(),
    val description: String? = null,
)

@Serializable
data class AlbumArtistRef(
    val name: String,
    val mbid: String? = null,
    @SerialName("sort_name") val sortName: String? = null,
)

@Serializable
data class PlaylistSummary(
    val id: Long,
    val name: String,
    val description: String? = null,
    @SerialName("track_count") val trackCount: Int = 0,
    @SerialName("total_duration") val totalDuration: Double = 0.0,
    @SerialName("updated_at") val updatedAt: String? = null,
    val thumbnails: List<String> = emptyList(),
)

@Serializable
data class PlaylistDetail(
    val id: Long,
    val name: String,
    val description: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
    @SerialName("track_count") val trackCount: Int = 0,
    @SerialName("total_duration") val totalDuration: Double = 0.0,
    val tracks: List<PlaylistTrack> = emptyList(),
)

@Serializable
data class PlaylistTrack(
    @SerialName("playlist_track_id") val playlistTrackId: Long,
    val position: Int,
    @SerialName("track_id") val trackId: Long,
    val title: String,
    val artist: String? = null,
    val album: String? = null,
    @SerialName("duration_seconds") val durationSeconds: Double? = null,
    @SerialName("art_sha1") val artSha1: String? = null,
    val plays: Int = 0,
)

@Serializable
data class ChartAlbum(
    val position: Int,
    val title: String,
    val artist: String,
    @SerialName("last_week") val lastWeek: String? = null,
    val peak: String? = null,
    val weeks: String? = null,
    val status: String = "",
    @SerialName("release_mbid") val releaseMbid: String? = null,
    @SerialName("release_group_mbid") val releaseGroupMbid: String? = null,
    @SerialName("in_library") val inLibrary: Boolean = false,
    @SerialName("local_album_mbid") val localAlbumMbid: String? = null,
    @SerialName("local_title") val localTitle: String? = null,
    @SerialName("local_artist") val localArtist: String? = null,
    @SerialName("artist_mbid") val artistMbid: String? = null,
    @SerialName("art_sha1") val artSha1: String? = null,
)

@Serializable
data class HistoryStats(
    val artists: List<HistoryArtistEntry> = emptyList(),
    val albums: List<HistoryAlbumEntry> = emptyList(),
    val tracks: List<HistoryTrackEntry> = emptyList(),
)

@Serializable
data class HistoryArtistEntry(
    @SerialName("artist_name") val artistName: String? = null,
    val artist: String? = null,
    @SerialName("artist_mbid") val artistMbid: String? = null,
    val mbid: String? = null,
    @SerialName("art_sha1") val artSha1: String? = null,
    val plays: Int = 0,
) {
    val displayName: String get() = artistName ?: artist ?: "Unknown"
    val resolvedMbid: String? get() = artistMbid ?: mbid
}

@Serializable
data class HistoryAlbumEntry(
    val album: String? = null,
    val title: String? = null,
    val artist: String? = null,
    @SerialName("mb_release_id") val mbReleaseId: String? = null,
    @SerialName("art_sha1") val artSha1: String? = null,
    val plays: Int = 0,
) {
    val displayTitle: String get() = album ?: title ?: "Unknown"
}

@Serializable
data class HistoryTrackEntry(
    val id: Long? = null,
    val title: String? = null,
    val artist: String? = null,
    val album: String? = null,
    @SerialName("mb_release_id") val mbReleaseId: String? = null,
    @SerialName("art_sha1") val artSha1: String? = null,
    val plays: Int = 0,
) {
    val displayTitle: String get() = title ?: "Untitled"
}
