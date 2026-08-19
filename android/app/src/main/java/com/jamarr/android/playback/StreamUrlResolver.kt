package com.jamarr.android.playback

import android.net.Uri
import androidx.annotation.OptIn
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSpec
import com.jamarr.android.data.JamarrApiClient
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout

/**
 * Turns `jamarr://track/{id}` into a signed `/api/stream/{id}?token=…` URL.
 *
 * Extracted from the playback service because the download engine needs the
 * identical mapping: both feed a `ResolvingDataSource` below the media caches,
 * and a download that resolved differently from playback would write bytes
 * playback could never find.
 *
 * Holds the short-lived URL cache (the token expires server-side, default 300 s)
 * and the quality labels, which outlive it — once a track plays from disk the
 * resolver stops running, so labels must not die with the token.
 */
@OptIn(markerClass = [UnstableApi::class])
class StreamUrlResolver(
    private val apiClient: JamarrApiClient,
    private val serverUrlProvider: () -> String,
    private val tokenProvider: () -> String,
    /** Blocks until server URL and token are loaded; see `settingsLoaded`. */
    private val awaitReady: suspend () -> Unit = {},
) {
    data class Resolved(
        val url: String,
        val quality: String,
        val qualityLabel: String,
        val originalQualityLabel: String,
        val source: StreamSource?,
        val expiresAtMs: Long,
    )

    data class Labels(
        val quality: String,
        val qualityLabel: String,
        val originalQualityLabel: String,
    )

    private val urlCache = ConcurrentHashMap<String, Resolved>()
    private val labels = ConcurrentHashMap<String, Labels>()

    /**
     * [DataSpec] rewrite for `ResolvingDataSource`. Anything that is not a
     * Jamarr track URI passes through untouched.
     *
     * Blocking on purpose: `ResolvingDataSource.Resolver` is called on a loader
     * thread and may only throw [IOException], so every other failure is
     * wrapped.
     */
    fun resolveDataSpec(spec: DataSpec, quality: String): DataSpec {
        val trackId = StreamCacheKeys.trackIdFromUri(spec.uri.toString())
            ?: return spec
        return spec.withUri(Uri.parse(resolve(trackId, quality).url))
    }

    fun resolve(trackId: Long, quality: String): Resolved {
        // Resumption can start playback before settings finish loading; wait
        // briefly on the calling thread rather than fail the open outright.
        runBlocking { runCatching { withTimeout(SETTINGS_WAIT_MS) { awaitReady() } } }
        val server = serverUrlProvider()
        if (server.isBlank()) throw IOException("Jamarr server URL not set")

        fresh(trackId, quality)?.let { return it }
        urlCache.remove(key(trackId, quality))

        val response = try {
            runBlocking {
                withTimeout(RESOLVE_TIMEOUT_MS) {
                    apiClient.streamUrlInfo(server, tokenProvider(), trackId, quality = quality)
                }
            }
        } catch (e: IOException) {
            throw e
        } catch (e: Exception) {
            throw IOException("Failed to resolve stream URL for track $trackId", e)
        }

        return store(
            trackId,
            Resolved(
                url = response.url,
                quality = response.streamQuality,
                qualityLabel = response.streamQualityLabel,
                originalQualityLabel = response.originalQualityLabel,
                source = StreamSource(response.sourceSampleRateHz, response.sourceBitDepth),
                expiresAtMs = System.currentTimeMillis() + STREAM_URL_TTL_MS,
            ),
        )
    }

    /**
     * Resolves without blocking, for the queue pre-warm loop. Failures are the
     * caller's to swallow: pre-warming is best-effort.
     */
    suspend fun prewarm(trackId: Long, quality: String): Resolved? {
        if (fresh(trackId, quality) != null) return null
        val server = serverUrlProvider()
        val token = tokenProvider()
        if (server.isBlank() || token.isBlank()) return null
        val response = withTimeout(RESOLVE_TIMEOUT_MS) {
            apiClient.streamUrlInfo(server, token, trackId, quality = quality)
        }
        return store(
            trackId,
            Resolved(
                url = response.url,
                quality = response.streamQuality,
                qualityLabel = response.streamQualityLabel,
                originalQualityLabel = response.originalQualityLabel,
                source = StreamSource(response.sourceSampleRateHz, response.sourceBitDepth),
                expiresAtMs = System.currentTimeMillis() + STREAM_URL_TTL_MS,
            ),
        )
    }

    fun labels(trackId: Long, quality: String): Labels? = labels[key(trackId, quality)]

    fun source(trackId: Long, quality: String): StreamSource? =
        urlCache[key(trackId, quality)]?.source

    fun isFresh(trackId: Long, quality: String): Boolean = fresh(trackId, quality) != null

    private fun fresh(trackId: Long, quality: String): Resolved? =
        urlCache[key(trackId, quality)]?.takeIf { it.expiresAtMs > System.currentTimeMillis() }

    private fun store(trackId: Long, resolved: Resolved): Resolved {
        urlCache[key(trackId, resolved.quality)] = resolved
        labels[key(trackId, resolved.quality)] = Labels(
            quality = resolved.quality,
            qualityLabel = resolved.qualityLabel,
            originalQualityLabel = resolved.originalQualityLabel,
        )
        return resolved
    }

    private fun key(trackId: Long, quality: String): String = "$trackId:$quality"

    companion object {
        // Server default STREAM_TOKEN_TTL_SECONDS=300. Cache for 240s so a
        // pre-warmed URL still has ~60s of validity when it is opened.
        const val STREAM_URL_TTL_MS = 240_000L
        const val RESOLVE_TIMEOUT_MS = 5_000L
        const val SETTINGS_WAIT_MS = 5_000L
    }
}
