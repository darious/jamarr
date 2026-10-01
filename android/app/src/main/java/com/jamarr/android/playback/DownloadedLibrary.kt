package com.jamarr.android.playback

import com.jamarr.android.download.db.DownloadGroupEntity
import com.jamarr.android.download.db.DownloadedTrackEntity
import java.io.File

/**
 * What the car's Downloads folder reads: finished downloads and their art,
 * all from the device, so the folder works with no signal.
 */
interface DownloadedLibrary {
    /** Every download group, standalone single tracks included. */
    suspend fun groups(): List<DownloadGroupEntity>

    /** A group's finished tracks in group order, or every finished track when [groupId] is null. */
    suspend fun completedTracks(groupId: String?): List<DownloadedTrackEntity>

    /** The stored artwork file for [artSha1], or null when it is not on disk. */
    fun localArtwork(artSha1: String): File?
}
