package com.jamarr.android.cast

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.jamarr.android.renderer.QueuedTrack
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The Cast SDK MediaInfo and org.json round trip that queue reconstruction
 * relies on: real classes, so on a device rather than the JVM.
 */
@RunWith(AndroidJUnit4::class)
class CastMediaItemsInstrumentedTest {

    private val server = "http://192.0.2.10:8111"
    private val track = QueuedTrack(
        id = 4242,
        title = "Song",
        artist = "Artist",
        album = "Album",
        mime = "audio/flac",
        durationSeconds = 187.5,
        streamUrl = "$server/api/stream/4242?token=abc",
        artUrl = "$server/art/file/sha?max_size=600",
    )

    @Test
    fun mediaInfoRoundTripsJamarrIdentity() {
        val media = CastMediaItems.mediaInfo(track, server)

        val item = CastMediaItems.receiverItem(7, media)!!

        assertEquals(7, item.itemId)
        assertEquals(track.streamUrl, item.contentId)
        assertEquals("audio/flac", item.contentType)
        assertEquals("Song", item.title)
        assertEquals("Artist", item.artist)
        assertEquals("Album", item.album)
        assertEquals(track.artUrl, item.artUrl)
        assertEquals(4242L, CastIdentity.trackId(item))
        assertEquals(CastIdentity.SOURCE_ANDROID, CastIdentity.source(item))
        assertEquals(server, item.custom[CastIdentity.SERVER])
    }

    @Test
    fun receiverQueueRebuildsFromSdkItems() {
        val second = track.copy(id = 4243, title = "Next", streamUrl = "$server/api/stream/4243?token=d")
        val items = listOf(track, second).mapIndexed { i, t ->
            CastMediaItems.receiverItem(100 + i, CastMediaItems.mediaInfo(t, server))!!
        }

        val rebuilt = CastQueueReconciler.reconstruct(
            ReceiverSnapshot(
                itemIds = listOf(100, 101),
                items = items.associateBy { it.itemId },
                currentItemId = 101,
            ),
            serverUrl = server,
        )

        assertEquals(ReceiverOwnership.JAMARR, rebuilt.ownership)
        assertEquals(listOf(4242L, 4243L), rebuilt.trackIds)
        assertEquals(1, rebuilt.currentIndex)
        assertEquals(187.5, rebuilt.tracks[0].durationSeconds, 0.0)
    }

    @Test
    fun jsonConversionSkipsNulls() {
        val json = CastMediaItems.toJson(mapOf("a" to 1L, "b" to null, "c" to "x"))
        val back = CastMediaItems.toMap(json)
        assertEquals(mapOf("a" to 1L, "c" to "x"), back.mapValues { (_, v) -> if (v is Int) v.toLong() else v })
    }
}
