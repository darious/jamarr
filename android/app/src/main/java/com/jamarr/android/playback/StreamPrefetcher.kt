package com.jamarr.android.playback

import android.util.Log
import androidx.annotation.OptIn
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.cache.CacheWriter
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch

/**
 * Pulls upcoming tracks into the prefetch cache before the player needs them.
 *
 * Only *upcoming* tracks are prefetched, never the one playing. Writing the
 * current track from two places at once would have the prefetch writer and the
 * player's own cache writer contending for the same cache key; the player would
 * fall back to an uncached upstream read and fetch the same bytes twice. The
 * track in progress is covered by the ExoPlayer buffer instead
 * (see the load control in [JamarrPlaybackService]).
 *
 * Net effect: after the first track of a queue, every following track is
 * already on disk before it starts, so a network blip between tracks is
 * invisible and the next track starts instantly.
 */
@OptIn(markerClass = [UnstableApi::class])
class StreamPrefetcher(
    private val scope: CoroutineScope,
    private val dataSourceFactory: CacheDataSource.Factory,
    private val mediaCache: JamarrMediaCache,
    private val qualityProvider: () -> String,
    /**
     * Whether read-ahead may use the network right now — false when the
     * wifi-only setting is on and the active network is metered. Injected as a
     * lambda so this class stays free of Android types and unit-testable, and
     * so it is re-read per prefetch rather than captured once.
     */
    private val networkAllows: () -> Boolean = { true },
) {
    private val job = AtomicReference<Job?>(null)
    private val activeWriter = AtomicReference<CacheWriter?>(null)
    private val inFlight = AtomicReference<List<Long>>(emptyList())

    /**
     * Prefetches [trackIds] in order. A repeat call with the same targets is a
     * no-op so player callbacks can fire it freely; any other call cancels the
     * work in progress.
     */
    fun prefetch(trackIds: List<Long>) {
        val targets = PrefetchPolicy.targets(trackIds)
        if (targets == inFlight.get() && job.get()?.isActive == true) return

        cancel()
        if (targets.isEmpty()) return

        // Re-evaluated on the next player event (transition, timeline change,
        // STATE_READY) rather than watched continuously, so moving back onto
        // wifi resumes read-ahead at the next track instead of instantly.
        if (!networkAllows()) return

        inFlight.set(targets)
        job.set(
            scope.launch(Dispatchers.IO) {
                for (trackId in targets) {
                    ensureActive()
                    cacheTrack(trackId)
                }
            },
        )
    }

    fun cancel() {
        activeWriter.getAndSet(null)?.cancel()
        job.getAndSet(null)?.cancel()
        inFlight.set(emptyList())
    }

    private fun cacheTrack(trackId: Long) {
        val quality = qualityProvider()
        if (mediaCache.isFullyCached(trackId, quality)) return

        val dataSpec = DataSpec.Builder()
            .setUri(JamarrPlaybackService.trackUri(trackId))
            .setKey(StreamCacheKeys.trackKey(trackId, quality))
            .build()

        val writer = CacheWriter(
            dataSourceFactory.createDataSource(),
            dataSpec,
            /* temporaryBuffer= */ null,
            /* progressListener= */ null,
        )
        activeWriter.set(writer)
        try {
            writer.cache()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            // Prefetch is best-effort: an offline server, an expired session or
            // a cancelled write must never surface to playback.
            Log.d(TAG, "Prefetch of track $trackId stopped: ${e.message}")
        } finally {
            activeWriter.compareAndSet(writer, null)
        }
    }

    private companion object {
        const val TAG = "StreamPrefetcher"
    }
}
