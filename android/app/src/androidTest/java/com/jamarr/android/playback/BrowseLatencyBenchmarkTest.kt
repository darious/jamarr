package com.jamarr.android.playback

import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.jamarr.android.auth.TokenHolder
import com.jamarr.android.data.JamarrApiClient
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.test.runTest
import mockwebserver3.Dispatcher
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * First-page cost of the large browse nodes (#321), against a fake server
 * that answers every request after a fixed delay — so the numbers measure
 * how many round trips and how much payload a first page needs, not the
 * emulator's network.
 *
 * Each case logs `BrowseLatency: <node> firstPage=<ms> requests=<n>
 * largestLimit=<n>` and asserts the request budget. The baseline, recorded
 * on the code before the paging work, is in the test's history (git log) and
 * in `docs/clients/android.md`.
 */
@RunWith(AndroidJUnit4::class)
class BrowseLatencyBenchmarkTest {
    private lateinit var server: MockWebServer
    private lateinit var scope: CoroutineScope
    private val requests = ConcurrentHashMap<String, AtomicInteger>()
    private val limits = ConcurrentHashMap<String, Int>()

    @Before
    fun setUp() {
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val path = request.url.encodedPath
                requests.getOrPut(path) { AtomicInteger() }.incrementAndGet()
                request.url.queryParameter("limit")?.toIntOrNull()?.let { l -> limits.merge(path, l, ::maxOf) }
                Thread.sleep(REQUEST_DELAY_MS)
                val limit = request.url.queryParameter("limit")?.toIntOrNull() ?: Int.MAX_VALUE
                val body = when (path) {
                    "/api/favorites/artists" -> artists(LARGE)
                    "/api/favorites/releases" -> releases(LARGE)
                    "/api/history/artists" -> historyArtists(minOf(limit, LARGE))
                    "/api/history/albums" -> albums(minOf(limit, LARGE))
                    "/api/home/recently-added-albums" -> albums(minOf(limit, LARGE))
                    "/api/home/new-releases", "/api/home/discover-artists" -> "[]"
                    "/api/history/tracks" -> tracks(minOf(limit, LARGE))
                    "/api/playlists" -> "[]"
                    else -> "[]"
                }
                return MockResponse.Builder().code(200).addHeader("Content-Type", "application/json").body(body).build()
            }
        }
        server.start()
        scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    }

    @After
    fun tearDown() {
        scope.cancel()
        server.close()
    }

    private fun provider(): JamarrLibraryProvider {
        val url = server.url("/").toString().trimEnd('/')
        return JamarrLibraryProvider(
            apiClient = JamarrApiClient(TokenHolder("t")),
            credentials = { JamarrLibraryProvider.Credentials(url, "t") },
            scope = scope,
        )
    }

    private data class Measure(val ms: Long, val requests: Int, val largestLimit: Int?)

    private suspend fun firstPage(node: String): Measure {
        requests.clear()
        limits.clear()
        val p = provider()
        val start = System.nanoTime()
        val result = p.childrenResult(node, 0, PAGE_SIZE)
        val ms = (System.nanoTime() - start) / 1_000_000
        val items = checkNotNull(result.value) { "node $node failed: ${result.resultCode}" }
        assertEquals("page size", PAGE_SIZE, items.size)
        val m = Measure(ms, requests.values.sumOf { it.get() }, limits.values.maxOrNull())
        Log.i("BrowseLatency", "$node firstPage=${m.ms}ms requests=${m.requests} largestLimit=${m.largestLimit}")
        return m
    }

    @Test
    fun recentlyPlayedAlbumsFirstPageIsOneBoundedRequest() = runTest {
        val m = firstPage(BrowseTree.ID_RECENT_ALBUMS)
        assertEquals(1, m.requests)
        assertTrue("limit ${m.largestLimit} should be bounded", (m.largestLimit ?: Int.MAX_VALUE) <= 100)
    }

    @Test
    fun recentlyPlayedArtistsFirstPageIsOneBoundedRequest() = runTest {
        val m = firstPage(BrowseTree.ID_RECENT_ARTISTS)
        assertEquals(1, m.requests)
        assertTrue((m.largestLimit ?: Int.MAX_VALUE) <= 100)
    }

    @Test
    fun recentlyAddedFirstPageIsOneBoundedRequest() = runTest {
        val m = firstPage(BrowseTree.ID_ADDED)
        assertEquals(1, m.requests)
        assertTrue((m.largestLimit ?: Int.MAX_VALUE) <= 100)
    }

    @Test
    fun recentTracksFirstPageIsOneBoundedRequest() = runTest {
        val m = firstPage(BrowseTree.ID_RECENT_TRACKS)
        assertEquals(1, m.requests)
        assertTrue((m.largestLimit ?: Int.MAX_VALUE) <= 100)
    }

    @Test
    fun favouriteArtistsFirstPageIsOneRequest() = runTest {
        // No server-side paging exists for this endpoint; the cost is one
        // request and one parse, and must not grow with page count.
        val m = firstPage(BrowseTree.ID_FAV_ARTISTS)
        assertEquals(1, m.requests)
    }

    @Test
    fun laterPagesOfAPagedNodeHaveNoGapsOrDuplicates() = runTest {
        val p = provider()
        val seen = mutableListOf<String>()
        var page = 0
        while (true) {
            val items = checkNotNull(p.childrenResult(BrowseTree.ID_RECENT_ALBUMS, page, PAGE_SIZE).value)
            if (items.isEmpty()) break
            seen += items.map { it.mediaId }
            page++
            if (page > LARGE / PAGE_SIZE + 2) error("never reached the end")
        }
        assertEquals(LARGE, seen.size)
        assertEquals(seen.size, seen.toSet().size)
        assertEquals((0 until LARGE).map { BrowseTree.albumId("album-$it") }, seen)
        Log.i("BrowseLatency", "recent-albums all pages: requests=${requests["/api/history/albums"]?.get()} largestLimit=${limits["/api/history/albums"]}")
    }

    private fun artists(n: Int) = (0 until n).joinToString(",", "[", "]") {
        """{"mbid":"artist-$it","name":"Artist $it","art_sha1":"${"a".repeat(40)}"}"""
    }

    private fun historyArtists(n: Int) = (0 until n).joinToString(",", "[", "]") {
        """{"mbid":"artist-$it","name":"Artist $it","art_sha1":"${"a".repeat(40)}"}"""
    }

    private fun releases(n: Int) = (0 until n).joinToString(",", "[", "]") {
        """{"album_mbid":"album-$it","title":"Album $it","artist_name":"Artist","year":"2000"}"""
    }

    private fun albums(n: Int) = (0 until n).joinToString(",", "[", "]") {
        """{"album":"Album $it","artist_name":"Artist","album_mbid":"album-$it","year":"2000"}"""
    }

    private fun tracks(n: Int) = (0 until n).joinToString(",", "[", "]") {
        """{"track":{"id":${it + 1},"title":"Track $it","artist":"Artist","album":"Album","duration_seconds":200.0},"timestamp":"2026-01-01T00:00:00Z"}"""
    }

    companion object {
        const val LARGE = 2_000
        const val PAGE_SIZE = 20
        const val REQUEST_DELAY_MS = 40L
    }
}
