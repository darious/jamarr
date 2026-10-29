package com.jamarr.android.download

import android.content.Context
import android.os.StatFs
import android.util.Log
import androidx.annotation.OptIn
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.datasource.HttpDataSource
import androidx.media3.datasource.ResolvingDataSource
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.cache.CacheKeyFactory
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
import com.jamarr.android.data.JamarrApiException
import com.jamarr.android.data.SearchTrack
import com.jamarr.android.data.toSearchTrack
import com.jamarr.android.data.topTrackEntries
import com.jamarr.android.download.db.DownloadGroupEntity
import com.jamarr.android.download.db.DownloadGroupKind
import com.jamarr.android.download.db.DownloadGroupTrackEntity
import com.jamarr.android.download.db.DownloadRecordState
import com.jamarr.android.download.db.DownloadedTrackEntity
import com.jamarr.android.download.db.JamarrDownloadDatabase
import com.jamarr.android.playback.JamarrPlaybackService
import com.jamarr.android.playback.StreamCacheKeys
import com.jamarr.android.playback.StreamUrlResolver
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

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

    private val _hold = MutableStateFlow<DownloadHold?>(null)

    /**
     * Why the queue is parked although nothing failed: storage under the
     * reserve ([StorageReservePolicy]), or Media3's network/storage
     * requirements not met. Null while downloads run, or when nothing is queued.
     */
    val hold: StateFlow<DownloadHold?> = _hold.asStateFlow()

    private val storageHeld = AtomicBoolean(false)
    private val notMetRequirements = AtomicInteger(0)
    private val wifiOnlyNow = AtomicBoolean(false)

    // Declared above `init`: the coroutines launched there can run before any
    // property declared further down has been assigned.
    private val lastFreeBytes = AtomicReference(0L)
    private val lastTotalBytes = AtomicReference(0L)

    /** Everything the user has downloaded, newest first. */
    fun observeTracks(): Flow<List<DownloadedTrackEntity>> = database.downloadDao().observeTracks()

    fun observeGroups(): Flow<List<DownloadGroupEntity>> = database.downloadDao().observeGroups()

    fun observeLinks(): Flow<List<DownloadGroupTrackEntity>> = database.downloadDao().observeLinks()

    fun observeGroupTracks(groupId: String): Flow<List<DownloadedTrackEntity>> =
        database.downloadDao().observeGroupTracks(groupId)

    /** One sync at a time; a reconnect during a start-up sync waits its turn. */
    private val syncLock = Mutex()

    init {
        downloadManager.addListener(
            object : DownloadManager.Listener {
                override fun onDownloadChanged(
                    downloadManager: DownloadManager,
                    download: Download,
                    finalException: Exception?,
                ) {
                    publish(download, finalException)
                    scope.launch { checkStorage() }
                }

                override fun onRequirementsStateChanged(
                    downloadManager: DownloadManager,
                    requirements: Requirements,
                    notMet: Int,
                ) {
                    notMetRequirements.set(notMet)
                    refreshHold()
                }

                override fun onIdle(downloadManager: DownloadManager) = refreshHold()

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
                wifiOnlyNow.set(wifiOnly)
                withContext(Dispatchers.Main) { downloadManager.requirements = requirements(wifiOnly) }
            }
        }
        // Free space is re-checked on every download event (above) and, while
        // anything is queued or held, on a timer — a hold must lift when the
        // user deletes something without a download event to prompt it.
        scope.launch {
            while (true) {
                val busy = storageHeld.get() || !downloadManager.isIdle
                if (busy) checkStorage()
                delay(if (busy) STORAGE_POLL_BUSY_MS else STORAGE_POLL_IDLE_MS)
            }
        }
        scope.launch {
            settingsLoaded.await()
            if (!app.connectivity.state.value.isOffline) syncTopTracks()
            app.connectivity.reconnected.collect { syncTopTracks() }
        }
    }

    /**
     * Queues one track and records the request.
     *
     * A standalone track gets a group of its own so removal is uniform: a track
     * disappears when its last group goes, and one shared by an album survives.
     */
    suspend fun downloadTrack(track: SearchTrack) = downloadGroup(
        groupId = DownloadGroupIds.track(track.id),
        kind = DownloadGroupKind.TRACK,
        title = track.title,
        subtitle = track.artist,
        artSha1 = track.artSha1,
        tracks = listOf(track),
    )

    /**
     * Records a group and queues every track in it that is not already on disk.
     *
     * Asking again replaces the group's track list rather than adding to it, so
     * re-requesting a playlist that lost tracks drops them too — and deletes
     * their bytes if nothing else holds them.
     */
    suspend fun downloadGroup(
        groupId: String,
        kind: DownloadGroupKind,
        title: String,
        subtitle: String?,
        artSha1: String?,
        tracks: List<SearchTrack>,
        artistMbid: String? = null,
    ) {
        val now = System.currentTimeMillis()
        val quality = settingsStore.downloadQuality()
        val orphans = database.downloadDao().replaceGroupTracks(
            group = DownloadGroupEntity(
                groupId = groupId,
                kind = kind,
                title = title,
                subtitle = subtitle,
                artSha1 = artSha1,
                requestedAt = now,
            ),
            tracks = tracks.distinctBy { it.id }.map { it.toEntity(artistMbid, quality, now) },
        )
        deleteBytes(orphans)
        // A track already on disk stays at the quality it was fetched at; its
        // row (and so its quality) is kept by insertTrackIfAbsent above.
        tracks.filter { _states.value[it.id]?.isComplete != true }.forEach { enqueue(it, quality) }
        scope.launch { fetchArtwork(listOfNotNull(artSha1) + tracks.mapNotNull { it.artSha1 }) }
    }

    suspend fun removeTrack(trackId: Long) = removeGroup(DownloadGroupIds.track(trackId))

    /**
     * Throws a download's bytes away and fetches them again: playback found
     * the copy on disk unreadable. The row and its groups are kept, so the
     * track stays in the Downloads lists while it is re-fetched.
     */
    suspend fun redownload(trackId: Long) {
        val row = database.downloadDao().track(trackId) ?: return
        DownloadService.sendRemoveDownload(
            appContext,
            JamarrDownloadService::class.java,
            StreamCacheKeys.trackKey(trackId, row.quality),
            /* foreground= */ false,
        )
        database.downloadDao().updateState(trackId, DownloadRecordState.QUEUED, 0L)
        _states.update { it + (trackId to DownloadProgress(trackId, DownloadRecordState.QUEUED, null)) }
        enqueue(
            SearchTrack(id = trackId, title = row.title, artist = row.artist, album = row.album, artSha1 = row.artSha1),
            row.quality,
        )
    }

    /** Drops a group and deletes the cached bytes of tracks nothing else holds. */
    suspend fun removeGroup(groupId: String) {
        deleteBytes(database.downloadDao().removeGroup(groupId))
        pruneArtwork()
    }

    /** Deletes every download: rows, bytes and art. */
    suspend fun removeAll() {
        deleteBytes(database.downloadDao().removeAll())
        pruneArtwork()
    }

    /**
     * Brings every synced top-tracks group up to date with its artist's list:
     * new entries are queued, ones that fell off are dropped (their bytes too,
     * unless another group holds them), and positions follow the new order.
     *
     * A list that fails to load is left alone — an unreachable server must not
     * read as "the list is empty" and wipe the downloads.
     */
    suspend fun syncTopTracks() = syncLock.withLock {
        val dao = database.downloadDao()
        dao.groups(DownloadGroupKind.ARTIST_TOP).forEach { group ->
            val (artistMbid, list) = DownloadGroupIds.parseArtistTop(group.groupId) ?: return@forEach
            val detail = runCatching {
                apiClient.artistDetail(serverUrl.get(), app.tokenHolder.get(), mbid = artistMbid, name = null)
            }.getOrNull() ?: return@forEach
            val latest = detail.topTrackEntries(list).mapNotNull { it.toSearchTrack(detail.name) }
            // Same tracks in the same order: nothing to queue, drop or reorder.
            if (dao.groupTrackIds(group.groupId) == latest.map { it.id }) return@forEach
            downloadGroup(
                groupId = group.groupId,
                kind = DownloadGroupKind.ARTIST_TOP,
                title = group.title,
                subtitle = group.subtitle,
                artSha1 = detail.artSha1 ?: group.artSha1,
                tracks = latest,
                artistMbid = artistMbid,
            )
        }
    }

    private fun enqueue(track: SearchTrack, quality: String) {
        val key = StreamCacheKeys.trackKey(track.id, quality)
        DownloadService.sendAddDownload(
            appContext,
            JamarrDownloadService::class.java,
            DownloadRequest.Builder(key, JamarrPlaybackService.trackUri(track.id))
                .setCustomCacheKey(key)
                .build(),
            /* foreground= */ false,
        )
    }

    private fun deleteBytes(tracks: List<DownloadedTrackEntity>) {
        tracks.forEach { track ->
            DownloadService.sendRemoveDownload(
                appContext,
                JamarrDownloadService::class.java,
                StreamCacheKeys.trackKey(track.trackId, track.quality),
                /* foreground= */ false,
            )
            _states.update { it - track.trackId }
        }
    }

    private suspend fun fetchArtwork(artSha1s: List<String>) {
        settingsLoaded.await()
        artSha1s.distinct().forEach { sha ->
            runCatching {
                app.artworkStore.ensure(sha) {
                    apiClient.fetchArtworkBytes(serverUrl.get(), it, OfflineArtworkStore.SIZE)
                }
            }
        }
    }

    private suspend fun pruneArtwork() {
        val keep = database.downloadDao().referencedArtSha1s().toSet()
        runCatching { app.artworkStore.prune(keep) }
    }

    private fun SearchTrack.toEntity(artistMbid: String?, quality: String, now: Long) = DownloadedTrackEntity(
        trackId = id,
        title = title,
        artist = artist,
        album = album,
        albumMbid = mbReleaseId,
        artistMbid = artistMbid,
        artSha1 = artSha1,
        durationSeconds = durationSeconds,
        quality = quality,
        sizeBytes = 0L,
        state = DownloadRecordState.QUEUED,
        addedAt = now,
    )

    private fun publish(download: Download, finalException: Exception? = null) {
        val trackId = StreamCacheKeys.trackIdFromUri(download.request.uri.toString()) ?: return
        val state = recordState(download.state)
        val reason = if (state == DownloadRecordState.FAILED) {
            DownloadFailures.classify(httpStatusOf(finalException), finalException).also {
                Log.w(TAG, "download of track $trackId failed: $it", finalException)
            }
        } else {
            null
        }
        _states.update {
            it + (
                trackId to DownloadProgress(
                    trackId = trackId,
                    state = state,
                    percent = download.percentDownloaded.takeIf { percent -> percent >= 0f },
                    failureReason = reason,
                )
                )
        }
        scope.launch {
            database.downloadDao().updateState(trackId, state, download.bytesDownloaded, reason?.name)
        }
        refreshHold()
    }

    /** The HTTP status behind a failed request, from media3's exception or the resolver's. */
    private fun httpStatusOf(error: Throwable?): Int? {
        var cause = error
        var hops = 0
        while (cause != null && hops++ < 8) {
            when (cause) {
                is HttpDataSource.InvalidResponseCodeException -> return cause.responseCode
                is JamarrApiException -> return cause.statusCode
            }
            cause = cause.cause
        }
        return null
    }

    // ----- holds: low storage and unmet requirements ---------------------

    /**
     * Pauses the queue before the disk fills and resumes it once space is
     * back; see [StorageReservePolicy] for the reserve. Pausing keeps every
     * partial download resumable — nothing is deleted to make room.
     */
    private suspend fun checkStorage() {
        val (free, total) = runCatching {
            val stat = StatFs(appContext.filesDir.absolutePath)
            stat.availableBytes to stat.totalBytes
        }.getOrElse { return }
        val held = storageHeld.get()
        val shouldHold = StorageReservePolicy.shouldHold(free, total, held)
        if (shouldHold != held) {
            storageHeld.set(shouldHold)
            Log.i(TAG, if (shouldHold) "holding downloads: ${free / MB} MB free" else "resuming downloads: ${free / MB} MB free")
            // Through the service rather than the manager directly, so the
            // foreground service (and its notification) comes back with the
            // queue when the hold lifts, and the request is valid from the
            // background on Android 8+ (startForegroundService).
            withContext(Dispatchers.Main) {
                if (shouldHold) {
                    DownloadService.sendPauseDownloads(appContext, JamarrDownloadService::class.java, /* foreground= */ true)
                } else {
                    DownloadService.sendResumeDownloads(appContext, JamarrDownloadService::class.java, /* foreground= */ true)
                }
            }
        }
        lastFreeBytes.set(free)
        lastTotalBytes.set(total)
        refreshHold()
    }

    private fun refreshHold() {
        val pending = _states.value.values.any {
            it.state == DownloadRecordState.QUEUED || it.state == DownloadRecordState.DOWNLOADING
        }
        val notMet = notMetRequirements.get()
        _hold.value = when {
            !pending -> null
            storageHeld.get() -> DownloadHold.LowStorage(
                freeBytes = lastFreeBytes.get(),
                reserveBytes = StorageReservePolicy.reserveBytes(lastTotalBytes.get()),
            )
            notMet and (Requirements.NETWORK or Requirements.NETWORK_UNMETERED) != 0 ->
                DownloadHold.WaitingForNetwork(wifiOnly = wifiOnlyNow.get())
            notMet and Requirements.DEVICE_STORAGE_NOT_LOW != 0 -> DownloadHold.WaitingForSystemStorage
            else -> null
        }
    }

    // ----- retries -------------------------------------------------------

    /** Queues a failed track again at the quality it was requested at. */
    suspend fun retryTrack(trackId: Long) {
        val row = database.downloadDao().track(trackId) ?: return
        database.downloadDao().updateState(trackId, DownloadRecordState.QUEUED, 0L, null)
        _states.update { it + (trackId to DownloadProgress(trackId, DownloadRecordState.QUEUED, null)) }
        enqueue(
            SearchTrack(id = trackId, title = row.title, artist = row.artist, album = row.album, artSha1 = row.artSha1),
            row.quality,
        )
    }

    /** Retries every failed track, or only those in [groupId]. Missing-on-server tracks are left alone. */
    suspend fun retryFailed(groupId: String? = null) {
        val dao = database.downloadDao()
        val failed = if (groupId == null) dao.failedTracks() else dao.failedTracksInGroup(groupId)
        failed.filter { DownloadFailureReason.fromName(it.failureReason)?.retryable != false }
            .forEach { retryTrack(it.trackId) }
    }

    /**
     * Media3's download index is the source of truth across process restarts;
     * Room only records intent, so states are rebuilt from the index on start.
     */
    private suspend fun loadInitialStates() {
        // Media3 only remembers *that* a download failed; the reason is ours.
        val reasons = runCatching {
            database.downloadDao().failedTracks().associate { it.trackId to DownloadFailureReason.fromName(it.failureReason) }
        }.getOrDefault(emptyMap())
        runCatching {
            downloadManager.downloadIndex.getDownloads().use { cursor ->
                val snapshot = mutableMapOf<Long, DownloadProgress>()
                while (cursor.moveToNext()) {
                    val download = cursor.download
                    val trackId =
                        StreamCacheKeys.trackIdFromUri(download.request.uri.toString()) ?: continue
                    val state = recordState(download.state)
                    snapshot[trackId] = DownloadProgress(
                        trackId = trackId,
                        state = state,
                        percent = download.percentDownloaded.takeIf { it >= 0f },
                        failureReason = if (state == DownloadRecordState.FAILED) {
                            reasons[trackId] ?: DownloadFailureReason.UNKNOWN
                        } else {
                            null
                        },
                    )
                }
                _states.value = snapshot
            }
        }
        checkStorage()
    }

    private fun buildDownloadManager(): DownloadManager {
        val cache = app.mediaCache.downloadCache
        // Each request carries its own key, `track:{id}:{quality}`, so the
        // quality to fetch at is read from it — downloads made under an older
        // quality setting keep fetching (and resuming) at that quality.
        val resolvingFactory = ResolvingDataSource.Factory(DefaultHttpDataSource.Factory()) { spec ->
            resolver.resolveDataSpec(spec, StreamCacheKeys.qualityFromKey(spec.key) ?: FALLBACK_QUALITY)
        }
        // Bytes are written under that same key, which is the key playback's
        // DownloadedCacheKeyFactory looks for.
        val downloadDataSourceFactory = CacheDataSource.Factory()
            .setCache(cache)
            .setUpstreamDataSourceFactory(resolvingFactory)
            .setCacheKeyFactory { spec -> spec.key ?: CacheKeyFactory.DEFAULT.buildCacheKey(spec) }

        return DownloadManager(
            appContext,
            DefaultDownloadIndex(app.mediaCache.databaseProvider),
            DefaultDownloaderFactory(downloadDataSourceFactory, Executors.newFixedThreadPool(2)),
        ).apply {
            maxParallelDownloads = MAX_PARALLEL_DOWNLOADS
        }
    }

    /**
     * Network as the user chose, plus the system's own low-storage signal as
     * a second line behind [StorageReservePolicy]: the OS fires it at the
     * smaller of 5 % / 500 MB, so ours normally trips first.
     */
    private fun requirements(wifiOnly: Boolean): Requirements = Requirements(
        (if (wifiOnly) Requirements.NETWORK_UNMETERED else Requirements.NETWORK) or
            Requirements.DEVICE_STORAGE_NOT_LOW,
    )

    companion object {
        private const val TAG = "JamarrDownloads"

        /** Only reached by a request without a quality in its key, which none are. */
        private const val FALLBACK_QUALITY = "original"

        const val MAX_PARALLEL_DOWNLOADS = 2

        private const val MB = 1024L * 1024L
        const val STORAGE_POLL_BUSY_MS = 15_000L
        const val STORAGE_POLL_IDLE_MS = 60_000L
    }
}
