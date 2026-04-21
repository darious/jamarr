package com.jamarr.android.data

import java.net.URI
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

class JamarrApiException(
    val statusCode: Int,
    message: String,
) : Exception(message)

class JamarrApiClient(
    private val httpClient: OkHttpClient = OkHttpClient(),
    private val json: Json = Json {
        ignoreUnknownKeys = true
    },
) {
    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()

    suspend fun login(
        serverUrl: String,
        username: String,
        password: String,
    ): LoginResponse = withContext(Dispatchers.IO) {
        val body = json.encodeToString(LoginRequest(username, password)).toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/auth/login"))
            .post(body)
            .build()

        execute(request)
    }

    suspend fun search(
        serverUrl: String,
        accessToken: String,
        query: String,
    ): SearchResponse = withContext(Dispatchers.IO) {
        val url = apiUrl(serverUrl, "/api/search")
            .toHttpUrl()
            .newBuilder()
            .addQueryParameter("q", query)
            .build()

        val request = Request.Builder()
            .url(url)
            .get()
            .bearer(accessToken)
            .build()

        execute(request)
    }

    suspend fun home(
        serverUrl: String,
        accessToken: String,
        limit: Int = 20,
    ): HomeContent = withContext(Dispatchers.IO) {
        HomeContent(
            newReleases = get(serverUrl, accessToken, "/api/home/new-releases", limit),
            recentlyAddedAlbums = get(serverUrl, accessToken, "/api/home/recently-added-albums", limit),
            recentlyPlayedAlbums = get(serverUrl, accessToken, "/api/history/albums", limit),
            discoverArtists = get(serverUrl, accessToken, "/api/home/discover-artists", limit),
            recentlyPlayedArtists = get(serverUrl, accessToken, "/api/history/artists", limit),
        )
    }

    suspend fun albumTracks(
        serverUrl: String,
        accessToken: String,
        album: String? = null,
        artist: String? = null,
        albumMbid: String? = null,
    ): List<SearchTrack> = withContext(Dispatchers.IO) {
        val builder = apiUrl(serverUrl, "/api/tracks").toHttpUrl().newBuilder()
        if (!albumMbid.isNullOrBlank()) builder.addQueryParameter("album_mbid", albumMbid)
        if (!album.isNullOrBlank()) builder.addQueryParameter("album", album)
        if (!artist.isNullOrBlank()) builder.addQueryParameter("artist", artist)

        val request = Request.Builder()
            .url(builder.build())
            .get()
            .bearer(accessToken)
            .build()

        execute(request)
    }

    suspend fun albumDetail(
        serverUrl: String,
        accessToken: String,
        albumMbid: String? = null,
        artistMbid: String? = null,
    ): AlbumDetail? = withContext(Dispatchers.IO) {
        val builder = apiUrl(serverUrl, "/api/albums").toHttpUrl().newBuilder()
        if (!albumMbid.isNullOrBlank()) builder.addQueryParameter("album_mbid", albumMbid)
        if (!artistMbid.isNullOrBlank()) builder.addQueryParameter("artist_mbid", artistMbid)

        val request = Request.Builder()
            .url(builder.build())
            .get()
            .bearer(accessToken)
            .build()

        val results: List<AlbumDetail> = execute(request)
        results.firstOrNull()
    }

    suspend fun artistAlbums(
        serverUrl: String,
        accessToken: String,
        artistMbid: String,
    ): List<AlbumDetail> = withContext(Dispatchers.IO) {
        val url = apiUrl(serverUrl, "/api/albums")
            .toHttpUrl()
            .newBuilder()
            .addQueryParameter("artist_mbid", artistMbid)
            .build()

        val request = Request.Builder().url(url).get().bearer(accessToken).build()
        execute(request)
    }

    suspend fun artistDetail(
        serverUrl: String,
        accessToken: String,
        mbid: String? = null,
        name: String? = null,
    ): ArtistDetail? = withContext(Dispatchers.IO) {
        val builder = apiUrl(serverUrl, "/api/artists").toHttpUrl().newBuilder()
        if (!mbid.isNullOrBlank()) builder.addQueryParameter("mbid", mbid)
        if (!name.isNullOrBlank()) builder.addQueryParameter("name", name)

        val request = Request.Builder()
            .url(builder.build())
            .get()
            .bearer(accessToken)
            .build()

        val results: List<ArtistDetail> = execute(request)
        results.firstOrNull()
    }

    suspend fun playlists(
        serverUrl: String,
        accessToken: String,
    ): List<PlaylistSummary> = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/playlists"))
            .get()
            .bearer(accessToken)
            .build()
        execute(request)
    }

    suspend fun playlistDetail(
        serverUrl: String,
        accessToken: String,
        id: Long,
    ): PlaylistDetail = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/playlists/$id"))
            .get()
            .bearer(accessToken)
            .build()
        execute(request)
    }

    suspend fun chart(
        serverUrl: String,
        accessToken: String,
    ): List<ChartAlbum> = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/charts"))
            .get()
            .bearer(accessToken)
            .build()
        execute(request)
    }

    suspend fun historyStats(
        serverUrl: String,
        accessToken: String,
        from: String? = null,
        to: String? = null,
        scope: String = "mine",
    ): HistoryStats = withContext(Dispatchers.IO) {
        val builder = apiUrl(serverUrl, "/api/history/stats").toHttpUrl().newBuilder()
            .addQueryParameter("scope", scope)
        if (!from.isNullOrBlank()) builder.addQueryParameter("from", from)
        if (!to.isNullOrBlank()) builder.addQueryParameter("to", to)

        val request = Request.Builder()
            .url(builder.build())
            .get()
            .bearer(accessToken)
            .build()
        execute(request)
    }

    suspend fun streamUrl(
        serverUrl: String,
        accessToken: String,
        trackId: Long,
    ): String = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/stream-url/$trackId"))
            .get()
            .bearer(accessToken)
            .build()

        resolveUrl(serverUrl, execute<StreamUrlResponse>(request).url)
    }

    fun artworkUrl(serverUrl: String, artSha1: String?, maxSize: Int = 400): String? {
        if (artSha1.isNullOrBlank()) return null
        return resolveUrl(serverUrl, "/api/art/file/$artSha1?max_size=$maxSize")
    }

    fun normalizeServerUrl(serverUrl: String): String {
        val trimmed = serverUrl.trim().trimEnd('/')
        require(trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
            "Server URL must start with http:// or https://"
        }
        return trimmed
    }

    fun resolveUrl(serverUrl: String, value: String): String {
        val base = URI(normalizeServerUrl(serverUrl))
        return base.resolve(value).toString()
    }

    private fun apiUrl(serverUrl: String, path: String): String = resolveUrl(serverUrl, path)

    private inline fun <reified T> get(
        serverUrl: String,
        accessToken: String,
        path: String,
        limit: Int,
    ): T {
        val url = apiUrl(serverUrl, path)
            .toHttpUrl()
            .newBuilder()
            .addQueryParameter("limit", limit.toString())
            .build()

        val request = Request.Builder()
            .url(url)
            .get()
            .bearer(accessToken)
            .build()

        return execute(request)
    }

    private inline fun <reified T> execute(request: Request): T {
        httpClient.newCall(request).execute().use { response ->
            val body = response.body.string()
            if (!response.isSuccessful) {
                throw JamarrApiException(response.code, errorMessage(response.code, body))
            }
            return json.decodeFromString(body)
        }
    }

    private fun Request.Builder.bearer(accessToken: String): Request.Builder {
        return header("Authorization", "Bearer $accessToken")
    }

    private fun errorMessage(statusCode: Int, body: String): String {
        val detail = runCatching {
            val element = json.parseToJsonElement(body)
            val value = (element as? JsonObject)?.get("detail")
            when (value) {
                is JsonPrimitive -> value.jsonPrimitive.contentOrNull
                else -> value?.toString()
            }
        }.getOrNull()

        return detail?.takeIf { it.isNotBlank() }
            ?: body.takeIf { it.isNotBlank() }
            ?: "Jamarr request failed with HTTP $statusCode"
    }
}
