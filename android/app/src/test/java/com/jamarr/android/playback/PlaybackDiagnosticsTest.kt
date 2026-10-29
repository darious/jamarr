package com.jamarr.android.playback

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PlaybackDiagnosticsTest {

    private fun entry(at: Long, message: String? = null) = DiagnosticEntry(
        atMs = at,
        trackId = 7L,
        quality = "original",
        source = "network",
        kind = PlaybackFailureKind.NETWORK,
        errorCode = "ERROR_CODE_IO_NETWORK_CONNECTION_FAILED",
        httpStatus = null,
        message = message,
        network = "unmetered",
        outputRoute = "speaker",
        stage = "retry 1/3 in 1s",
    )

    @Test
    fun `the record is bounded and keeps the newest entries`() {
        val d = PlaybackDiagnostics(capacity = 3)
        (1..5).forEach { d.record(entry(it.toLong())) }
        assertEquals(listOf(3L, 4L, 5L), d.entries.value.map { it.atMs })
    }

    @Test
    fun `tokens and signed urls never reach the record`() {
        val d = PlaybackDiagnostics()
        d.record(entry(1L, "Response code: 403 for http://h/api/stream/7?token=abc.def.ghi&quality=original"))
        d.record(entry(2L, "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig_sig_sig_sig"))
        val text = d.exportText()
        assertFalse(text.contains("abc.def.ghi"))
        assertFalse(text.contains("eyJhbGci"))
        assertTrue(text.contains("token=…"))
        assertTrue(text.contains("quality=original"))
        assertTrue(text.contains("Bearer …"))
    }

    @Test
    fun `export carries the fields a bug report needs`() {
        val d = PlaybackDiagnostics()
        d.record(entry(1L, "boom"))
        val line = d.exportText()
        listOf("track=7", "quality=original", "source=network", "network=unmetered", "route=speaker",
            "kind=NETWORK", "code=ERROR_CODE_IO_NETWORK_CONNECTION_FAILED", "stage=retry 1/3 in 1s", ":: boom")
            .forEach { assertTrue("missing $it in $line", line.contains(it)) }
    }

    @Test
    fun `redaction leaves ordinary text alone`() {
        assertEquals("Connection refused to 192.168.1.107:8111", Redaction.scrub("Connection refused to 192.168.1.107:8111"))
        assertEquals("?quality=mp3_320", Redaction.scrub("?quality=mp3_320"))
    }
}
