package com.jamarr.android.cast

import com.jamarr.android.renderer.QueuedTrack
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CastQueueReconcilerTest {

    private val server = "http://192.0.2.10:8111"

    private fun track(id: Long, title: String = "Track $id") = QueuedTrack(
        id = id,
        title = title,
        artist = "Artist",
        album = "Album",
        mime = "audio/flac",
        durationSeconds = 200.0,
        streamUrl = "$server/api/stream/$id?token=t$id",
        artUrl = "$server/art/file/a$id",
    )

    /** An item exactly as this app would have loaded it. */
    private fun ourItem(itemId: Int, t: QueuedTrack, withMetadata: Boolean = true) = ReceiverItem(
        itemId = itemId,
        contentId = t.streamUrl,
        contentType = "audio/flac",
        title = t.title.takeIf { withMetadata },
        artist = t.artist.takeIf { withMetadata },
        album = t.album.takeIf { withMetadata },
        durationSeconds = 200.0,
        custom = CastIdentity.customData(t, server),
    )

    private fun snapshot(items: List<ReceiverItem>, currentItemId: Int?, itemIds: List<Int> = items.map { it.itemId }) =
        ReceiverSnapshot(
            itemIds = itemIds,
            items = items.associateBy { it.itemId },
            currentItemId = currentItemId,
            currentMedia = items.firstOrNull { it.itemId == currentItemId },
        )

    private val tracks = listOf(track(1), track(2), track(3))
    private val items = tracks.mapIndexed { i, t -> ourItem(10 + i, t) }

    @Test
    fun customDataCarriesStableIdentity() {
        val data = CastIdentity.customData(track(7), server)

        assertEquals(7L, data[CastIdentity.TRACK_ID])
        assertEquals(CastIdentity.SOURCE_ANDROID, data[CastIdentity.SOURCE])
        assertEquals("$server/api/stream/7", data[CastIdentity.CONTENT_PATH])
        assertEquals(server, data[CastIdentity.SERVER])
        assertEquals("audio/flac", data[CastIdentity.MIME])
        assertEquals(200.0, data[CastIdentity.DURATION])
    }

    @Test
    fun trackIdNeedsMatchingContent() {
        val item = items[0]
        assertEquals(1L, CastIdentity.trackId(item))
        // Same media under a fresh token.
        assertEquals(1L, CastIdentity.trackId(item.copy(contentId = "$server/api/stream/1?token=new")))
        // customData carried over onto other media is not believed.
        assertNull(CastIdentity.trackId(item.copy(contentId = "https://video.example/x.mp4")))
        assertNull(CastIdentity.trackId(item.copy(custom = emptyMap())))
        // JSON numbers may arrive as Int.
        assertEquals(1L, CastIdentity.trackId(item.copy(custom = item.custom + (CastIdentity.TRACK_ID to 1))))
    }

    @Test
    fun serverOriginIsSchemeAndAuthority() {
        assertEquals("http://192.0.2.10:8111", CastIdentity.serverOrigin("HTTP://192.0.2.10:8111/api/x?y=1"))
        assertEquals("https://jamarr.example", CastIdentity.serverOrigin("https://jamarr.example"))
        assertNull(CastIdentity.serverOrigin("not a url"))
        assertNull(CastIdentity.serverOrigin(null))
    }

    @Test
    fun reconstructsQueueAndCurrentItemAfterRestart() {
        val rebuilt = CastQueueReconciler.reconstruct(snapshot(items, currentItemId = 11), serverUrl = server)

        assertEquals(ReceiverOwnership.JAMARR, rebuilt.ownership)
        assertTrue(rebuilt.complete)
        assertEquals(listOf(1L, 2L, 3L), rebuilt.trackIds)
        assertEquals(1, rebuilt.currentIndex)
        assertEquals("Track 2", rebuilt.tracks[1].title)
        assertEquals(tracks[1].streamUrl, rebuilt.tracks[1].streamUrl)
        assertEquals(tracks[1].artUrl, rebuilt.tracks[1].artUrl)
    }

    @Test
    fun restartAdoptsReceiverQueueIntoEmptyLocalState() {
        val rebuilt = CastQueueReconciler.reconstruct(snapshot(items, currentItemId = 12), serverUrl = server)

        val sync = CastQueueReconciler.sync(rebuilt, emptyList(), -1, expectation = null, nowMs = 0)

        sync as QueueSync.Adopt
        assertTrue(sync.queueChanged)
        assertEquals(2, sync.currentIndex)
        assertEquals(listOf(1L, 2L, 3L), sync.tracks.map { it.id })
    }

    @Test
    fun itemsWithoutMetadataAreLookedUpAndFilledIn() {
        val bare = tracks.mapIndexed { i, t -> ourItem(10 + i, t, withMetadata = false) }
        val rebuilt = CastQueueReconciler.reconstruct(snapshot(bare, currentItemId = 10), serverUrl = server)

        assertEquals(listOf(1L, 2L, 3L), rebuilt.needsMetadata)
        assertEquals("", rebuilt.tracks[0].title)

        val resolved = mapOf(2L to track(2, title = "From Server"))
        val filled = CastQueueReconciler.reconstruct(
            snapshot(bare, currentItemId = 10),
            serverUrl = server,
            resolved = resolved,
        )
        assertEquals(listOf(1L, 3L), filled.needsMetadata)
        assertEquals("From Server", filled.tracks[1].title)
        // The receiver's URL is kept: it is what the receiver plays.
        assertEquals(tracks[1].streamUrl, filled.tracks[1].streamUrl)
    }

    @Test
    fun partiallyFetchedQueueIsIncomplete() {
        val partial = snapshot(items.take(2), currentItemId = 10, itemIds = listOf(10, 11, 12))
        val rebuilt = CastQueueReconciler.reconstruct(partial, serverUrl = server)

        assertEquals(listOf(12), rebuilt.missingItemIds)
        assertFalse(rebuilt.complete)
        // Nothing local to compare against: wait for the rest.
        assertEquals(QueueSync.Keep, CastQueueReconciler.sync(rebuilt, emptyList(), -1, null, 0))
    }

    @Test
    fun partialWindowStillFollowsTheCurrentItemOfTheSameQueue() {
        // A long queue: only a window of items is known, but it is ours.
        val window = snapshot(listOf(items[2]), currentItemId = 12, itemIds = listOf(10, 11, 12))
        val rebuilt = CastQueueReconciler.reconstruct(window, tracks, server)

        val sync = CastQueueReconciler.sync(rebuilt, tracks, localIndex = 1, expectation = null, nowMs = 0)

        sync as QueueSync.Adopt
        assertFalse(sync.queueChanged)
        assertEquals(2, sync.currentIndex)
        assertEquals(tracks, sync.tracks)
    }

    @Test
    fun receiverAdvanceMovesLocalIndexOnly() {
        val rebuilt = CastQueueReconciler.reconstruct(snapshot(items, currentItemId = 11), tracks, server)

        val sync = CastQueueReconciler.sync(rebuilt, tracks, localIndex = 0, expectation = null, nowMs = 0)

        sync as QueueSync.Adopt
        assertFalse(sync.queueChanged)
        assertEquals(1, sync.currentIndex)
        assertEquals(QueueSync.Keep, CastQueueReconciler.sync(rebuilt, tracks, 1, null, 0))
    }

    @Test
    fun anotherControllersQueueEditIsAdopted() {
        // Another phone removed track 2 and appended track 4.
        val four = track(4)
        val edited = listOf(items[0], items[2], ourItem(13, four))
        val rebuilt = CastQueueReconciler.reconstruct(snapshot(edited, currentItemId = 13), tracks, server)

        val sync = CastQueueReconciler.sync(rebuilt, tracks, localIndex = 0, expectation = null, nowMs = 0)

        sync as QueueSync.Adopt
        assertTrue(sync.queueChanged)
        assertEquals(listOf(1L, 3L, 4L), sync.tracks.map { it.id })
        assertEquals(2, sync.currentIndex)
    }

    @Test
    fun ownLoadInFlightIgnoresStatusesOfTheOldQueue() {
        val old = CastQueueReconciler.reconstruct(snapshot(items, currentItemId = 10), serverUrl = server)
        val newQueue = listOf(track(7), track(8))
        val expectation = LoadExpectation(listOf(7L, 8L), currentTrackId = 8L, untilMs = 1_000)

        assertEquals(QueueSync.Keep, CastQueueReconciler.sync(old, newQueue, 1, expectation, nowMs = 500))

        val landed = CastQueueReconciler.reconstruct(
            snapshot(listOf(ourItem(20, newQueue[0]), ourItem(21, newQueue[1])), currentItemId = 21),
            newQueue,
            server,
        )
        val sync = CastQueueReconciler.sync(landed, newQueue, 1, expectation, nowMs = 600)
        sync as QueueSync.Adopt
        assertTrue(sync.expectationMet)
        assertFalse(sync.queueChanged)
        assertEquals(1, sync.currentIndex)

        // Expired: the receiver's view counts again (the load did not land).
        val expired = CastQueueReconciler.sync(old, newQueue, 1, expectation, nowMs = 2_000)
        expired as QueueSync.Adopt
        assertTrue(expired.queueChanged)
    }

    @Test
    fun otherAppsMediaIsNotOurs() {
        val video = ReceiverItem(itemId = 5, contentId = "https://video.example/clip.mp4", title = "Clip")
        val rebuilt = CastQueueReconciler.reconstruct(snapshot(listOf(video), currentItemId = 5), tracks, server)

        assertEquals(ReceiverOwnership.FOREIGN, rebuilt.ownership)
        assertEquals(
            QueueSync.NotOurs(ReceiverOwnership.FOREIGN),
            CastQueueReconciler.sync(rebuilt, tracks, 0, null, 0),
        )
    }

    @Test
    fun serverCastMediaBelongsToTheServer() {
        val t = track(9)
        val serverItem = ourItem(30, t).copy(
            custom = mapOf(
                CastIdentity.TRACK_ID to 9L,
                CastIdentity.SOURCE to CastIdentity.SOURCE_SERVER,
                CastIdentity.CONTENT_PATH to CastIdentity.contentPath(t.streamUrl),
            ),
        )
        val rebuilt = CastQueueReconciler.reconstruct(snapshot(listOf(serverItem), 30), emptyList(), server)

        assertEquals(ReceiverOwnership.JAMARR_SERVER, rebuilt.ownership)
        assertEquals(
            QueueSync.NotOurs(ReceiverOwnership.JAMARR_SERVER),
            CastQueueReconciler.sync(rebuilt, emptyList(), -1, null, 0),
        )
    }

    @Test
    fun anotherJamarrServersQueueIsNotOurs() {
        val rebuilt = CastQueueReconciler.reconstruct(
            snapshot(items, currentItemId = 10),
            serverUrl = "https://other-jamarr.example",
        )
        assertEquals(ReceiverOwnership.FOREIGN, rebuilt.ownership)
    }

    @Test
    fun noMediaMeansNoChange() {
        val rebuilt = CastQueueReconciler.reconstruct(ReceiverSnapshot(), tracks, server)
        assertEquals(ReceiverOwnership.NONE, rebuilt.ownership)
        assertEquals(QueueSync.Keep, CastQueueReconciler.sync(rebuilt, tracks, 0, null, 0))
    }

    @Test
    fun singleLoadWithoutQueueIsReconstructed() {
        // A plain LOAD (e.g. from another sender) reports media, no queue ids.
        val only = ourItem(40, track(5))
        val rebuilt = CastQueueReconciler.reconstruct(
            ReceiverSnapshot(currentItemId = 40, currentMedia = only),
            serverUrl = server,
        )
        assertTrue(rebuilt.complete)
        assertEquals(listOf(5L), rebuilt.trackIds)
        assertEquals(0, rebuilt.currentIndex)
    }

    @Test
    fun playOnTheSameReceiverQueueJumpsInsteadOfReloading() {
        val rebuilt = CastQueueReconciler.reconstruct(snapshot(items, currentItemId = 10), tracks, server)

        assertEquals(PlayPlan.JumpTo(12), CastQueueReconciler.planPlay(listOf(1L, 2L, 3L), 2, rebuilt))
        assertEquals(
            PlayPlan.Load(ReceiverOwnership.JAMARR),
            CastQueueReconciler.planPlay(listOf(1L, 2L), 0, rebuilt),
        )
    }

    @Test
    fun playOverAnotherAppsMediaIsAnExplicitReplace() {
        val video = ReceiverItem(itemId = 5, contentId = "https://video.example/clip.mp4")
        val rebuilt = CastQueueReconciler.reconstruct(snapshot(listOf(video), 5), tracks, server)

        assertEquals(
            PlayPlan.Load(ReceiverOwnership.FOREIGN),
            CastQueueReconciler.planPlay(listOf(1L, 2L, 3L), 0, rebuilt),
        )
        assertEquals(
            PlayPlan.Load(ReceiverOwnership.NONE),
            CastQueueReconciler.planPlay(listOf(1L), 0, ReceiverQueue(ReceiverOwnership.NONE)),
        )
    }
}
