package com.jamarr.android.playback

import android.content.ComponentName
import android.os.Bundle
import androidx.media3.session.MediaBrowser
import androidx.media3.session.SessionCommand
import androidx.media3.session.SessionResult
import androidx.media3.session.SessionToken
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.common.util.concurrent.ListenableFuture
import com.jamarr.android.auth.SettingsStore
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * End-to-end harness: connects to [JamarrPlaybackService] through a real
 * `MediaBrowser`, the same interface Android Auto uses.
 *
 * This is the test that would catch a broken manifest, a session that never
 * builds, or connection filtering that locks out legitimate callers — none of
 * which the provider-level tests can see. Content assertions live in
 * [JamarrLibraryProviderInstrumentedTest]; this one is about the plumbing.
 *
 * Controller calls must happen on the application thread and their futures must
 * not be awaited there, so every call is issued via [onMain] and resolved on the
 * test thread.
 */
@RunWith(AndroidJUnit4::class)
class MediaBrowserHarnessTest {

    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext
    private var browser: MediaBrowser? = null

    @Before
    fun setUp() {
        // Leave no half-written resumption state behind from another test.
        runBlocking { SettingsStore(context).saveResumeQueue(null) }
    }

    @After
    fun tearDown() {
        instrumentation.runOnMainSync {
            browser?.release()
            browser = null
        }
    }

    private fun <T> onMain(block: () -> ListenableFuture<T>): T {
        lateinit var future: ListenableFuture<T>
        instrumentation.runOnMainSync { future = block() }
        return future.get(TIMEOUT_SECONDS, TimeUnit.SECONDS)
    }

    private fun <T> readOnMain(block: () -> T): T {
        var value: T? = null
        instrumentation.runOnMainSync { value = block() }
        @Suppress("UNCHECKED_CAST")
        return value as T
    }

    private fun connect(): MediaBrowser {
        val connected = onMain {
            val token = SessionToken(
                context,
                ComponentName(context, JamarrPlaybackService::class.java),
            )
            MediaBrowser.Builder(context, token).buildAsync()
        }
        browser = connected
        return connected
    }

    @Test
    fun ourOwnAppCanConnectToTheSession() {
        // onConnect rejects unknown callers; rejecting ourselves would take the
        // phone UI down along with the car.
        val connected = connect()

        assertTrue(readOnMain { connected.isConnected })
    }

    @Test
    fun theLibraryRootIsBrowsable() {
        val connected = connect()

        val result = onMain { connected.getLibraryRoot(null) }

        assertEquals(0, result.resultCode)
        val root = requireNotNull(result.value) { "library root had no item" }
        assertEquals(BrowseTree.ID_ROOT, root.mediaId)
        assertEquals(true, root.mediaMetadata.isBrowsable)
    }

    @Test
    fun rootChildrenComeBackOverTheBrowserInterface() {
        val connected = connect()
        onMain { connected.getLibraryRoot(null) }

        val children = onMain { connected.getChildren(BrowseTree.ID_ROOT, 0, PAGE_SIZE, null) }

        assertEquals(0, children.resultCode)
        // Signed out this is the sign-in prompt, signed in it is the folder
        // list; either way the tree must answer rather than hang or error.
        assertTrue("expected at least one row", children.value.orEmpty().isNotEmpty())
    }

    @Test
    fun searchIsAnsweredOverTheBrowserInterface() {
        val connected = connect()
        onMain { connected.getLibraryRoot(null) }

        val outcome = onMain { connected.search("angel", null) }

        // Signed out the service says so; signed in it accepts and later
        // notifies. Either is an answer; a hang or ERROR_NOT_SUPPORTED means
        // the callback was not forwarded through the service.
        assertTrue(
            "unexpected search result code ${outcome.resultCode}",
            outcome.resultCode == 0 ||
                outcome.resultCode == androidx.media3.session.SessionError.ERROR_SESSION_AUTHENTICATION_EXPIRED,
        )
    }

    @Test
    fun shuffleAndRepeatAreOfferedAsButtonsAndToggleThroughCustomCommands() {
        val connected = connect()
        val before = readOnMain { connected.shuffleModeEnabled }

        // The connection carries the button preferences and authorises the
        // commands behind them; a controller media3 did not accept would get
        // ERROR_NOT_SUPPORTED here.
        val prefs = readOnMain { connected.mediaButtonPreferences }
        assertTrue(prefs.any { it.sessionCommand?.customAction == MediaButtonPolicy.CMD_TOGGLE_SHUFFLE })
        assertTrue(prefs.any { it.sessionCommand?.customAction == MediaButtonPolicy.CMD_CYCLE_REPEAT })

        val result = onMain {
            connected.sendCustomCommand(SessionCommand(MediaButtonPolicy.CMD_TOGGLE_SHUFFLE, Bundle.EMPTY), Bundle.EMPTY)
        }
        assertEquals(SessionResult.RESULT_SUCCESS, result.resultCode)
        assertEquals(!before, readOnMain { connected.shuffleModeEnabled })

        // Put it back so the device is left as found.
        onMain { connected.sendCustomCommand(SessionCommand(MediaButtonPolicy.CMD_TOGGLE_SHUFFLE, Bundle.EMPTY), Bundle.EMPTY) }
        assertEquals(before, readOnMain { connected.shuffleModeEnabled })

        val unknown = onMain { connected.sendCustomCommand(SessionCommand("com.jamarr.android.NOPE", Bundle.EMPTY), Bundle.EMPTY) }
        assertTrue(unknown.resultCode != SessionResult.RESULT_SUCCESS)
    }

    companion object {
        private const val TIMEOUT_SECONDS = 20L
        private const val PAGE_SIZE = 20
    }
}
