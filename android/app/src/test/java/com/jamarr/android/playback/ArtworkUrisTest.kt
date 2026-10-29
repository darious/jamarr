package com.jamarr.android.playback

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ArtworkUrisTest {
    private val a = "a".repeat(40)
    private val b = "b".repeat(40)

    @Test
    fun `only a bare hash is an artwork request`() {
        assertEquals(ArtworkUris.Request.Art(a), ArtworkUris.parse(listOf("art", a)))
        assertEquals(ArtworkUris.Request.Art(a), ArtworkUris.parse(listOf("art", a.uppercase())))
        assertNull(ArtworkUris.parse(listOf("art", "..")))
        assertNull(ArtworkUris.parse(listOf("art", "../../data/x")))
        assertNull(ArtworkUris.parse(listOf("art", "http://evil/x.jpg")))
        assertNull(ArtworkUris.parse(listOf("art", a.dropLast(1))))
        assertNull(ArtworkUris.parse(listOf("art", a, "extra")))
        assertNull(ArtworkUris.parse(listOf("files", a)))
        assertNull(ArtworkUris.parse(emptyList()))
    }

    @Test
    fun `a grid takes up to four distinct hashes`() {
        assertEquals(ArtworkUris.Request.Grid(listOf(a, b)), ArtworkUris.parse(listOf("grid", "$a,$b,$a")))
        assertNull(ArtworkUris.parse(listOf("grid", "$a,$b,nope")))
        assertNull(ArtworkUris.parse(listOf("grid", "")))
        val five = (1..5).map { it.toString().repeat(40) }
        assertNull(ArtworkUris.parse(listOf("grid", five.joinToString(","))))
        assertEquals("grid/" + five.take(4).joinToString(","), ArtworkUris.gridPath(five + "junk"))
        assertNull(ArtworkUris.gridPath(listOf("junk")))
    }

    @Test
    fun `paths and cache names are stable`() {
        assertEquals("art/$a", ArtworkUris.artPath(a.uppercase()))
        assertEquals(ArtworkUris.gridCacheName(listOf(a, b)), ArtworkUris.gridCacheName(listOf(a, b)))
        assert(ArtworkUris.gridCacheName(listOf(a, b)) != ArtworkUris.gridCacheName(listOf(b, a)))
    }
}
