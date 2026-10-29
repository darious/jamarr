package com.jamarr.android.playback

import com.jamarr.android.data.JamarrApiClient
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * The user's favourite albums, for the session's favourite button.
 *
 * The server has no per-album "is favourite" call outside the album detail,
 * so the favourites list is fetched once and held for [ttlMs]; a toggle
 * updates the held set at once (the server confirmed it) rather than
 * refetching. [cached] answers without the network so button state can be
 * built synchronously; [isFavourite] loads when needed.
 */
class AlbumFavourites(
    private val apiClient: JamarrApiClient,
    private val credentials: () -> Pair<String, String>,
    private val ttlMs: Long = TTL_MS,
    private val now: () -> Long = System::currentTimeMillis,
) {
    private class Snapshot(val ids: Set<String>, val loadedAtMs: Long)

    private val snapshot = AtomicReference<Snapshot?>(null)
    private val loadLock = Mutex()

    /** Known state without a network call: null when nothing is loaded yet. */
    fun cached(albumMbid: String): Boolean? =
        snapshot.get()?.takeIf { now() - it.loadedAtMs < ttlMs }?.ids?.contains(albumMbid)

    suspend fun isFavourite(albumMbid: String): Boolean {
        cached(albumMbid)?.let { return it }
        return load().contains(albumMbid)
    }

    /** Flips the album's state on the server; returns the new state. */
    suspend fun toggle(albumMbid: String): Boolean {
        val (server, token) = credentials()
        val desired = !isFavourite(albumMbid)
        apiClient.setAlbumFavorite(server, token, albumMbid, desired)
        snapshot.updateAndGet { current ->
            val ids = current?.ids.orEmpty().toMutableSet()
            if (desired) ids += albumMbid else ids -= albumMbid
            Snapshot(ids, current?.loadedAtMs ?: now())
        }
        return desired
    }

    fun invalidate() {
        snapshot.set(null)
    }

    private suspend fun load(): Set<String> = loadLock.withLock {
        snapshot.get()?.takeIf { now() - it.loadedAtMs < ttlMs }?.let { return it.ids }
        val (server, token) = credentials()
        val ids = apiClient.favoriteReleases(server, token).map { it.albumMbid }.toSet()
        snapshot.set(Snapshot(ids, now()))
        ids
    }

    companion object {
        const val TTL_MS = 5 * 60_000L
    }
}
