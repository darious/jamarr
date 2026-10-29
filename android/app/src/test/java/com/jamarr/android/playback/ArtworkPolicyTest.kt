package com.jamarr.android.playback

import org.junit.Assert.assertEquals
import org.junit.Test

class ArtworkPolicyTest {

    @Test
    fun `an https server hands the car its own URL`() {
        assertEquals(ArtworkPolicy.Mode.URI, ArtworkPolicy.modeFor("https://jamarr.example.com"))
        assertEquals(ArtworkPolicy.Mode.URI, ArtworkPolicy.modeFor("  HTTPS://jamarr.example.com "))
    }

    @Test
    fun `a cleartext server goes through the content provider`() {
        // The host process fetches artworkUri itself and does not permit
        // cleartext, so an http:// icon URI would silently fail to load there.
        assertEquals(ArtworkPolicy.Mode.CONTENT, ArtworkPolicy.modeFor("http://192.168.1.107:8111"))
        assertEquals(ArtworkPolicy.Mode.CONTENT, ArtworkPolicy.modeFor(""))
    }

    @Test
    fun `downloaded art is always served locally`() {
        assertEquals(ArtworkPolicy.Mode.CONTENT, ArtworkPolicy.browseMode("https://jamarr.example.com", downloaded = true))
        assertEquals(ArtworkPolicy.Mode.URI, ArtworkPolicy.browseMode("https://jamarr.example.com", downloaded = false))
    }
}
