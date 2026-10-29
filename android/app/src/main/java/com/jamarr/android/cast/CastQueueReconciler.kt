package com.jamarr.android.cast

import com.jamarr.android.renderer.QueuedTrack

/**
 * Jamarr identity carried in each Cast item's MediaInfo customData.
 *
 * The keys match the server's (`app/services/renderer/cast_backend.py`), so
 * the app and the server can each tell their own items from the other's and
 * from other apps' media. Pure data: the controller converts to/from JSON.
 */
object CastIdentity {
    const val TRACK_ID = "jamarrTrackId"
    const val SOURCE = "jamarrSource"
    const val CONTENT_PATH = "jamarrContentPath"
    const val SERVER = "jamarrServer"
    const val MIME = "jamarrMime"
    const val DURATION = "jamarrDurationSeconds"
    const val ART_URL = "jamarrArtUrl"

    const val SOURCE_ANDROID = "android"
    const val SOURCE_SERVER = "server"

    fun customData(track: QueuedTrack, serverUrl: String?): Map<String, Any?> = buildMap {
        put(TRACK_ID, track.id)
        put(SOURCE, SOURCE_ANDROID)
        if (track.streamUrl.isNotBlank()) put(CONTENT_PATH, contentPath(track.streamUrl))
        serverOrigin(serverUrl ?: track.streamUrl)?.let { put(SERVER, it) }
        put(MIME, track.mime)
        put(DURATION, track.durationSeconds)
        track.artUrl?.let { put(ART_URL, it) }
    }

    fun contentPath(url: String): String = url.substringBefore('?')

    /** `scheme://host[:port]` of a URL, lower-cased; null if it has none. */
    fun serverOrigin(url: String?): String? {
        if (url.isNullOrBlank()) return null
        val scheme = url.substringBefore("://", missingDelimiterValue = "")
        if (scheme.isBlank()) return null
        val authority = url.substringAfter("://").substringBefore('/').substringBefore('?')
        if (authority.isBlank()) return null
        return "${scheme.lowercase()}://${authority.lowercase()}"
    }

    /**
     * The Jamarr track id of [item], or null if it is not a Jamarr item.
     * A stamped content path must match the media itself, so customData that
     * a receiver carried over to other media is not believed.
     */
    fun trackId(item: ReceiverItem): Long? {
        val id = when (val raw = item.custom[TRACK_ID]) {
            is Number -> raw.toLong()
            is String -> raw.toLongOrNull()
            else -> null
        } ?: return null
        val path = item.custom[CONTENT_PATH] as? String
        val content = item.contentId
        if (!path.isNullOrBlank() && !content.isNullOrBlank() && contentPath(content) != path) return null
        return id
    }

    fun source(item: ReceiverItem): String? = item.custom[SOURCE] as? String
}

/** One item as the receiver reports it (from a MediaQueueItem / MediaInfo). */
data class ReceiverItem(
    val itemId: Int,
    val contentId: String?,
    val contentType: String? = null,
    val title: String? = null,
    val artist: String? = null,
    val album: String? = null,
    val artUrl: String? = null,
    val durationSeconds: Double? = null,
    val custom: Map<String, Any?> = emptyMap(),
)

/**
 * What the receiver says it is playing: the full queue order ([itemIds], from
 * MediaQueue), the items fetched so far, and the current item.
 */
data class ReceiverSnapshot(
    val itemIds: List<Int> = emptyList(),
    val items: Map<Int, ReceiverItem> = emptyMap(),
    val currentItemId: Int? = null,
    val currentMedia: ReceiverItem? = null,
)

enum class ReceiverOwnership {
    /** No media on the receiver. */
    NONE,

    /** This app's Jamarr queue (possibly started by another phone). */
    JAMARR,

    /** Jamarr media the server is casting; the server controls it. */
    JAMARR_SERVER,

    /** Another app's media. */
    FOREIGN,
}

data class ReceiverQueue(
    val ownership: ReceiverOwnership,
    val tracks: List<QueuedTrack> = emptyList(),
    val itemIds: List<Int> = emptyList(),
    val currentIndex: Int = -1,
    /** Queue items whose details the receiver has not sent yet. */
    val missingItemIds: List<Int> = emptyList(),
    /** Jamarr items without usable metadata: look them up on the server. */
    val needsMetadata: List<Long> = emptyList(),
    /** Position of the current item in [itemIds] (-1 if unknown). */
    val currentItemIndex: Int = -1,
    /** Jamarr track id of the current item, when it is a Jamarr item. */
    val currentTrackId: Long? = null,
) {
    /** Every item is known and ours, so this can replace the local queue. */
    val complete: Boolean
        get() = ownership == ReceiverOwnership.JAMARR &&
            missingItemIds.isEmpty() &&
            tracks.size == itemIds.size &&
            currentIndex in tracks.indices

    val trackIds: List<Long> get() = tracks.map { it.id }
}

