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
