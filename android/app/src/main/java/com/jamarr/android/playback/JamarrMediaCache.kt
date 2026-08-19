package com.jamarr.android.playback

import android.content.Context
import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.util.UnstableApi
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.cache.Cache
import androidx.media3.datasource.cache.CacheKeyFactory
import androidx.media3.datasource.cache.ContentMetadata
import androidx.media3.datasource.cache.LeastRecentlyUsedCacheEvictor
import androidx.media3.datasource.cache.NoOpCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import java.io.File

/**
 * The two on-disk media caches, chained above the stream-URL resolver.
 *
 * They have opposite eviction policies, hence two of them:
 *
 * - [downloadCache] holds user downloads. Never evicted automatically; only an
 *   explicit removal deletes anything. Playback reads it but never writes it.
 * - [prefetchCache] holds read-ahead data for online playback and is evicted
 *   least-recently-used once it exceeds [PREFETCH_MAX_BYTES].
 *
 * `SimpleCache` permits one instance per directory per process, so this is held
 * as a singleton on `JamarrApplication` and shared by every component.
 */
@OptIn(markerClass = [UnstableApi::class])
class JamarrMediaCache(context: Context) {
    /** Also backs the download index, which must share this cache's database. */
    val databaseProvider = StandaloneDatabaseProvider(context)

    val downloadCache: Cache = SimpleCache(
        File(context.filesDir, DOWNLOAD_DIR),
        NoOpCacheEvictor(),
        databaseProvider,
    )

    val prefetchCache: Cache = SimpleCache(
        File(context.cacheDir, PREFETCH_DIR),
        LeastRecentlyUsedCacheEvictor(PREFETCH_MAX_BYTES),
        databaseProvider,
    )

    /** True when the whole track is already on disk in either cache. */
    fun isFullyCached(trackId: Long, quality: String?): Boolean {
        val key = StreamCacheKeys.trackKey(trackId, quality)
        return isFullyCached(downloadCache, key) || isFullyCached(prefetchCache, key)
    }

    fun isDownloaded(trackId: Long, quality: String?): Boolean =
        isFullyCached(downloadCache, StreamCacheKeys.trackKey(trackId, quality))

    private fun isFullyCached(cache: Cache, key: String): Boolean {
        val length = ContentMetadata.getContentLength(cache.getContentMetadata(key))
        if (length == C.LENGTH_UNSET.toLong() || length <= 0L) return false
        return cache.getCachedBytes(key, 0, length) == length
    }

    fun release() {
        downloadCache.release()
        prefetchCache.release()
    }

    companion object {
        private const val DOWNLOAD_DIR = "media_downloads"
        private const val PREFETCH_DIR = "media_prefetch"

        /** LRU ceiling for read-ahead data. Downloads are not counted here. */
        const val PREFETCH_MAX_BYTES = 1024L * 1024L * 1024L
    }
}

/**
 * Maps `jamarr://track/{id}` to a stable cache key at the *current* quality.
 *
 * The quality is read per call rather than baked in, because
 * [AdaptiveStreamQualityPolicy] can downgrade mid-queue and the player re-uses
 * the same `MediaItem`s afterwards.
 */
@OptIn(markerClass = [UnstableApi::class])
class JamarrCacheKeyFactory(private val qualityProvider: () -> String) : CacheKeyFactory {
    override fun buildCacheKey(dataSpec: DataSpec): String {
        val trackId = StreamCacheKeys.trackIdFromUri(dataSpec.uri.toString())
        if (trackId != null) return StreamCacheKeys.trackKey(trackId, qualityProvider())
        return CacheKeyFactory.DEFAULT.buildCacheKey(dataSpec)
    }
}
