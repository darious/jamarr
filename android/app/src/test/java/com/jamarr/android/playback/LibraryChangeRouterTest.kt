package com.jamarr.android.playback

import com.jamarr.android.data.LibraryChange
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LibraryChangeRouterTest {
    @Test
    fun `a favourite change touches only its own folder`() {
        val a = LibraryChangeRouter.affected(LibraryChange.FavouriteReleases)
        assertEquals(setOf("favourite-releases"), a.cacheKeys)
        assertEquals(setOf(BrowseTree.ID_FAV_RELEASES), a.nodeIds)
        assertFalse(BrowseTree.ID_CHARTS in LibraryChangeRouter.affected(LibraryChange.FavouriteArtists).nodeIds)
    }

    @Test
    fun `a playlist change names the list and the playlist`() {
        val a = LibraryChangeRouter.affected(LibraryChange.Playlist(7))
        assertEquals(setOf("playlists", "playlist:7"), a.cacheKeys)
        assertEquals(setOf(BrowseTree.ID_PLAYLISTS, BrowseTree.playlistId(7)), a.nodeIds)
        assertEquals(setOf("playlists"), LibraryChangeRouter.affected(LibraryChange.Playlist(null)).cacheKeys)
    }

    @Test
    fun `history drops the shared home payload but does not re-notify Recently Added`() {
        val a = LibraryChangeRouter.affected(LibraryChange.History)
        assertTrue("home" in a.cacheKeys)
        assertTrue(BrowseTree.ID_RECENT_TRACKS in a.nodeIds)
        assertFalse(BrowseTree.ID_ADDED in a.nodeIds)
    }

    @Test
    fun `a burst collapses to one notification per folder`() {
        val burst = listOf(LibraryChange.History, LibraryChange.FavouriteReleases, LibraryChange.History)
        val a = LibraryChangeRouter.affected(burst)
        assertEquals(
            LibraryChangeRouter.affected(LibraryChange.History).nodeIds + BrowseTree.ID_FAV_RELEASES,
            a.nodeIds,
        )
    }
}
