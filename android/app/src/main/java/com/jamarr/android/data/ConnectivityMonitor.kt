package com.jamarr.android.data

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import com.jamarr.android.auth.SettingsStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/** Why the app is, or is not, talking to the server. */
data class OnlineState(
    /** The user's own switch in the account dialog. */
    val manualOffline: Boolean = false,
    val networkAvailable: Boolean = true,
    /** Last `/api/health` answer; a phone on wifi can still be away from home. */
    val serverReachable: Boolean = true,
) {
    val isOffline: Boolean get() = manualOffline || !networkAvailable || !serverReachable
}

/**
 * Decides when the app is offline: the manual switch, no network at all, or a
 * network on which the server does not answer.
 *
 * The server is probed on every network change, whenever a caller reports a
 * failed request ([recheck]), and every [UNREACHABLE_RETRY_MS] while it is
 * down, so a phone coming back into range goes online without a tap.
 */
class ConnectivityMonitor(
    context: Context,
    private val settingsStore: SettingsStore,
    private val probe: suspend (serverUrl: String) -> Boolean,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val connectivityManager = context.getSystemService(ConnectivityManager::class.java)
    private val networkAvailable = MutableStateFlow(hasActiveNetwork())
    private val serverReachable = MutableStateFlow(true)
    private val recheckRequests = Channel<Unit>(Channel.CONFLATED)
    private val _reconnected = MutableSharedFlow<Unit>(extraBufferCapacity = 1)

    val state: StateFlow<OnlineState> = combine(
        settingsStore.observeOfflineMode(),
        networkAvailable,
        serverReachable,
    ) { manual, network, server ->
        OnlineState(manualOffline = manual, networkAvailable = network, serverReachable = server)
    }.stateIn(scope, SharingStarted.Eagerly, OnlineState(networkAvailable = networkAvailable.value))

    /** Fires each time the app goes from offline to online. */
    val reconnected: SharedFlow<Unit> = _reconnected.asSharedFlow()

    init {
        connectivityManager.registerDefaultNetworkCallback(
            object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) {
                    networkAvailable.value = true
                    recheck()
                }

                override fun onLost(network: Network) {
                    networkAvailable.value = hasActiveNetwork()
                    recheck()
                }
            },
        )
        scope.launch { probeLoop() }
        scope.launch {
            var wasOffline = state.value.isOffline
            state.collect { current ->
                if (wasOffline && !current.isOffline) _reconnected.tryEmit(Unit)
                wasOffline = current.isOffline
            }
        }
    }

    /** Asks for a fresh probe; call after a request to the server fails. */
    fun recheck() {
        recheckRequests.trySend(Unit)
    }

    private suspend fun probeLoop() {
        while (true) {
            val serverUrl = settingsStore.observeSession().first().serverUrl
            if (networkAvailable.value && serverUrl.isNotBlank()) {
                serverReachable.value = probe(serverUrl)
            }
            val wait = if (serverReachable.value && networkAvailable.value) {
                REACHABLE_RECHECK_MS
            } else {
                UNREACHABLE_RETRY_MS
            }
            withTimeoutOrNull(wait) { recheckRequests.receive() }
        }
    }

    private fun hasActiveNetwork(): Boolean {
        val network = connectivityManager.activeNetwork ?: return false
        val caps = connectivityManager.getNetworkCapabilities(network) ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    companion object {
        const val UNREACHABLE_RETRY_MS = 30_000L
        const val REACHABLE_RECHECK_MS = 5 * 60_000L
    }
}
