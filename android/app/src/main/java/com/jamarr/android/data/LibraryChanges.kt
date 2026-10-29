package com.jamarr.android.data

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow

/** Something the user did that changes what a browse folder lists. */
sealed interface LibraryChange {
    data object FavouriteArtists : LibraryChange
    data object FavouriteReleases : LibraryChange

    /** A playlist's contents or the playlist list; [id] null means the list itself. */
    data class Playlist(val id: Long?) : LibraryChange

    /** A play reached the server (or will, once uploaded): recent and history folders moved. */
    data object History : LibraryChange
}

/**
 * Process-wide channel for library changes made on this phone.
 *
 * The phone UI, the playback service and the download engine share no object
 * graph beyond the application, so the one place a favourite toggle in a
 * Compose screen can tell the car's subscribed folder to refresh is here. The
 * Android Auto provider collects it and turns each change into the cache keys
 * to drop and the folders to re-notify (`LibraryChangeRouter`).
 *
 * Server-originated changes (another client editing a playlist) are not on
 * this channel: the server's event stream only carries scan events, so those
 * still rely on the browse cache's TTL.
 */
class LibraryChanges {
    private val _events = MutableSharedFlow<LibraryChange>(extraBufferCapacity = 64)
    val events: SharedFlow<LibraryChange> = _events.asSharedFlow()

    fun emit(change: LibraryChange) {
        _events.tryEmit(change)
    }
}
