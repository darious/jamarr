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
