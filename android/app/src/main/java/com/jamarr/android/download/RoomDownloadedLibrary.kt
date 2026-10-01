package com.jamarr.android.download

import com.jamarr.android.download.db.DownloadGroupEntity
import com.jamarr.android.download.db.DownloadRecordState
import com.jamarr.android.download.db.DownloadedTrackEntity
import com.jamarr.android.playback.DownloadedLibrary
import java.io.File

/** [DownloadedLibrary] over the download database and the offline art store. */
class RoomDownloadedLibrary(
    private val downloads: JamarrDownloads,
    private val artworkStore: OfflineArtworkStore,
) : DownloadedLibrary {
    private val dao get() = downloads.database.downloadDao()

    override suspend fun groups(): List<DownloadGroupEntity> = dao.allGroups()

    override suspend fun completedTracks(groupId: String?): List<DownloadedTrackEntity> =
        if (groupId == null) {
            dao.tracksByState(DownloadRecordState.COMPLETED)
        } else {
            dao.groupTracks(groupId).filter { it.state == DownloadRecordState.COMPLETED }
        }

    override fun localArtwork(artSha1: String): File? = artworkStore.existing(artSha1)
}
