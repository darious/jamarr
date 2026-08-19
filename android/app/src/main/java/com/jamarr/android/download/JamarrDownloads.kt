package com.jamarr.android.download

import android.content.Context
import androidx.annotation.OptIn
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.datasource.ResolvingDataSource
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.exoplayer.offline.DefaultDownloadIndex
import androidx.media3.exoplayer.offline.DefaultDownloaderFactory
import androidx.media3.exoplayer.offline.Download
import androidx.media3.exoplayer.offline.DownloadManager
import androidx.media3.exoplayer.offline.DownloadRequest
import androidx.media3.exoplayer.offline.DownloadService
import androidx.media3.exoplayer.scheduler.Requirements
import com.jamarr.android.JamarrApplication
import com.jamarr.android.auth.SettingsStore
import com.jamarr.android.data.JamarrApiClient
import com.jamarr.android.data.SearchTrack
import com.jamarr.android.download.db.DownloadGroupEntity
import com.jamarr.android.download.db.DownloadGroupKind
import com.jamarr.android.download.db.DownloadRecordState
import com.jamarr.android.download.db.DownloadedTrackEntity
import com.jamarr.android.download.db.JamarrDownloadDatabase
import com.jamarr.android.playback.JamarrCacheKeyFactory
import com.jamarr.android.playback.JamarrPlaybackService
import com.jamarr.android.playback.StreamCacheKeys
import com.jamarr.android.playback.StreamUrlResolver
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Everything the download engine needs, built once per process.
 *
 * Downloads resolve stream URLs through the same [StreamUrlResolver] and the
 * same cache keys as playback, so a finished download is indistinguishable from
 * a cache hit when the track is later played — no offline-specific playback
 * path exists, or needs to.
 *
 * Its own session state is loaded here rather than borrowed from whoever
 * happens to be running: WorkManager can restart a download after a reboot,
 * with no UI and no playback service alive to have primed the token.
 */
@OptIn(markerClass = [UnstableApi::class])
class JamarrDownloads(context: Context) {
    private val appContext = context.applicationContext
    private val app = appContext as JamarrApplication
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val settingsStore = SettingsStore(appContext)
    private val serverUrl = AtomicReference("")
    private val settingsLoaded = CompletableDeferred<Unit>()

    val database: JamarrDownloadDatabase by lazy { JamarrDownloadDatabase.build(appContext) }

    private val apiClient = JamarrApiClient(
        tokenHolder = app.tokenHolder,
        cookieJar = app.cookieJar,
        onTokenRefreshed = { token -> settingsStore.saveAccessToken(token) },
        onRefreshFailed = { settingsStore.clearAccessToken() },
        onForceLogout = {
            settingsStore.clearAccessToken()
            app.cookieJar.clear()
        },
    )

    private val resolver = StreamUrlResolver(
        apiClient = apiClient,
        serverUrlProvider = { serverUrl.get() },
        tokenProvider = { app.tokenHolder.get() },
        awaitReady = { settingsLoaded.await() },
    )

    val downloadManager: DownloadManager by lazy { buildDownloadManager() }

    private val _states = MutableStateFlow<Map<Long, DownloadProgress>>(emptyMap())

    /** Live per-track download state for the UI. */
    val states: StateFlow<Map<Long, DownloadProgress>> = _states.asStateFlow()

    /** Everything the user has downloaded, newest first. */
    fun observeTracks(): Flow<List<DownloadedTrackEntity>> = database.downloadDao().observeTracks()

    init {
        downloadManager.addListener(
            object : DownloadManager.Listener {
                override fun onDownloadChanged(
                    downloadManager: DownloadManager,
                    download: Download,
                    finalException: Exception?,
                ) {
                    publish(download)
                }

                override fun onDownloadRemoved(
                    downloadManager: DownloadManager,
                    download: Download,
                ) {
                    val trackId = StreamCacheKeys.trackIdFromUri(download.request.uri.toString())
                        ?: return
                    _states.update { it - trackId }
                }
            },
        )
        scope.launch { loadInitialStates() }

        scope.launch {
            val saved = settingsStore.load()
            serverUrl.set(saved.serverUrl)
            if (app.tokenHolder.get().isBlank()) app.tokenHolder.set(saved.accessToken)
            app.cookieJar.prime()
            settingsLoaded.complete(Unit)
            settingsStore.observeSession().collectLatest { serverUrl.set(it.serverUrl) }
        }
        scope.launch {
            settingsStore.observeWifiOnlyTransfers().collectLatest { wifiOnly ->
                downloadManager.requirements = requirements(wifiOnly)
            }
        }
    }

