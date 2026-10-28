package com.jamarr.android.renderer

import kotlinx.coroutines.flow.StateFlow

data class DeviceRendererInfo(
    val rendererId: String,
    val kind: String,
    val name: String,
    val manufacturer: String? = null,
    val modelName: String? = null,
    val ip: String? = null,
    val available: Boolean = true,
    val status: String? = null,
) {
    val udn: String get() = rendererId
}

data class QueuedTrack(
    val id: Long,
    val title: String,
    val artist: String,
    val album: String,
    val mime: String,
    val durationSeconds: Double,
    val streamUrl: String,
    val artUrl: String?,
)

data class DeviceRendererPlaybackState(
    val activeRendererId: String? = null,
    val queue: List<QueuedTrack> = emptyList(),
    val currentIndex: Int = -1,
    val positionSeconds: Double = 0.0,
    val durationSeconds: Double = 0.0,
    val isPlaying: Boolean = false,
    val transportState: String = "STOPPED",
    val volumePercent: Int = 0,
    val status: String? = null,
)

interface DeviceRendererController {
    val kind: String

    /**
     * The controller mints each track's stream URL itself when it loads it,
     * so [playQueue] can take tracks with a blank [QueuedTrack.streamUrl].
     */
    val resolvesStreamUrls: Boolean get() = false
    val renderers: StateFlow<List<DeviceRendererInfo>>
    val state: StateFlow<DeviceRendererPlaybackState>

    fun start()
    fun stop()
    fun search()
    fun selectRenderer(rendererId: String)

    suspend fun playQueue(tracks: List<QueuedTrack>, startIndex: Int)
    suspend fun pause()
    suspend fun resume()
    suspend fun stopPlayback()
    suspend fun seek(seconds: Double)
    suspend fun setVolumePercent(percent: Int)
    suspend fun next()
    suspend fun previous()
    suspend fun jumpTo(index: Int)
}

/**
 * Stream URLs for a queue headed to [controller]: none when it mints its own
 * at load time (each mint is a server round trip, so a long album would
 * otherwise wait on one per track before anything plays), else one per track.
 */
suspend fun <T> deviceQueueStreamUrls(
    tracks: List<T>,
    controller: DeviceRendererController?,
    mint: suspend (T) -> String,
): List<String> =
    if (controller?.resolvesStreamUrls == true) List(tracks.size) { "" } else tracks.map { mint(it) }
