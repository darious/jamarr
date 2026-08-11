package com.jamarr.android.playback

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ArtworkPolicyTest {

    @Test
    fun `an https server hands the car a URI`() {
        assertEquals(ArtworkPolicy.Mode.URI, ArtworkPolicy.modeFor("https://jamarr.example.com"))
        assertEquals(ArtworkPolicy.Mode.URI, ArtworkPolicy.modeFor("  HTTPS://jamarr.example.com "))
    }

    @Test
    fun `a cleartext server keeps sending bytes`() {
        // The host process fetches artworkUri itself and does not permit
        // cleartext, so an http:// icon URI would silently fail to load there.
        assertEquals(ArtworkPolicy.Mode.BYTES, ArtworkPolicy.modeFor("http://192.168.1.107:8111"))
        assertEquals(ArtworkPolicy.Mode.BYTES, ArtworkPolicy.modeFor(""))
    }

    @Test
    fun `queue items never carry bytes`() {
        // Nothing renders them, and fetching art to build a queue only delays
        // the first note.
        assertFalse(ArtworkPolicy.embedsBytes("http://lan:8111", forBrowse = false))
        assertFalse(ArtworkPolicy.embedsBytes("https://jamarr.example.com", forBrowse = false))
    }

    @Test
    fun `browse items carry bytes only when the URI would not load`() {
        assertTrue(ArtworkPolicy.embedsBytes("http://lan:8111", forBrowse = true))
        assertFalse(ArtworkPolicy.embedsBytes("https://jamarr.example.com", forBrowse = true))
    }
}