    /**
     * Queues one track and records the request.
     *
     * A standalone track gets a group of its own so removal is uniform: a track
     * disappears when its last group goes, and one shared by an album survives.
     */
    suspend fun downloadTrack(track: SearchTrack) {
        val now = System.currentTimeMillis()
        database.downloadDao().addGroup(
            group = DownloadGroupEntity(
                groupId = trackGroupId(track.id),
                kind = DownloadGroupKind.TRACK,
                title = track.title,
                subtitle = track.artist,
                artSha1 = track.artSha1,
                requestedAt = now,
            ),
            tracks = listOf(
                DownloadedTrackEntity(
                    trackId = track.id,
                    title = track.title,
                    artist = track.artist,
                    album = track.album,
                    albumMbid = track.mbReleaseId,
                    artistMbid = null,
                    artSha1 = track.artSha1,
                    durationSeconds = track.durationSeconds,
                    quality = DOWNLOAD_QUALITY,
                    sizeBytes = 0L,
                    state = DownloadRecordState.QUEUED,
                    addedAt = now,
                ),
            ),
        )

        val key = StreamCacheKeys.trackKey(track.id, DOWNLOAD_QUALITY)
        DownloadService.sendAddDownload(
            appContext,
            JamarrDownloadService::class.java,
            DownloadRequest.Builder(key, JamarrPlaybackService.trackUri(track.id))
                .setCustomCacheKey(key)
                .build(),
            /* foreground= */ false,
        )
    }

    suspend fun removeTrack(trackId: Long) = removeGroup(trackGroupId(trackId))

    /** Drops a group and deletes the cached bytes of tracks nothing else holds. */
    suspend fun removeGroup(groupId: String) {
        database.downloadDao().removeGroup(groupId).forEach { trackId ->
            DownloadService.sendRemoveDownload(
                appContext,
                JamarrDownloadService::class.java,
                StreamCacheKeys.trackKey(trackId, DOWNLOAD_QUALITY),
                /* foreground= */ false,
            )
            _states.update { it - trackId }
        }
    }

    private fun publish(download: Download) {
        val trackId = StreamCacheKeys.trackIdFromUri(download.request.uri.toString()) ?: return
        val state = recordState(download.state)
        _states.update {
            it + (
                trackId to DownloadProgress(
                    trackId = trackId,
                    state = state,
                    percent = download.percentDownloaded.takeIf { percent -> percent >= 0f },
                )
                )
        }
        scope.launch {
            database.downloadDao().updateState(trackId, state, download.bytesDownloaded)
        }
    }

    /**
     * Media3's download index is the source of truth across process restarts;
     * Room only records intent, so states are rebuilt from the index on start.
     */
    private fun loadInitialStates() {
        runCatching {
            downloadManager.downloadIndex.getDownloads().use { cursor ->
                val snapshot = mutableMapOf<Long, DownloadProgress>()
                while (cursor.moveToNext()) {
                    val download = cursor.download
                    val trackId =
                        StreamCacheKeys.trackIdFromUri(download.request.uri.toString()) ?: continue
                    snapshot[trackId] = DownloadProgress(
                        trackId = trackId,
                        state = recordState(download.state),
                        percent = download.percentDownloaded.takeIf { it >= 0f },
                    )
                }
                _states.value = snapshot
            }
        }
    }

    private fun trackGroupId(trackId: Long): String = "track:$trackId"

    private fun buildDownloadManager(): DownloadManager {
        val cache = app.mediaCache.downloadCache
        val resolvingFactory = ResolvingDataSource.Factory(DefaultHttpDataSource.Factory()) { spec ->
            resolver.resolveDataSpec(spec, DOWNLOAD_QUALITY)
        }
        // Same key factory as playback. A download written under a different key
        // would be invisible to the player and re-fetched over the network.
        val downloadDataSourceFactory = CacheDataSource.Factory()
            .setCache(cache)
            .setUpstreamDataSourceFactory(resolvingFactory)
            .setCacheKeyFactory(JamarrCacheKeyFactory { DOWNLOAD_QUALITY })

        return DownloadManager(
            appContext,
            DefaultDownloadIndex(app.mediaCache.databaseProvider),
            DefaultDownloaderFactory(downloadDataSourceFactory, Executors.newFixedThreadPool(2)),
        ).apply {
            maxParallelDownloads = MAX_PARALLEL_DOWNLOADS
        }
    }

    private fun requirements(wifiOnly: Boolean): Requirements = Requirements(
        if (wifiOnly) Requirements.NETWORK_UNMETERED else Requirements.NETWORK,
    )

    companion object {
        /**
         * Downloads are fetched at the playback default so a downloaded track
         * is a cache hit under the key the player looks up. A download-quality
         * setting (phase 5) has to come with a player-side lookup that accepts
         * any downloaded quality, not just the active one.
         */
        const val DOWNLOAD_QUALITY = "original"

        const val MAX_PARALLEL_DOWNLOADS = 2
    }
}
