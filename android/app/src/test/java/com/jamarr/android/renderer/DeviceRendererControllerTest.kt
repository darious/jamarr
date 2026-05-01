package com.jamarr.android.renderer

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test

class DeviceRendererControllerTest {
    @Test
    fun fakeControllerTracksSelectionQueueProgressAndVolume() = runTest {
        val controller = FakeDeviceRendererController("cast")
        val track = QueuedTrack(
            id = 42,
            title = "Song",
            artist = "Artist",
            album = "Album",
            mime = "audio/flac",
            durationSeconds = 120.0,
            streamUrl = "https://jamarr.example/api/stream/42?token=t",
            artUrl = "https://jamarr.example/art/file/a",
        )

        controller.start()
        controller.selectRenderer("cast:kitchen")
        controller.playQueue(listOf(track), 0)
        controller.seek(30.0)
        controller.setVolumePercent(35)

        val state = controller.state.value
        assertEquals(listOf("start", "select:cast:kitchen", "playQueue:0:1", "seek:30.0", "volume:35"), controller.calls)
        assertEquals("cast:kitchen", state.activeRendererId)
        assertEquals(0, state.currentIndex)
        assertEquals(30.0, state.positionSeconds, 0.001)
        assertEquals(35, state.volumePercent)
        assertEquals(true, state.isPlaying)
    }

    private class FakeDeviceRendererController(
        override val kind: String,
    ) : DeviceRendererController {
        val calls = mutableListOf<String>()
        private val rendererState = MutableStateFlow(
            listOf(DeviceRendererInfo(rendererId = "$kind:kitchen", kind = kind, name = "Kitchen")),
        )
        override val renderers: StateFlow<List<DeviceRendererInfo>> = rendererState

        private val playbackState = MutableStateFlow(DeviceRendererPlaybackState())
        override val state: StateFlow<DeviceRendererPlaybackState> = playbackState

        override fun start() {
            calls += "start"
        }

        override fun stop() {
            calls += "stop"
        }

        override fun search() {
            calls += "search"
        }

        override fun selectRenderer(rendererId: String) {
            calls += "select:$rendererId"
            playbackState.value = playbackState.value.copy(activeRendererId = rendererId)
        }

        override suspend fun playQueue(tracks: List<QueuedTrack>, startIndex: Int) {
            calls += "playQueue:$startIndex:${tracks.size}"
            playbackState.value = playbackState.value.copy(
                queue = tracks,
                currentIndex = startIndex,
                durationSeconds = tracks[startIndex].durationSeconds,
                isPlaying = true,
                transportState = "PLAYING",
            )
        }

        override suspend fun pause() {
            calls += "pause"
            playbackState.value = playbackState.value.copy(isPlaying = false)
        }

        override suspend fun resume() {
            calls += "resume"
            playbackState.value = playbackState.value.copy(isPlaying = true)
        }

        override suspend fun stopPlayback() {
            calls += "stopPlayback"
            playbackState.value = DeviceRendererPlaybackState()
        }

        override suspend fun seek(seconds: Double) {
            calls += "seek:$seconds"
            playbackState.value = playbackState.value.copy(positionSeconds = seconds)
        }

        override suspend fun setVolumePercent(percent: Int) {
            calls += "volume:$percent"
            playbackState.value = playbackState.value.copy(volumePercent = percent.coerceIn(0, 100))
        }

        override suspend fun next() {
            calls += "next"
        }

        override suspend fun previous() {
            calls += "previous"
        }

        override suspend fun jumpTo(index: Int) {
            calls += "jumpTo:$index"
            playbackState.value = playbackState.value.copy(currentIndex = index)
        }
    }
}
