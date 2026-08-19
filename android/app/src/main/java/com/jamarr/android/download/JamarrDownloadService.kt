package com.jamarr.android.download

import android.app.Notification
import android.app.PendingIntent
import android.content.Intent
import androidx.annotation.OptIn
import androidx.core.app.NotificationCompat
import androidx.media3.common.util.NotificationUtil
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.offline.Download
import androidx.media3.exoplayer.offline.DownloadManager
import androidx.media3.exoplayer.offline.DownloadService
import androidx.media3.exoplayer.scheduler.Scheduler
import androidx.media3.exoplayer.workmanager.WorkManagerScheduler
import com.jamarr.android.JamarrApplication
import com.jamarr.android.MainActivity
import com.jamarr.android.R

/**
 * Foreground service that runs downloads and survives the app being closed.
 *
 * The notification is hand-built rather than taken from Media3's
 * `DownloadNotificationHelper`, which lives in `media3-ui` — a dependency whose
 * View-based player UI this Compose app has no other use for.
 */
@OptIn(markerClass = [UnstableApi::class])
class JamarrDownloadService : DownloadService(
    FOREGROUND_NOTIFICATION_ID,
    DEFAULT_FOREGROUND_NOTIFICATION_UPDATE_INTERVAL,
    CHANNEL_ID,
    R.string.download_channel_name,
    /* channelDescriptionResourceId= */ 0,
) {
    override fun getDownloadManager(): DownloadManager {
        val downloads = (application as JamarrApplication).downloads
        NotificationUtil.createNotificationChannel(
            this,
            CHANNEL_ID,
            R.string.download_channel_name,
            /* descriptionResourceId= */ 0,
            NotificationUtil.IMPORTANCE_LOW,
        )
        return downloads.downloadManager
    }

    // WorkManager rather than PlatformScheduler: it needs no boot permission and
    // requeues the same way on every API level the app supports.
    override fun getScheduler(): Scheduler = WorkManagerScheduler(this, WORK_NAME)

    override fun getForegroundNotification(
        downloads: List<Download>,
        notMetRequirements: Int,
    ): Notification {
        val active = downloads.count { it.state == Download.STATE_DOWNLOADING }
        val queued = downloads.count { it.state == Download.STATE_QUEUED }
        val progress = downloads
            .filter { it.state == Download.STATE_DOWNLOADING }
            .map { it.percentDownloaded }
            .filter { it >= 0f }
        val percent = progress.average().takeIf { progress.isNotEmpty() && !it.isNaN() }

        val text = when {
            notMetRequirements != 0 -> getString(R.string.download_waiting_for_network)
            active == 0 && queued > 0 -> resources.getQuantityString(
                R.plurals.download_queued,
                queued,
                queued,
            )
            else -> resources.getQuantityString(
                R.plurals.download_in_progress,
                active.coerceAtLeast(1),
                active.coerceAtLeast(1),
            )
        }

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setOngoing(true)
            .setSilent(true)
            .setContentIntent(
                PendingIntent.getActivity(
                    this,
                    0,
                    Intent(this, MainActivity::class.java),
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                ),
            )
            .apply {
                if (percent != null) {
                    setProgress(100, percent.toInt(), false)
                } else if (active > 0) {
                    setProgress(0, 0, true)
                }
            }
            .build()
    }

    companion object {
        private const val FOREGROUND_NOTIFICATION_ID = 2
        private const val CHANNEL_ID = "jamarr_downloads"
        private const val WORK_NAME = "jamarr-downloads"
    }
}
