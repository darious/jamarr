package com.jamarr.android.playback

import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test

class TtlCacheTest {

    @Test
    fun `a repeated read hits the cache`() = runTest {
        val calls = AtomicInteger()
        val cache = TtlCache(ttlMs = 1_000L, now = { 0L })

        assertEquals("v", cache.get("k") { calls.incrementAndGet(); "v" })
        assertEquals("v", cache.get("k") { calls.incrementAndGet(); "v" })

        assertEquals(1, calls.get())
    }

    @Test
    fun `an expired entry is reloaded`() = runTest {
        val calls = AtomicInteger()
        var clock = 0L
        val cache = TtlCache(ttlMs = 100L, now = { clock })

        cache.get("k") { calls.incrementAndGet() }
        clock = 101L
        cache.get("k") { calls.incrementAndGet() }

        assertEquals(2, calls.get())
    }

    @Test
    fun `separate keys do not share a value`() = runTest {
        val cache = TtlCache(ttlMs = 1_000L, now = { 0L })
        assertEquals("a", cache.get("one") { "a" })
        assertEquals("b", cache.get("two") { "b" })
        assertEquals("a", cache.get("one") { "unused" })
    }

    @Test
    fun `parallel readers of one key share a single load`() = runTest {
        // Building a browse screen fans out into sibling nodes that want the
        // same /api/home payload; without single-flighting they all fetch it.
        val calls = AtomicInteger()
        val cache = TtlCache(ttlMs = 1_000L, now = { 0L })

        val results = (1..8).map {
            async { cache.get("home") { calls.incrementAndGet(); "payload" } }
        }.awaitAll()

        assertEquals(List(8) { "payload" }, results)
        assertEquals(1, calls.get())
    }

    @Test
    fun `invalidate drops one key`() = runTest {
        val calls = AtomicInteger()
        val cache = TtlCache(ttlMs = 1_000L, now = { 0L })

        cache.get("k") { calls.incrementAndGet() }
        cache.invalidate("k")
        cache.get("k") { calls.incrementAndGet() }

        assertEquals(2, calls.get())
    }

    @Test
    fun `invalidateAll clears the tree after a sign-in`() = runTest {
        val calls = AtomicInteger()
        val cache = TtlCache(ttlMs = 10_000L, now = { 0L })

        cache.get("home") { calls.incrementAndGet() }
        cache.get("playlists") { calls.incrementAndGet() }
        cache.invalidateAll()
        cache.get("home") { calls.incrementAndGet() }
        cache.get("playlists") { calls.incrementAndGet() }

        assertEquals(4, calls.get())
    }
}
