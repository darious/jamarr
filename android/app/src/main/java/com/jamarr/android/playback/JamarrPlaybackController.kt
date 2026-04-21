package com.jamarr.android.playback

import android.content.ComponentName
import android.content.Context
import android.net.Uri
import android.os.Handler
import android.os.Looper
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import com.google.common.util.concurrent.ListenableFuture
import com.jamarr.android.data.SearchTrack
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine
import java.util.concurrent.Executor

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
            .setUri(streamUrl)
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