/** A queue this controller has just asked the receiver to play. */
data class LoadExpectation(
    val trackIds: List<Long>,
    val currentTrackId: Long,
    val untilMs: Long,
)

sealed interface QueueSync {
    /** Nothing to change (no media, still loading, or already in step). */
    data object Keep : QueueSync

    /** Take the receiver's queue/current item as the local state. */
    data class Adopt(
        val tracks: List<QueuedTrack>,
        val currentIndex: Int,
        /** The queue itself differs: restored, or changed by another controller. */
        val queueChanged: Boolean,
        /** The receiver now plays what [LoadExpectation] asked for. */
        val expectationMet: Boolean = false,
    ) : QueueSync

    /** Someone else's media is on the receiver. */
    data class NotOurs(val ownership: ReceiverOwnership) : QueueSync
}

sealed interface PlayPlan {
    /** The receiver already holds this queue: jump to the item, no reload. */
    data class JumpTo(val itemId: Int) : PlayPlan

    /** Load the queue, replacing whatever [replacing] says is there. */
    data class Load(val replacing: ReceiverOwnership) : PlayPlan
}

/**
 * Rebuilds Jamarr queue state from what a Cast receiver reports, and decides
 * when that should replace the local state. Pure: no Cast SDK types.
 */
object CastQueueReconciler {

    fun reconstruct(
        snapshot: ReceiverSnapshot,
        known: List<QueuedTrack> = emptyList(),
        serverUrl: String? = null,
        resolved: Map<Long, QueuedTrack> = emptyMap(),
    ): ReceiverQueue {
        val order = snapshot.itemIds.ifEmpty {
            listOfNotNull(snapshot.currentItemId ?: snapshot.currentMedia?.itemId)
        }
        if (order.isEmpty()) return ReceiverQueue(ReceiverOwnership.NONE)
        val knownById = known.associateBy { it.id }
        val ourOrigin = CastIdentity.serverOrigin(serverUrl)
        val tracks = mutableListOf<QueuedTrack>()
        val missing = mutableListOf<Int>()
        val needsMetadata = mutableListOf<Long>()
        val currentItemId = snapshot.currentItemId ?: order.singleOrNull()
        var currentOwnership: ReceiverOwnership? = null
        // Any non-Jamarr item wins over Jamarr ones when the current item is
        // not known yet: a mixed queue is not ours to take over.
        var anyOwnership: ReceiverOwnership? = null
        var currentTrackId: Long? = null
        val trackItemIds = mutableListOf<Int>()
        for (itemId in order) {
            val item = snapshot.items[itemId]
                ?: snapshot.currentMedia?.takeIf { itemId == currentItemId }
            if (item == null) {
                missing += itemId
                continue
            }
            val ownership = classify(item, ourOrigin)
            if (itemId == currentItemId) {
                currentOwnership = ownership
                if (ownership == ReceiverOwnership.JAMARR) currentTrackId = CastIdentity.trackId(item)
            }
            if (anyOwnership == null || ownership != ReceiverOwnership.JAMARR) anyOwnership = ownership
            if (ownership != ReceiverOwnership.JAMARR) continue
            val trackId = CastIdentity.trackId(item) ?: continue
            val local = resolved[trackId] ?: knownById[trackId]
            if (item.title.isNullOrBlank() && local == null) needsMetadata += trackId
            tracks += trackFrom(item, trackId, local)
            trackItemIds += itemId
        }
        val ownership = currentOwnership ?: anyOwnership ?: return ReceiverQueue(
            ReceiverOwnership.NONE,
            itemIds = order,
            missingItemIds = missing,
        )
        val currentIndex = trackItemIds.indexOf(currentItemId)
        return ReceiverQueue(
            ownership = ownership,
            tracks = tracks,
            itemIds = order,
            currentIndex = currentIndex,
            missingItemIds = missing,
            needsMetadata = needsMetadata,
            currentItemIndex = order.indexOf(currentItemId),
            currentTrackId = currentTrackId,
        )
    }

