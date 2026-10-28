package com.jamarr.android.upnp

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class DiscoveryLifecycleTest {

    private class FakeEngine : DiscoveryEngine {
        var opens = 0
        var closes = 0
        var searches = 0
        var rebinds = 0
        var failOpen = false
        var signature = "wlan0/192.168.0.10"
        val isOpen get() = opens - closes > 0

        override fun open() {
            if (failOpen) throw IllegalStateException("no network")
            check(!isOpen) { "opened twice" }
            opens++
        }

        override fun close() {
            check(isOpen) { "closed while not open" }
            closes++
        }

        override fun search() {
            check(isOpen) { "search while closed" }
            searches++
        }

        override fun rebind() {
            rebinds++
        }

        override fun addressSignature(): String = signature
    }

    private class FakeNetwork : NetworkWatcher {
        var onChange: ((Boolean) -> Unit)? = null
        var registrations = 0
        var unregistrations = 0

        override fun register(onChange: (lost: Boolean) -> Unit) {
            registrations++
            this.onChange = onChange
        }

        override fun unregister() {
            unregistrations++
            onChange = null
        }
    }

    // advanceUntilIdle() skips backgroundScope work, so run the clock instead.
    private fun TestScope.settle() = advanceTimeBy(60_000)

    private fun TestScope.lifecycle(engine: FakeEngine, network: FakeNetwork) = DiscoveryLifecycle(
        engine = engine,
        network = network,
        scope = backgroundScope,
        startupSearchOffsetsMs = listOf(0L, 1_000L, 3_000L, 10_000L),
        burstSearchOffsetsMs = listOf(0L, 500L, 1_500L),
        networkDebounceMs = 2_000L,
    )

    @Test
    fun startRunsTheStartupBurstOnceThenGoesQuiet() = runTest {
        val engine = FakeEngine()
        val discovery = lifecycle(engine, FakeNetwork())

        discovery.start()
        runCurrent()
        assertEquals(1, engine.searches)
        advanceTimeBy(10_001)
        assertEquals(4, engine.searches)
        advanceTimeBy(10 * 60_000)
        assertEquals("no background searching after the burst", 4, engine.searches)
        assertFalse(discovery.isSearching)
    }

    @Test
    fun startAndStopAreIdempotent() = runTest {
        val engine = FakeEngine()
        val network = FakeNetwork()
        val discovery = lifecycle(engine, network)

        discovery.start()
        discovery.start()
        assertEquals(1, engine.opens)
        assertEquals(1, network.registrations)

        discovery.stop()
        discovery.stop()
        assertEquals(1, engine.closes)
        assertEquals(1, network.unregistrations)
        assertFalse(discovery.isRunning)
    }

    @Test
    fun stopCancelsTheStartupSearches() = runTest {
        val engine = FakeEngine()
        val discovery = lifecycle(engine, FakeNetwork())

        discovery.start()
        advanceTimeBy(1_500)
        assertEquals(2, engine.searches)
        discovery.stop()
        settle()
        assertEquals(2, engine.searches)
    }

    @Test
    fun rapidStopStartNeverOverlapsStartupSearches() = runTest {
        val engine = FakeEngine()
        val discovery = lifecycle(engine, FakeNetwork())

        repeat(5) {
            discovery.start()
            advanceTimeBy(200)
            discovery.stop()
        }
        discovery.start()
        settle()

        assertEquals(6, engine.opens)
        assertEquals(5, engine.closes)
        // 5 aborted bursts sent their t=0 search; only the last one ran to the end.
        assertEquals(5 + 4, engine.searches)
    }

    @Test
    fun failedStartReleasesNothingTwiceAndRetriesOnNetworkChange() = runTest {
        val engine = FakeEngine().apply { failOpen = true }
        val network = FakeNetwork()
        val discovery = lifecycle(engine, network)

        discovery.start()
        assertTrue(discovery.isRunning)
        assertFalse(discovery.isOpen)
        assertEquals(1, network.registrations)

        engine.failOpen = false
        network.onChange!!(false)
        advanceTimeBy(2_001)
        assertTrue(discovery.isOpen)
        assertEquals(1, engine.opens)
        settle()
        assertEquals(4, engine.searches)

        discovery.stop()
        assertEquals(1, engine.closes)
        assertEquals(1, network.unregistrations)
    }

    @Test
    fun stopAfterFailedStartUnregistersWithoutClosing() = runTest {
        val engine = FakeEngine().apply { failOpen = true }
        val network = FakeNetwork()
        val discovery = lifecycle(engine, network)

        discovery.start()
        discovery.stop()
        assertEquals(0, engine.closes)
        assertEquals(1, network.unregistrations)
        assertNull(network.onChange)
    }

    @Test
    fun pickerBurstIsSkippedWhileSearchesAreInFlight() = runTest {
        val engine = FakeEngine()
        val discovery = lifecycle(engine, FakeNetwork())

        discovery.start()
        runCurrent()
        discovery.searchBurst()
        settle()
        assertEquals(4, engine.searches)

        discovery.searchBurst()
        settle()
        assertEquals(4 + 3, engine.searches)
    }

    @Test
    fun pickerBurstDoesNothingWhenStopped() = runTest {
        val engine = FakeEngine()
        val discovery = lifecycle(engine, FakeNetwork())

        discovery.searchBurst()
        settle()
        assertEquals(0, engine.opens)
        assertEquals(0, engine.searches)
    }

    @Test
    fun networkChangesAreDebouncedIntoOneRebind() = runTest {
        val engine = FakeEngine()
        val network = FakeNetwork()
        val discovery = lifecycle(engine, network)
        discovery.start()
        settle()
        val before = engine.searches

        engine.signature = "wlan0/192.168.1.20"
        repeat(5) {
            network.onChange!!(false)
            advanceTimeBy(500)
        }
        assertEquals(0, engine.rebinds)
        advanceTimeBy(1_501)
        assertEquals(1, engine.rebinds)
        settle()
        assertEquals(before + 3, engine.searches)
    }

    @Test
    fun unchangedAddressesDoNotRebind() = runTest {
        val engine = FakeEngine()
        val network = FakeNetwork()
        val discovery = lifecycle(engine, network)
        discovery.start()
        settle()
        val before = engine.searches

        // Registering a callback replays onAvailable for every current network.
        network.onChange!!(false)
        settle()
        assertEquals(0, engine.rebinds)
        assertEquals(before, engine.searches)
    }

    @Test
    fun lostNetworkRebindsEvenWhenAddressesComeBackTheSame() = runTest {
        val engine = FakeEngine()
        val network = FakeNetwork()
        val discovery = lifecycle(engine, network)
        discovery.start()
        settle()

        network.onChange!!(true)
        network.onChange!!(false)
        settle()
        assertEquals(1, engine.rebinds)

        network.onChange!!(false)
        settle()
        assertEquals("the lost flag is consumed", 1, engine.rebinds)
    }

    @Test
    fun stopCancelsAPendingRecovery() = runTest {
        val engine = FakeEngine()
        val network = FakeNetwork()
        val discovery = lifecycle(engine, network)
        discovery.start()
        settle()

        val onChange = network.onChange!!
        engine.signature = "wlan0/10.0.0.5"
        onChange(true)
        discovery.stop()
        // A callback racing the unregister must not resurrect anything.
        onChange(true)
        settle()
        assertEquals(0, engine.rebinds)
        assertFalse(engine.isOpen)
    }

    @Test
    fun recoveryReplacesAnInFlightBurst() = runTest {
        val engine = FakeEngine()
        val network = FakeNetwork()
        val discovery = lifecycle(engine, network)
        discovery.start()
        advanceTimeBy(1)
        assertEquals(1, engine.searches)

        engine.signature = "wlan0/10.0.0.5"
        network.onChange!!(false)
        advanceTimeBy(2_001)
        assertEquals(1, engine.rebinds)
        settle()
        // Startup sent 0 s and 1 s before the rebind at 2 s cancelled it; then a 3-search burst.
        assertEquals(2 + 3, engine.searches)
    }
}
