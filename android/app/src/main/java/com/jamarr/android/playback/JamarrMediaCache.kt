package com.jamarr.android.playback

import android.content.Context
import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.util.UnstableApi
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.cache.Cache
import androidx.media3.datasource.cache.CacheEvictor
import androidx.media3.datasource.cache.CacheKeyFactory
import androidx.media3.datasource.cache.CacheSpan
import androidx.media3.datasource.cache.ContentMetadata
import androidx.media3.datasource.cache.NoOpCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import com.jamarr.android.auth.SettingsStore
import java.io.File
import java.util.TreeSet

/**
 * The two on-disk media caches, chained above the stream-URL resolver.
 *
 * They have opposite eviction policies, hence two of them:
 *
 * - [downloadCache] holds user downloads. Never evicted automatically; only an
 *   explicit removal deletes anything. Playback reads it but never writes it.
 * - [prefetchCache] holds read-ahead data for online playback and is evicted
 *   least-recently-used once it exceeds the read-ahead cap (a setting).
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

    private val prefetchEvictor = AdjustableLruCacheEvictor(SettingsStore.DEFAULT_PREFETCH_MAX_BYTES)

    val prefetchCache: Cache = SimpleCache(
        File(context.cacheDir, PREFETCH_DIR),
        prefetchEvictor,
        databaseProvider,
    )

    /** True when the whole track is on disk: downloaded at any quality, or read ahead at [quality]. */
    fun isFullyCached(trackId: Long, quality: String?): Boolean =
        downloadedQuality(trackId, quality) != null ||
            isFullyCached(prefetchCache, StreamCacheKeys.trackKey(trackId, quality))

    /** The quality [trackId] is downloaded at, preferring [preferred]; null when not downloaded. */
    fun downloadedQuality(trackId: Long, preferred: String?): String? =
        StreamCacheKeys.downloadedQuality(preferred) { quality ->
            isFullyCached(downloadCache, StreamCacheKeys.trackKey(trackId, quality))
        }

    /** Bytes of downloaded media on disk. */
    fun downloadBytes(): Long = downloadCache.cacheSpace

    /** Bytes of read-ahead media on disk. */
    fun readAheadBytes(): Long = prefetchCache.cacheSpace

    /** Applies a new read-ahead cap, evicting at once if the cache is now over it. */
    fun setPrefetchMaxBytes(maxBytes: Long) = prefetchEvictor.setMaxBytes(prefetchCache, maxBytes)

    /** Drops every read-ahead byte. Downloads are untouched. */
    fun clearPrefetch() {
        // SimpleCache's methods synchronise on the instance; holding the same
        // monitor keeps the key snapshot and the removals consistent.
        synchronized(prefetchCache) {
            prefetchCache.keys.toList().forEach { prefetchCache.removeResource(it) }
        }
    }

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
    }
}

/**
 * Media3's `LeastRecentlyUsedCacheEvictor`, with a ceiling that can change
 * while the cache is open. Media3's fixes it at construction, and `SimpleCache`
 * cannot be reopened in-process, so a new setting would otherwise only apply
 * after a restart.
 *
 * Every callback runs under the cache's lock; [setMaxBytes] takes the same lock
 * before trimming, so the span set is never touched from two threads at once.
 */
@OptIn(markerClass = [UnstableApi::class])
class AdjustableLruCacheEvictor(initialMaxBytes: Long) : CacheEvictor {
    @Volatile
    private var maxBytes = initialMaxBytes
    private val leastRecentlyUsed = TreeSet<CacheSpan>(::compareSpans)
    private var currentSize = 0L

    fun setMaxBytes(cache: Cache, bytes: Long) {
        maxBytes = bytes
        synchronized(cache) { evict(cache, 0) }
    }

    override fun requiresCacheSpanTouches(): Boolean = true

    override fun onCacheInitialized() = Unit

    override fun onStartFile(cache: Cache, key: String, position: Long, length: Long) {
        if (length != C.LENGTH_UNSET.toLong()) evict(cache, length)
    }

    override fun onSpanAdded(cache: Cache, span: CacheSpan) {
        leastRecentlyUsed.add(span)
        currentSize += span.length
        evict(cache, 0)
    }

    override fun onSpanRemoved(cache: Cache, span: CacheSpan) {
        leastRecentlyUsed.remove(span)
        currentSize -= span.length
    }

    override fun onSpanTouched(cache: Cache, oldSpan: CacheSpan, newSpan: CacheSpan) {
        onSpanRemoved(cache, oldSpan)
        onSpanAdded(cache, newSpan)
    }

    private fun evict(cache: Cache, requiredSpace: Long) {
        while (currentSize + requiredSpace > maxBytes && leastRecentlyUsed.isNotEmpty()) {
            cache.removeSpan(leastRecentlyUsed.first())
        }
    }

    private fun compareSpans(lhs: CacheSpan, rhs: CacheSpan): Int {
        if (lhs.lastTouchTimestamp == rhs.lastTouchTimestamp) return lhs.compareTo(rhs)
        return if (lhs.lastTouchTimestamp < rhs.lastTouchTimestamp) -1 else 1
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

/**
 * Key factory for the read-only download layer of playback: the key of the
 * quality the track is actually downloaded at, which need not be the quality
 * being played. Falls back to the active quality's key, a guaranteed miss that
 * passes the read on to the read-ahead cache and the network.
 */
@OptIn(markerClass = [UnstableApi::class])
class DownloadedCacheKeyFactory(
    private val mediaCache: JamarrMediaCache,
    private val qualityProvider: () -> String,
) : CacheKeyFactory {
    override fun buildCacheKey(dataSpec: DataSpec): String {
        val trackId = StreamCacheKeys.trackIdFromUri(dataSpec.uri.toString())
            ?: return CacheKeyFactory.DEFAULT.buildCacheKey(dataSpec)
        val active = qualityProvider()
        return StreamCacheKeys.trackKey(trackId, mediaCache.downloadedQuality(trackId, active) ?: active)
    }
}
