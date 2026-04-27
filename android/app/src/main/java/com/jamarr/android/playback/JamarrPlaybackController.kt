package com.jamarr.android.playback

import android.content.ComponentName
import android.content.Context
import android.net.Uri
import android.os.Handler
import android.os.Looper
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import com.google.common.util.concurrent.ListenableFuture
import com.jamarr.android.data.SearchTrack
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.Serializable
import java.util.concurrent.Executor

@Serializable
data class ResolvedTrack(
    val track: SearchTrack,
    val streamUrl: String,
    val artworkUrl: String?,
)

class JamarrPlaybackController(context: Context) {
    private val appContext = context.applicationContext
    private val mainHandler = Handler(Looper.getMainLooper())
    private val mainExecutor = Executor { runnable -> mainHandler.post(runnable) }
    private val controllerFuture: ListenableFuture<MediaController>
    private var controller: MediaController? = null

    val isPlaying: Boolean
        get() = controller?.isPlaying == true

    val currentMediaId: String?
        get() = controller?.currentMediaItem?.mediaId

    val currentMediaItem: MediaItem?
        get() = controller?.currentMediaItem

    val mediaItemCount: Int
        get() = controller?.mediaItemCount ?: 0

    fun currentQueueSnapshot(): List<ResolvedTrack> {
        val c = controller ?: return emptyList()
        val count = c.mediaItemCount
        if (count == 0) return emptyList()

        val orderedIndices: List<Int> = if (c.shuffleModeEnabled) {
            // Walk the player's shuffle order starting from the current item so
            // the queue view shows tracks in the order they'll actually play.
            val timeline = c.currentTimeline
            val current = c.currentMediaItemIndex.coerceIn(0, count - 1)
            val list = mutableListOf(current)
            var idx = current
            while (list.size < count) {
                val next = timeline.getNextWindowIndex(idx, Player.REPEAT_MODE_OFF, true)
                if (next == C.INDEX_UNSET || next in list) break
                list.add(next)
                idx = next
            }
            list
        } else {
            (0 until count).toList()
        }

        return orderedIndices.map { i ->
            val item = c.getMediaItemAt(i)
            val md = item.mediaMetadata
            ResolvedTrack(
                track = SearchTrack(
                    id = item.mediaId.toLongOrNull() ?: 0L,
                    title = md.title?.toString().orEmpty(),
                    artist = md.artist?.toString(),
                    album = md.albumTitle?.toString(),
                ),
                streamUrl = "",
                artworkUrl = md.artworkUri?.toString(),
            )
        }
    }

    val currentPosition: Long
        get() = controller?.currentPosition ?: 0L

    val duration: Long
        get() = controller?.duration?.coerceAtLeast(0L) ?: 0L

    val shuffleEnabled: Boolean
        get() = controller?.shuffleModeEnabled == true

    val repeatMode: Int
        get() = controller?.repeatMode ?: Player.REPEAT_MODE_OFF

    init {
        val sessionToken = SessionToken(
            appContext,
            ComponentName(appContext, JamarrPlaybackService::class.java),
        )
        controllerFuture = MediaController.Builder(appContext, sessionToken).buildAsync()
        controllerFuture.addListener(
            {
                controller = runCatching { controllerFuture.get() }.getOrNull()
            },
            mainExecutor,
        )
    }

    suspend fun play(track: SearchTrack, streamUrl: String, artworkUrl: String?) {
        playQueue(
            queue = listOf(ResolvedTrack(track, streamUrl, artworkUrl)),
            startIndex = 0,
        )
    }

    suspend fun playQueue(queue: List<ResolvedTrack>, startIndex: Int) {
        if (queue.isEmpty()) return

        val mediaItems = queue.map { it.toMediaItem() }
        controller().run {
            setMediaItems(mediaItems, startIndex.coerceIn(mediaItems.indices), 0L)
            prepare()
            play()
        }
    }

    private fun ResolvedTrack.toMediaItem(): MediaItem {
        val searchTrack = track
        val metadata = MediaMetadata.Builder()
            .setTitle(searchTrack.title)
            .setArtist(searchTrack.artist)
            .setAlbumTitle(searchTrack.album)
            .setArtworkUri(artworkUrl?.let(Uri::parse))
            .build()

        return MediaItem.Builder()
            .setUri(JamarrPlaybackService.trackUri(searchTrack.id))
            .setMediaId(searchTrack.id.toString())
            .setMediaMetadata(metadata)
            .build()
    }

    fun togglePlayPause() {
        val activeController = controller ?: return
        if (activeController.isPlaying) {
            activeController.pause()
        } else {
            activeController.play()
        }
    }

    fun stop() {
        controller?.run {
            stop()
            clearMediaItems()
        }
    }

    fun seekBackward() {
        controller?.run {
            seekTo((currentPosition - 10_000L).coerceAtLeast(0L))
        }
    }

    fun seekForward() {
        controller?.run {
            seekTo(currentPosition + 30_000L)
        }
    }

    fun previous() {
        controller?.seekToPreviousMediaItem()
    }

    fun next() {
        controller?.seekToNextMediaItem()
    }

    fun seekTo(positionMs: Long) {
        controller?.seekTo(positionMs.coerceAtLeast(0L))
    }

    fun toggleShuffle() {
        controller?.let { it.shuffleModeEnabled = !it.shuffleModeEnabled }
    }

    fun cycleRepeatMode() {
        controller?.let {
            it.repeatMode = when (it.repeatMode) {
                Player.REPEAT_MODE_OFF -> Player.REPEAT_MODE_ALL
                Player.REPEAT_MODE_ALL -> Player.REPEAT_MODE_ONE
                else -> Player.REPEAT_MODE_OFF
            }
        }
    }

    fun playQueueItem(index: Int) {
        controller?.seekTo(index, 0L)
    }

    fun release() {
        controller?.release()
        controller = null
    }

    private suspend fun controller(): MediaController {
        controller?.let { return it }

        return suspendCancellableCoroutine { continuation ->
            controllerFuture.addListener(
                {
                    runCatching { controllerFuture.get() }
                        .onSuccess {
                            controller = it
                            if (continuation.isActive) {
                                continuation.resume(it)
                            }
                        }
                        .onFailure {
                            if (continuation.isActive) {
                                continuation.resumeWithException(it)
                            }
                        }
                },
                mainExecutor,
            )
        }
    }
}