    /**
     * Whether the receiver's view should replace the local queue state.
     *
     * While [expectation] is pending (this controller's own load in flight),
     * statuses describing the previous media are ignored instead of adopted.
     */
    fun sync(
        receiver: ReceiverQueue,
        localQueue: List<QueuedTrack>,
        localIndex: Int,
        expectation: LoadExpectation?,
        nowMs: Long,
    ): QueueSync {
        val pending = expectation != null && nowMs < expectation.untilMs
        when (receiver.ownership) {
            ReceiverOwnership.NONE -> return QueueSync.Keep
            ReceiverOwnership.JAMARR_SERVER, ReceiverOwnership.FOREIGN ->
                return if (pending) QueueSync.Keep else QueueSync.NotOurs(receiver.ownership)
            ReceiverOwnership.JAMARR -> Unit
        }
        if (!receiver.complete) {
            // Not every item fetched yet (long queue, MediaQueue window). The
            // same-length queue on the same current track is taken as ours.
            val sameShape = receiver.itemIds.size == localQueue.size &&
                receiver.currentItemIndex in localQueue.indices &&
                localQueue[receiver.currentItemIndex].id == receiver.currentTrackId
            if (!sameShape) return QueueSync.Keep
            if (pending) {
                val met = expectation.trackIds == localQueue.map { it.id } &&
                    receiver.currentTrackId == expectation.currentTrackId
                return if (met) {
                    QueueSync.Adopt(localQueue, receiver.currentItemIndex, queueChanged = false, expectationMet = true)
                } else {
                    QueueSync.Keep
                }
            }
            return if (receiver.currentItemIndex != localIndex) {
                QueueSync.Adopt(localQueue, receiver.currentItemIndex, queueChanged = false)
            } else {
                QueueSync.Keep
            }
        }
        val ids = receiver.trackIds
        val currentId = receiver.tracks[receiver.currentIndex].id
        if (pending) {
            val met = ids == expectation.trackIds && currentId == expectation.currentTrackId
            return if (met) {
                QueueSync.Adopt(
                    tracks = mergeTracks(localQueue, receiver.tracks).takeIf { localQueue.map { it.id } == ids }
                        ?: mergeTracks(receiver.tracks, localQueue),
                    currentIndex = receiver.currentIndex,
                    queueChanged = false,
                    expectationMet = true,
                )
            } else {
                QueueSync.Keep
            }
        }
        val localIds = localQueue.map { it.id }
        if (ids == localIds) {
            // Details looked up since (server metadata) fill local blanks.
            val merged = mergeTracks(localQueue, receiver.tracks)
            return if (receiver.currentIndex != localIndex || merged != localQueue) {
                QueueSync.Adopt(merged, receiver.currentIndex, queueChanged = false)
            } else {
                QueueSync.Keep
            }
        }
        return QueueSync.Adopt(
            tracks = mergeTracks(receiver.tracks, localQueue),
            currentIndex = receiver.currentIndex,
            queueChanged = true,
        )
    }

    /**
     * Inspect the receiver before replacing its media: when it already holds
     * exactly this queue, jump within it rather than reloading everything.
     */
    fun planPlay(requestedIds: List<Long>, startIndex: Int, receiver: ReceiverQueue): PlayPlan {
        if (receiver.complete && receiver.trackIds == requestedIds && startIndex in receiver.itemIds.indices) {
            return PlayPlan.JumpTo(receiver.itemIds[startIndex])
        }
        return PlayPlan.Load(receiver.ownership)
    }

    private fun classify(item: ReceiverItem, ourOrigin: String?): ReceiverOwnership {
        CastIdentity.trackId(item) ?: return ReceiverOwnership.FOREIGN
        return when (CastIdentity.source(item)) {
            CastIdentity.SOURCE_SERVER -> ReceiverOwnership.JAMARR_SERVER
            CastIdentity.SOURCE_ANDROID -> {
                val origin = item.custom[CastIdentity.SERVER] as? String
                if (ourOrigin != null && origin != null && origin != ourOrigin) {
                    // Another Jamarr server's queue is not ours to drive.
                    ReceiverOwnership.FOREIGN
                } else {
                    ReceiverOwnership.JAMARR
                }
            }
            else -> ReceiverOwnership.FOREIGN
        }
    }

    private fun trackFrom(item: ReceiverItem, trackId: Long, local: QueuedTrack?): QueuedTrack {
        val custom = item.custom
        return QueuedTrack(
            id = trackId,
            title = item.title?.takeIf { it.isNotBlank() } ?: local?.title.orEmpty(),
            artist = item.artist?.takeIf { it.isNotBlank() } ?: local?.artist ?: "Unknown Artist",
            album = item.album?.takeIf { it.isNotBlank() } ?: local?.album ?: "Unknown Album",
            mime = (custom[CastIdentity.MIME] as? String)
                ?: item.contentType
                ?: local?.mime
                ?: "audio/flac",
            durationSeconds = (custom[CastIdentity.DURATION] as? Number)?.toDouble()
                ?: item.durationSeconds?.takeIf { it > 0 }
                ?: local?.durationSeconds
                ?: 0.0,
            // The receiver's own URL is what it plays (and later refetches).
            streamUrl = item.contentId ?: local?.streamUrl.orEmpty(),
            artUrl = item.artUrl ?: (custom[CastIdentity.ART_URL] as? String) ?: local?.artUrl,
        )
    }

    /** Receiver tracks, filling blanks from same-id local tracks. */
    private fun mergeTracks(receiver: List<QueuedTrack>, local: List<QueuedTrack>): List<QueuedTrack> {
        val byId = local.associateBy { it.id }
        return receiver.map { track ->
            val mine = byId[track.id] ?: return@map track
            track.copy(
                title = track.title.ifBlank { mine.title },
                artUrl = track.artUrl ?: mine.artUrl,
                durationSeconds = if (track.durationSeconds > 0) track.durationSeconds else mine.durationSeconds,
            )
        }
    }
}
