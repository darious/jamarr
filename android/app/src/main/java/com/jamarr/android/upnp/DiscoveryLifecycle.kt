package com.jamarr.android.upnp

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * The jUPnP-facing half of discovery, kept behind an interface so the
 * lifecycle below runs on the JVM in tests.
 */
interface DiscoveryEngine {
    /** Brings the stack up. Releases whatever it acquired before throwing. */
    fun open()

    fun close()

    /** Sends one round of M-SEARCH requests. */
    fun search()

    /** Re-reads the network interfaces and rebinds the sockets to them. */
    fun rebind()

    /** The addresses the stack would bind to now; a change means a rebind is due. */
    fun addressSignature(): String
}

/** Reports LAN changes; `lost` is true when a network went away. */
interface NetworkWatcher {
    fun register(onChange: (lost: Boolean) -> Unit)

    fun unregister()
}

/**
 * Start/stop, search scheduling and network recovery for UPnP discovery.
 *
 * - [start]/[stop] are idempotent; a stop cancels every search and recovery
 *   job, so a quick stop/start never leaves two schedules running.
 * - Searches go out in short bursts: one after startup, one when the picker
 *   opens ([searchBurst]) and one after a network change. Nothing repeats in
 *   the background; jUPnP's registry keeps devices alive from their own
 *   NOTIFY announcements.
 * - jUPnP binds to the interfaces present when its router is enabled and
 *   never looks again, so a network change (debounced) rebinds it when the
 *   address set changed or a network was lost, then searches again. A start
 *   that failed (no network yet) is retried on the next change.
 */
class DiscoveryLifecycle(
    private val engine: DiscoveryEngine,
    private val network: NetworkWatcher,
    private val scope: CoroutineScope,
    private val startupSearchOffsetsMs: List<Long> = STARTUP_SEARCH_OFFSETS_MS,
    private val burstSearchOffsetsMs: List<Long> = BURST_SEARCH_OFFSETS_MS,
    private val networkDebounceMs: Long = NETWORK_DEBOUNCE_MS,
    private val onError: (String, Throwable) -> Unit = { _, _ -> },
) {
    private val lock = Any()
    private var wanted = false
    private var open = false
    private var generation = 0
    private var boundSignature: String? = null
    private var pendingLost = false
    private var searchJob: Job? = null
    private var networkJob: Job? = null

    val isRunning: Boolean get() = synchronized(lock) { wanted }
    val isOpen: Boolean get() = synchronized(lock) { open }
    val isSearching: Boolean get() = synchronized(lock) { searchJob?.isActive == true }

    fun start() {
        synchronized(lock) {
            if (wanted) return
            wanted = true
            generation++
            try {
                network.register(::onNetworkChanged)
            } catch (e: Throwable) {
                onError("network callback registration failed", e)
            }
            openLocked()
        }
    }

    fun stop() {
        synchronized(lock) {
            if (!wanted) return
            wanted = false
            generation++
            searchJob?.cancel()
            searchJob = null
            networkJob?.cancel()
            networkJob = null
            pendingLost = false
            try {
                network.unregister()
            } catch (e: Throwable) {
                onError("network callback unregistration failed", e)
            }
            if (open) {
                open = false
                try {
                    engine.close()
                } catch (e: Throwable) {
                    onError("shutdown failed", e)
                }
            }
            boundSignature = null
        }
    }

    /**
     * A short burst of searches, e.g. when the renderer picker opens. A no-op
     * while another burst is still going.
     */
    fun searchBurst() {
        synchronized(lock) {
            if (!wanted) return
            if (!open) {
                openLocked()
                return
            }
            if (searchJob?.isActive == true) return
            launchSearchesLocked(burstSearchOffsetsMs)
        }
    }

    fun onNetworkChanged(lost: Boolean) {
        synchronized(lock) {
            if (!wanted) return
            pendingLost = pendingLost || lost
            networkJob?.cancel()
            val gen = generation
            networkJob = scope.launch {
                delay(networkDebounceMs)
                recover(gen)
            }
        }
    }

    private fun recover(gen: Int) {
        synchronized(lock) {
            if (!wanted || gen != generation) return
            val lost = pendingLost
            pendingLost = false
            if (!open) {
                openLocked()
                return
            }
            val signature = engine.addressSignature()
            if (!lost && signature == boundSignature) return
            try {
                engine.rebind()
            } catch (e: Throwable) {
                onError("rebind failed", e)
                return
            }
            boundSignature = signature
            searchJob?.cancel()
            launchSearchesLocked(burstSearchOffsetsMs)
        }
    }

    private fun openLocked(): Boolean {
        try {
            engine.open()
        } catch (e: Throwable) {
            onError("start failed", e)
            return false
        }
        open = true
        boundSignature = engine.addressSignature()
        searchJob?.cancel()
        launchSearchesLocked(startupSearchOffsetsMs)
        return true
    }

    private fun launchSearchesLocked(offsetsMs: List<Long>) {
        val gen = generation
        searchJob = scope.launch {
            var elapsed = 0L
            for (offset in offsetsMs) {
                delay(offset - elapsed)
                elapsed = offset
                synchronized(lock) {
                    if (gen != generation || !open) return@launch
                    try {
                        engine.search()
                    } catch (e: Throwable) {
                        onError("search failed", e)
                    }
                }
            }
        }
    }

    companion object {
        /** After startup: a quick retry for lost packets, then two slower ones for sleepy renderers. */
        val STARTUP_SEARCH_OFFSETS_MS = listOf(0L, 1_000L, 3_000L, 10_000L)

        /** Picker open / network change: three sends ~0.5–1 s apart. */
        val BURST_SEARCH_OFFSETS_MS = listOf(0L, 500L, 1_500L)

        /** Network callbacks arrive in clusters (lost, available, link props). */
        const val NETWORK_DEBOUNCE_MS = 2_000L
    }
}
