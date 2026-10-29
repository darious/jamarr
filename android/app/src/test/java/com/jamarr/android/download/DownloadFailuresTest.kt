package com.jamarr.android.download

import java.io.IOException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DownloadFailuresTest {
    @Test
    fun `http status decides first`() {
        assertEquals(DownloadFailureReason.AUTH, DownloadFailures.classify(401, IOException("x")))
        assertEquals(DownloadFailureReason.AUTH, DownloadFailures.classify(403, null))
        assertEquals(DownloadFailureReason.NOT_FOUND, DownloadFailures.classify(404, null))
        assertEquals(DownloadFailureReason.SERVER, DownloadFailures.classify(502, null))
        assertEquals(DownloadFailureReason.SERVER, DownloadFailures.classify(418, null))
    }

    @Test
    fun `out of space is recognised anywhere in the cause chain`() {
        val wrapped = IOException("write failed", IOException("ENOSPC (No space left on device)"))
        assertEquals(DownloadFailureReason.STORAGE_FULL, DownloadFailures.classify(null, wrapped))
    }

    @Test
    fun `read-only and permission errors are storage errors, not network`() {
        assertEquals(DownloadFailureReason.STORAGE_IO, DownloadFailures.classify(null, IOException("EROFS (Read-only file system)")))
        assertEquals(DownloadFailureReason.STORAGE_IO, DownloadFailures.classify(null, IOException("open failed: EACCES (Permission denied)")))
    }

    @Test
    fun `connection failures are network`() {
        assertEquals(DownloadFailureReason.NETWORK, DownloadFailures.classify(null, UnknownHostException("jamarr")))
        assertEquals(DownloadFailureReason.NETWORK, DownloadFailures.classify(null, IOException("x", SocketTimeoutException())))
        assertEquals(DownloadFailureReason.NETWORK, DownloadFailures.classify(null, IOException("unexpected end of stream")))
    }

    @Test
    fun `anything else is unknown`() {
        assertEquals(DownloadFailureReason.UNKNOWN, DownloadFailures.classify(null, IllegalStateException("?")))
        assertEquals(DownloadFailureReason.UNKNOWN, DownloadFailures.classify(null, null))
    }

    @Test
    fun `only a missing track is not worth retrying`() {
        assertFalse(DownloadFailureReason.NOT_FOUND.retryable)
        DownloadFailureReason.entries.filter { it != DownloadFailureReason.NOT_FOUND }.forEach { assertTrue(it.retryable) }
    }

    @Test
    fun `names round-trip through the database column`() {
        DownloadFailureReason.entries.forEach { assertEquals(it, DownloadFailureReason.fromName(it.name)) }
        assertEquals(null, DownloadFailureReason.fromName(null))
        assertEquals(null, DownloadFailureReason.fromName("made_up"))
    }
}
