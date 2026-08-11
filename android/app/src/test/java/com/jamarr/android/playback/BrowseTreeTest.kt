package com.jamarr.android.playback

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class BrowseTreeTest {

    @Test
    fun `track ids round-trip through their parent`() {
        val id = BrowseTree.trackId(42L, BrowseTree.albumId("mbid-1"))
        assertEquals("track:42|p:album:mbid-1", id)
        assertEquals(42L, BrowseTree.trackIdOf(id))
        assertEquals("album:mbid-1", BrowseTree.parentOf(id))
    }

    @Test
    fun `a parentless track id is still playable`() {
        val id = BrowseTree.trackId(7L, null)
        assertEquals("track:7", id)
        assertEquals(7L, BrowseTree.trackIdOf(id))
        assertNull(BrowseTree.parentOf(id))
    }

    @Test
    fun `non-track ids have no track id`() {
        assertNull(BrowseTree.trackIdOf("album:x"))
        assertNull(BrowseTree.trackIdOf(BrowseTree.ID_ROOT))
        // Malformed but well-prefixed: must not be read as track 0.
        assertNull(BrowseTree.trackIdOf("track:not-a-number"))
    }

    @Test
    fun `every static node resolves, not just root's children`() {
        // onGetItem used to look only at root's children, so a browser
        // restoring a deeper screen got ERROR_BAD_VALUE.
        for (id in BrowseTree.staticNodeIds()) {
            assertNotNull("node $id should resolve", BrowseTree.node(id))
        }
        assertNotNull(BrowseTree.node(BrowseTree.ID_FAV_ARTISTS))
        assertNotNull(BrowseTree.node(BrowseTree.ID_RECENT_TRACKS))
        assertNotNull(BrowseTree.node(BrowseTree.ID_HISTORY_ALBUMS))
        assertNull(BrowseTree.node("node:does-not-exist"))
    }

    @Test
    fun `root lists the six top-level folders in order`() {
        assertEquals(
            listOf(
                BrowseTree.ID_FAVOURITES,
                BrowseTree.ID_PLAYLISTS,
                BrowseTree.ID_RECENT,
                BrowseTree.ID_CHARTS,
                BrowseTree.ID_HISTORY,
                BrowseTree.ID_ADDED,
            ),
            BrowseTree.node(BrowseTree.ID_ROOT)?.children,
        )
    }

    @Test
    fun `play-all ids carry the folder they play`() {
        val id = BrowseTree.playAllId(BrowseTree.playlistId(3L))
        assertEquals("playall:playlist:3", id)
        assertEquals("playlist:3", BrowseTree.playAllTarget(id))
        assertNull(BrowseTree.playAllTarget("playlist:3"))
        assertNull(BrowseTree.playAllTarget("playall:"))
    }

    @Test
    fun `playlist ids parse only when numeric`() {
        assertEquals(12L, BrowseTree.playlistIdOf("playlist:12"))
        assertNull(BrowseTree.playlistIdOf("playlist:abc"))
        assertNull(BrowseTree.playlistIdOf("album:12"))
    }

    @Test
    fun `paging returns one window per page`() {
        val items = (1..10).toList()
        assertEquals(listOf(1, 2, 3), BrowseTree.page(items, page = 0, pageSize = 3))
        assertEquals(listOf(4, 5, 6), BrowseTree.page(items, page = 1, pageSize = 3))
        assertEquals(listOf(10), BrowseTree.page(items, page = 3, pageSize = 3))
    }

    @Test
    fun `a page past the end is empty, not the whole list`() {
        // The old provider ignored the window and re-sent everything, so a
        // browser paging past the end got duplicates instead of a stop signal.
        assertEquals(emptyList<Int>(), BrowseTree.page((1..10).toList(), page = 9, pageSize = 3))
    }

    @Test
    fun `an unpaged request keeps the whole list`() {
        // Media3 passes (0, MAX_VALUE) when the browser sends no page options.
        val items = (1..10).toList()
        assertEquals(items, BrowseTree.page(items, page = 0, pageSize = Int.MAX_VALUE))
        assertEquals(items, BrowseTree.page(items, page = 0, pageSize = 0))
        assertEquals(items, BrowseTree.page(items, page = -1, pageSize = 5))
    }

    @Test
    fun `a huge page number does not overflow into a valid window`() {
        // page * pageSize wraps negative in Int arithmetic and would slice
        // from the start of the list.
        assertEquals(
            emptyList<Int>(),
            BrowseTree.page((1..10).toList(), page = Int.MAX_VALUE, pageSize = 1000),
        )
    }

    @Test
    fun `releases are grouped by type`() {
        assertEquals(BrowseTree.GROUP_ALBUMS, BrowseTree.albumGroupTitle(null, "album"))
        assertEquals(BrowseTree.GROUP_ALBUMS, BrowseTree.albumGroupTitle(null, null))
        assertEquals(BrowseTree.GROUP_EPS, BrowseTree.albumGroupTitle(null, "EP"))
        assertEquals(BrowseTree.GROUP_LIVE, BrowseTree.albumGroupTitle(null, " live "))
        assertEquals(BrowseTree.GROUP_COMPILATIONS, BrowseTree.albumGroupTitle(null, "compilation"))
        assertEquals(BrowseTree.GROUP_SINGLE_RELEASES, BrowseTree.albumGroupTitle(null, "single"))
    }

    @Test
    fun `appears-on wins over the release type`() {
        assertEquals(BrowseTree.GROUP_APPEARS_ON, BrowseTree.albumGroupTitle("appears_on", "album"))
        assertEquals(BrowseTree.GROUP_APPEARS_ON, BrowseTree.albumGroupTitle("APPEARS_ON", "ep"))
    }

    @Test
    fun `appears-on is not in the album section order`() {
        // It is appended after the synthetic Singles / Most Scrobbled folders.
        assertEquals(false, BrowseTree.ALBUM_GROUP_ORDER.contains(BrowseTree.GROUP_APPEARS_ON))
    }
}
