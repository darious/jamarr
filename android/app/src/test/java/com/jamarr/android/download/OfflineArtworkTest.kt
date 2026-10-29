package com.jamarr.android.download

import java.nio.file.Files
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class OfflineArtworkTest {
    private val dir = Files.createTempDirectory("art").toFile()
    private val store = OfflineArtworkStore(dir)

    @Test
    fun `the artwork hash is read from any size of art URL`() {
        assertEquals("abc123", ArtworkUrls.sha1FromUrl("https://x/api/art/file/abc123?max_size=200"))
        assertEquals("abc123", ArtworkUrls.sha1FromUrl("http://x:8111/api/art/file/abc123"))
        assertNull(ArtworkUrls.sha1FromUrl("https://x/api/stream/12"))
    }

    @Test
    fun `art is fetched once and then served from disk`() = runTest {
        var fetches = 0
        val fetch: suspend (String) -> ByteArray? = { fetches++; byteArrayOf(1, 2, 3) }

        store.ensure("aa", fetch)
        store.ensure("aa", fetch)

        assertEquals(1, fetches)
        assertArrayEquals(byteArrayOf(1, 2, 3), store.existing("aa")!!.readBytes())
    }

    @Test
    fun `concurrent calls for one hash fetch once and leave no temp file`() = runTest {
        var fetches = 0
        val release = CompletableDeferred<Unit>()
        val fetch: suspend (String) -> ByteArray? = { fetches++; release.await(); byteArrayOf(9) }

        val a = launch { store.ensure("aa", fetch) }
        val b = launch { store.ensure("aa", fetch) }
        val other = launch { store.ensure("bb") { byteArrayOf(1) } }
        runCurrent()
        assertEquals(1, fetches)
        assertNotNull(store.existing("bb")) // a different hash is not held up
        release.complete(Unit)
        a.join(); b.join(); other.join()

        assertEquals(1, fetches)
        assertArrayEquals(byteArrayOf(9), store.existing("aa")!!.readBytes())
        assertEquals(listOf("aa.img", "bb.img"), dir.list()!!.sorted())
    }

    @Test
    fun `a failed fetch stores nothing`() = runTest {
        store.ensure("aa") { null }

        assertNull(store.existing("aa"))
    }

    @Test
    fun `pruning keeps only referenced art`() = runTest {
        store.ensure("aa") { byteArrayOf(1) }
        store.ensure("bb") { byteArrayOf(2) }

        store.prune(keep = setOf("bb"))

        assertNull(store.existing("aa"))
        assertNotNull(store.existing("bb"))
    }
}
