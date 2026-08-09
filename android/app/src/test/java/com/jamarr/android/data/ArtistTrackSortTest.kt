package com.jamarr.android.data

import org.junit.Assert.assertEquals
import org.junit.Test

class ArtistTrackSortTest {
    @Test
    fun releasesAreNewestFirst() {
        val sorted = listOf(
            release("CRASH", "2022-03-18"),
            release("Music, Fashion, Film", "2026-07-24"),
            release("how i'm feeling now", "2020-05-15"),
            release("BRAT", "2024-06-07"),
        ).sortedReleasesDesc()

        assertEquals(
            listOf("Music, Fashion, Film", "BRAT", "CRASH", "how i'm feeling now"),
            sorted.map { it.album },
        )
    }

    @Test
    fun undatedReleasesSortLast() {
        val sorted = listOf(
            release("No Date", null),
            release("Blank Date", ""),
            release("Dated", "2001-01-01"),
        ).sortedReleasesDesc()

        assertEquals(listOf("Dated", "No Date", "Blank Date"), sorted.map { it.album })
    }

    /** Only a handful of rows carry `year` without a full `release_date`. */
    @Test
    fun yearIsUsedWhenReleaseDateIsAbsent() {
        val sorted = listOf(
            release("Older", releaseDate = null, year = "1999-01-01"),
            release("Newer", releaseDate = null, year = "2010-01-01"),
        ).sortedReleasesDesc()

        assertEquals(listOf("Newer", "Older"), sorted.map { it.album })
    }

    @Test
    fun equalDatesKeepTheirOriginalOrder() {
        val sorted = listOf(
            release("First", "2020-01-01"),
            release("Second", "2020-01-01"),
            release("Third", "2020-01-01"),
        ).sortedReleasesDesc()

        assertEquals(listOf("First", "Second", "Third"), sorted.map { it.album })
    }

    private fun release(album: String, releaseDate: String?, year: String? = releaseDate) =
        AlbumDetail(album = album, releaseDate = releaseDate, year = year)
}
