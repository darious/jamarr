package com.jamarr.android.data

import com.jamarr.android.auth.TokenHolder
import java.net.URI
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response

class JamarrApiException(
    val statusCode: Int,
    message: String,
) : Exception(message)

class JamarrApiClient(
    private val tokenHolder: TokenHolder = TokenHolder(),
    cookieJar: CookieJar = CookieJar.NO_COOKIES,
    private val onTokenRefreshed: suspend (String) -> Unit = {},
    private val onRefreshFailed: suspend () -> Unit = {},
    private val json: Json = Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
    },
) {
    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()
    private val refreshLock = Any()
    private val callbackScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    // Cooldown after a refresh fails to prevent loops (e.g. background loops
    // that keep firing requests while the refresh token is permanently invalid).
    @Volatile private var refreshFailedAtMs: Long = 0L
    private val refreshCooldownMs: Long = 60_000L

    private val authInterceptor = Interceptor { chain ->
        val original = chain.request()
        val path = original.url.encodedPath
        val skip = path.endsWith("/api/auth/login") || path.endsWith("/api/auth/refresh")
        if (skip || original.header("Authorization") != null) {
            return@Interceptor chain.proceed(original)
        }
        val token = tokenHolder.get()
        val request = if (token.isNotBlank()) {
            original.newBuilder().header("Authorization", "Bearer $token").build()
        } else original
        chain.proceed(request)
    }

    private val httpClient: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(5, java.util.concurrent.TimeUnit.SECONDS)
        .readTimeout(30, java.util.concurrent.TimeUnit.SECONDS)
        .writeTimeout(5, java.util.concurrent.TimeUnit.SECONDS)
        .cookieJar(cookieJar)
        .addInterceptor(authInterceptor)
        .authenticator { _, response ->
            handleAuthChallenge(response)
        }
        .build()

    private fun handleAuthChallenge(response: Response): Request? {
        val req = response.request
        val path = req.url.encodedPath
        if (path.endsWith("/api/auth/login") || path.endsWith("/api/auth/refresh")) return null
        if (response.priorResponse != null) {
            callbackScope.launch { onRefreshFailed() }
            return null
        }
        val failedAuth = req.header("Authorization")
        val failedToken = failedAuth?.removePrefix("Bearer ")?.trim()
        val newToken = refreshTokenSync(req.url, failedToken) ?: return null
        return req.newBuilder().header("Authorization", "Bearer $newToken").build()
    }

    private fun refreshTokenSync(originalUrl: HttpUrl, failedToken: String?): String? {
        synchronized(refreshLock) {
            val current = tokenHolder.get()
            if (current.isNotBlank() && current != failedToken) {
                return current
            }
            val now = System.currentTimeMillis()
            val sinceFailure = now - refreshFailedAtMs
            if (refreshFailedAtMs > 0L && sinceFailure < refreshCooldownMs) {
                // Recent refresh failure — don't hammer the server. Caller
                // should treat this as an auth failure and stop retrying.
                return null
            }
            val refreshUrl = originalUrl.newBuilder()
                .encodedPath("/api/auth/refresh")
                .query(null)
                .fragment(null)
                .build()
            val refreshRequest = Request.Builder()
                .url(refreshUrl)
                .post("".toRequestBody(jsonMediaType))
                .build()
            val newToken = runCatching {
                httpClient.newCall(refreshRequest).execute().use { resp ->
                    if (!resp.isSuccessful) return@use null
                    val body = resp.body.string()
                    json.decodeFromString<RefreshResponse>(body).accessToken
                }
            }.getOrNull()
            return if (newToken.isNullOrBlank()) {
                refreshFailedAtMs = System.currentTimeMillis()
                tokenHolder.clear()
                callbackScope.launch { onRefreshFailed() }
                null
            } else {
                refreshFailedAtMs = 0L
                tokenHolder.set(newToken)
                callbackScope.launch { onTokenRefreshed(newToken) }
                newToken
            }
        }
    }

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
            .build()

        execute(request)
    }

    suspend fun home(
        serverUrl: String,
        accessToken: String,
        limit: Int = 20,
    ): HomeContent = withContext(Dispatchers.IO) {
        HomeContent(
            newReleases = get(serverUrl, "/api/home/new-releases", limit),
            recentlyAddedAlbums = get(serverUrl, "/api/home/recently-added-albums", limit),
            recentlyPlayedAlbums = get(serverUrl, "/api/history/albums", limit),
            discoverArtists = get(serverUrl, "/api/home/discover-artists", limit),
            recentlyPlayedArtists = get(serverUrl, "/api/history/artists", limit),
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

        val request = Request.Builder().url(url).get().build()
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
            .build()
        execute(request)
    }

    suspend fun recentlyPlayedTracks(
        serverUrl: String,
        accessToken: String,
        limit: Int = 30,
    ): List<SearchTrack> = withContext(Dispatchers.IO) {
        val url = apiUrl(serverUrl, "/api/history/tracks")
            .toHttpUrl()
            .newBuilder()
            .addQueryParameter("limit", limit.toString())
            .addQueryParameter("scope", "mine")
            .build()
        val request = Request.Builder().url(url).get().build()
        val entries: List<PlaybackHistoryEntry> = execute(request)
        val seen = HashSet<Long>()
        entries.mapNotNull { e ->
            val t = e.track ?: return@mapNotNull null
            if (!seen.add(t.id)) return@mapNotNull null
            SearchTrack(
                id = t.id,
                title = t.title,
                artist = t.artist,
                album = t.album,
                mbReleaseId = t.mbReleaseId,
                durationSeconds = t.durationSeconds,
                artSha1 = t.artSha1,
            )
        }
    }

    suspend fun streamUrl(
        serverUrl: String,
        accessToken: String,
        trackId: Long,
        rendererKind: String? = null,
    ): String = withContext(Dispatchers.IO) {
        val url = apiUrl(serverUrl, "/api/stream-url/$trackId")
            .toHttpUrl()
            .newBuilder()
            .apply {
                if (!rendererKind.isNullOrBlank()) {
                    addQueryParameter("renderer_kind", rendererKind)
                }
            }
            .build()
        val request = Request.Builder()
            .url(url)
            .get()
            .build()

        resolveUrl(serverUrl, execute<StreamUrlResponse>(request).url)
    }

    suspend fun favoriteArtists(
        serverUrl: String,
        accessToken: String,
    ): List<FavoriteArtist> = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/favorites/artists"))
            .get()
            .build()
        execute(request)
    }

    suspend fun favoriteReleases(
        serverUrl: String,
        accessToken: String,
    ): List<FavoriteRelease> = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/favorites/releases"))
            .get()
            .build()
        execute(request)
    }

    suspend fun setArtistFavorite(
        serverUrl: String,
        accessToken: String,
        artistMbid: String,
        favorite: Boolean,
    ): Unit = withContext(Dispatchers.IO) {
        val body = json.encodeToString(FavoriteToggleRequest(favorite)).toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/favorites/artists/$artistMbid"))
            .put(body)
            .build()
        httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                val b = response.body.string()
                throw JamarrApiException(response.code, errorMessage(response.code, b))
            }
        }
    }

    suspend fun setAlbumFavorite(
        serverUrl: String,
        accessToken: String,
        albumMbid: String,
        favorite: Boolean,
    ): Unit = withContext(Dispatchers.IO) {
        val body = json.encodeToString(FavoriteToggleRequest(favorite)).toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/favorites/releases/$albumMbid"))
            .put(body)
            .build()
        httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                val b = response.body.string()
                throw JamarrApiException(response.code, errorMessage(response.code, b))
            }
        }
    }

    suspend fun logout(serverUrl: String): Unit = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/auth/logout"))
            .post("".toRequestBody(jsonMediaType))
            .build()
        runCatching {
            httpClient.newCall(request).execute().use { /* best-effort */ }
        }
    }

    fun artworkUrl(serverUrl: String, artSha1: String?, maxSize: Int = 400): String? {
        if (artSha1.isNullOrBlank()) return null
        return resolveUrl(serverUrl, "/api/art/file/$artSha1?max_size=$maxSize")
    }

    suspend fun fetchArtworkBytes(
        serverUrl: String,
        artSha1: String?,
        maxSize: Int = 400,
    ): ByteArray? = withContext(Dispatchers.IO) {
        val url = artworkUrl(serverUrl, artSha1, maxSize) ?: return@withContext null
        val request = Request.Builder().url(url).get().build()
        runCatching {
            httpClient.newCall(request).execute().use { resp ->
                if (!resp.isSuccessful) null else resp.body.bytes()
            }
        }.getOrNull()
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
            .build()

        return execute(request)
    }

    suspend fun reportQueue(
        serverUrl: String,
        clientId: String,
        tracks: List<SearchTrack>,
        startIndex: Int,
    ) = withContext(Dispatchers.IO) {
        val payload = buildJsonObject {
            put("start_index", startIndex)
            put("queue", buildJsonArray {
                tracks.forEach { t ->
                    add(buildJsonObject {
                        put("id", t.id)
                        put("title", t.title)
                        put("artist", t.artist ?: "Unknown Artist")
                        put("album", t.album ?: "Unknown Album")
                        put("duration_seconds", t.durationSeconds ?: 0.0)
                        t.artSha1?.let { put("art_sha1", it) }
                        t.mbReleaseId?.let { put("mb_release_id", it) }
                    })
                }
            })
        }
        val body = payload.toString().toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/player/queue"))
            .header("X-Jamarr-Client-Id", clientId)
            .post(body)
            .build()
        httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                val b = response.body.string()
                throw JamarrApiException(response.code, errorMessage(response.code, b))
            }
        }
    }

    suspend fun reportIndex(
        serverUrl: String,
        clientId: String,
        index: Int,
    ) = withContext(Dispatchers.IO) {
        val payload = buildJsonObject { put("index", index) }
        val body = payload.toString().toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/player/index"))
            .header("X-Jamarr-Client-Id", clientId)
            .post(body)
            .build()
        httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                val b = response.body.string()
                throw JamarrApiException(response.code, errorMessage(response.code, b))
            }
        }
    }

    suspend fun reportProgress(
        serverUrl: String,
        clientId: String,
        positionSeconds: Double,
        isPlaying: Boolean,
    ) = withContext(Dispatchers.IO) {
        val payload = buildJsonObject {
            put("position_seconds", positionSeconds)
            put("is_playing", isPlaying)
        }
        val body = payload.toString().toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/player/progress"))
            .header("X-Jamarr-Client-Id", clientId)
            .post(body)
            .build()
        runCatching {
            httpClient.newCall(request).execute().use { it.body.string() }
        }
    }

    suspend fun getRenderers(
        serverUrl: String,
        refresh: Boolean = false,
    ): List<Renderer> = withContext(Dispatchers.IO) {
        val builder = apiUrl(serverUrl, "/api/renderers").toHttpUrl().newBuilder()
        if (refresh) builder.addQueryParameter("refresh", "true")
        val request = Request.Builder().url(builder.build()).get().build()
        execute(request)
    }

    suspend fun setRenderer(
        serverUrl: String,
        clientId: String,
        rendererIdOrUdn: String,
    ): Unit = withContext(Dispatchers.IO) {
        val payload = buildJsonObject { put("renderer_id", rendererIdOrUdn) }
        val body = payload.toString().toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/player/renderer"))
            .header("X-Jamarr-Client-Id", clientId)
            .post(body)
            .build()
        httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                val b = response.body.string()
                throw JamarrApiException(response.code, errorMessage(response.code, b))
            }
        }
    }

    suspend fun getPlayerState(
        serverUrl: String,
        clientId: String,
    ): PlayerStateResponse = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/player/state"))
            .header("X-Jamarr-Client-Id", clientId)
            .get()
            .build()
        execute(request)
    }

    suspend fun remotePause(
        serverUrl: String,
        clientId: String,
    ): Unit = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/player/pause"))
            .header("X-Jamarr-Client-Id", clientId)
            .post("".toRequestBody(jsonMediaType))
            .build()
        httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                val b = response.body.string()
                throw JamarrApiException(response.code, errorMessage(response.code, b))
            }
        }
    }

    suspend fun remoteResume(
        serverUrl: String,
        clientId: String,
    ): Unit = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/player/resume"))
            .header("X-Jamarr-Client-Id", clientId)
            .post("".toRequestBody(jsonMediaType))
            .build()
        httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                val b = response.body.string()
                throw JamarrApiException(response.code, errorMessage(response.code, b))
            }
        }
    }

    suspend fun remoteSeek(
        serverUrl: String,
        clientId: String,
        seconds: Double,
    ): Unit = withContext(Dispatchers.IO) {
        val payload = buildJsonObject { put("seconds", seconds) }
        val body = payload.toString().toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/player/seek"))
            .header("X-Jamarr-Client-Id", clientId)
            .post(body)
            .build()
        httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                val b = response.body.string()
                throw JamarrApiException(response.code, errorMessage(response.code, b))
            }
        }
    }

    suspend fun remoteVolume(
        serverUrl: String,
        clientId: String,
        percent: Int,
    ): Unit = withContext(Dispatchers.IO) {
        val payload = buildJsonObject { put("percent", percent) }
        val body = payload.toString().toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/player/volume"))
            .header("X-Jamarr-Client-Id", clientId)
            .post(body)
            .build()
        httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                val b = response.body.string()
                throw JamarrApiException(response.code, errorMessage(response.code, b))
            }
        }
    }

    suspend fun remotePlay(
        serverUrl: String,
        clientId: String,
        trackId: Long,
    ): Unit = withContext(Dispatchers.IO) {
        val payload = buildJsonObject { put("track_id", trackId) }
        val body = payload.toString().toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/player/play"))
            .header("X-Jamarr-Client-Id", clientId)
            .post(body)
            .build()
        httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                val b = response.body.string()
                throw JamarrApiException(response.code, errorMessage(response.code, b))
            }
        }
    }

    suspend fun remoteClearQueue(
        serverUrl: String,
        clientId: String,
    ): Unit = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(apiUrl(serverUrl, "/api/player/queue/clear"))
            .header("X-Jamarr-Client-Id", clientId)
            .post("".toRequestBody(jsonMediaType))
            .build()
        httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                val b = response.body.string()
                throw JamarrApiException(response.code, errorMessage(response.code, b))
            }
        }
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
