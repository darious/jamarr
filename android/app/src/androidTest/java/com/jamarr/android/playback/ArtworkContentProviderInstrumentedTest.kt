package com.jamarr.android.playback

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.jamarr.android.JamarrApplication
import com.jamarr.android.auth.SettingsStore
import java.io.File
import java.io.FileNotFoundException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.runBlocking
import mockwebserver3.Dispatcher
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
import okio.Buffer
import okio.ByteString.Companion.decodeBase64
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The artwork provider as the car host sees it: through the content
 * resolver, with a real server behind it. Covers the three sources (offline
 * store, provider cache, server), the grammar's refusals, and concurrency.
 */
@RunWith(AndroidJUnit4::class)
class ArtworkContentProviderInstrumentedTest {
    private val app = ApplicationProvider.getApplicationContext<JamarrApplication>()
    private val resolver = app.contentResolver
    private lateinit var server: MockWebServer
    private val hits = AtomicInteger()
    private var savedServerUrl: String = ""

    private val shaLocal = "1".repeat(40)
    private val shaRemote = "2".repeat(40)
    private val shaMissing = "3".repeat(40)

    @Before
    fun setUp() {
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val path = request.url.encodedPath
                if (path == "/api/art/file/$shaRemote") {
                    hits.incrementAndGet()
                    Thread.sleep(150)
                    return MockResponse.Builder().code(200).addHeader("Content-Type", "image/jpeg")
                        .body(Buffer().write(ONE_PIXEL_JPEG)).build()
                }
                return MockResponse.Builder().code(404).build()
            }
        }
        server.start()
        runBlocking {
            val store = SettingsStore(app)
            savedServerUrl = store.load().serverUrl
            store.saveServerUrl(server.url("/").toString().trimEnd('/'))
        }
        app.artworkStore.file(shaLocal).apply { parentFile?.mkdirs(); writeBytes(byteArrayOf(7, 7, 7)) }
        File(app.cacheDir, "auto_art").deleteRecursively()
    }

    @After
    fun tearDown() {
        runBlocking { SettingsStore(app).saveServerUrl(savedServerUrl) }
        app.artworkStore.file(shaLocal).delete()
        File(app.cacheDir, "auto_art").deleteRecursively()
        server.close()
    }

    private fun read(uri: android.net.Uri): ByteArray = resolver.openInputStream(uri)!!.use { it.readBytes() }

    @Test
    fun downloadedArtIsServedFromTheOfflineStore() {
        assertArrayEquals(byteArrayOf(7, 7, 7), read(ArtworkContentProvider.artUri(app, shaLocal)))
        assertEquals(0, hits.get())
    }

    @Test
    fun remoteArtIsFetchedOnceThenServedFromTheCache() {
        val uri = ArtworkContentProvider.artUri(app, shaRemote)
        assertArrayEquals(ONE_PIXEL_JPEG, read(uri))
        assertArrayEquals(ONE_PIXEL_JPEG, read(uri))
        assertEquals(1, hits.get())
        assertEquals("image/jpeg", resolver.getType(uri))
    }

    @Test
    fun concurrentRequestsForOneHashShareOneFetch() {
        val uri = ArtworkContentProvider.artUri(app, shaRemote)
        val pool = Executors.newFixedThreadPool(6)
        val done = CountDownLatch(6)
        val failures = AtomicInteger()
        repeat(6) {
            pool.execute {
                try {
                    if (!read(uri).contentEquals(ONE_PIXEL_JPEG)) failures.incrementAndGet()
                } catch (e: Exception) {
                    failures.incrementAndGet()
                } finally {
                    done.countDown()
                }
            }
        }
        assertTrue(done.await(30, TimeUnit.SECONDS))
        pool.shutdown()
        assertEquals(0, failures.get())
        assertEquals(1, hits.get())
    }

    @Test
    fun gridsAreComposedFromTheirTiles() {
        val uri = ArtworkContentProvider.gridUri(app, listOf(shaRemote, shaLocal))!!
        // Two tiles: one real JPEG and one undecodable blob; the compositor
        // falls back to the first decodable image, which is still a file.
        assertTrue(read(uri).isNotEmpty())
    }

    @Test
    fun missingArtAndBadPathsAreRefused() {
        for (bad in listOf(
            ArtworkContentProvider.artUri(app, shaMissing),
            ArtworkContentProvider.baseUri(app).buildUpon().path("art/../shared_prefs/x").build(),
            ArtworkContentProvider.baseUri(app).buildUpon().path("files/$shaLocal").build(),
            ArtworkContentProvider.baseUri(app).buildUpon().path("art/not-a-hash").build(),
        )) {
            try {
                resolver.openInputStream(bad)?.close()
                fail("expected $bad to be refused")
            } catch (expected: FileNotFoundException) {
                // good
            }
        }
        assertNull(resolver.getType(ArtworkContentProvider.baseUri(app).buildUpon().path("art/nope").build()))
        assertNull(ArtworkContentProvider.gridUri(app, listOf("junk")))
    }

    companion object {
        private val ONE_PIXEL_JPEG: ByteArray = (
            "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
            ).decodeBase64()!!.toByteArray()
    }
}
