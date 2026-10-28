package com.jamarr.android.upnp

import android.content.Context
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiManager
import android.util.Log
import com.jamarr.android.renderer.DeviceRendererController
import com.jamarr.android.renderer.DeviceRendererInfo
import com.jamarr.android.renderer.DeviceRendererPlaybackState
import com.jamarr.android.renderer.QueuedTrack
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.jupnp.UpnpService
import org.jupnp.UpnpServiceImpl
import org.jupnp.android.AndroidUpnpServiceConfiguration
import org.jupnp.controlpoint.ActionCallback
import org.jupnp.model.action.ActionInvocation
import org.jupnp.model.meta.Action
import org.jupnp.model.message.UpnpResponse
import org.jupnp.model.message.header.UDADeviceTypeHeader
import org.jupnp.model.message.header.UDAServiceTypeHeader
import org.jupnp.model.meta.LocalDevice
import org.jupnp.model.meta.RemoteDevice
import org.jupnp.model.meta.Service as UpnpModelService
import org.jupnp.model.types.UDADeviceType
import org.jupnp.model.types.UDAServiceType
import org.jupnp.model.types.UnsignedIntegerFourBytes
import org.jupnp.registry.DefaultRegistryListener
import org.jupnp.registry.Registry
import org.jupnp.support.avtransport.callback.GetPositionInfo
import org.jupnp.support.avtransport.callback.GetTransportInfo
import org.jupnp.support.avtransport.callback.Pause
import org.jupnp.support.avtransport.callback.Play
import org.jupnp.support.avtransport.callback.Seek
import org.jupnp.support.avtransport.callback.SetAVTransportURI
import org.jupnp.support.avtransport.callback.Stop
import org.jupnp.support.model.PositionInfo
import org.jupnp.support.model.SeekMode
import org.jupnp.support.model.TransportInfo
import org.jupnp.support.model.TransportState
import org.jupnp.support.renderingcontrol.callback.SetVolume
import java.net.Inet4Address
import java.net.NetworkInterface
import kotlin.coroutines.cancellation.CancellationException
import kotlin.coroutines.Continuation
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlin.coroutines.suspendCoroutine

private const val TAG = "UpnpDeviceController"
private const val SET_NEXT_AV_TRANSPORT_URI = "SetNextAVTransportURI"

class UpnpDeviceController(private val appContext: Context) : DeviceRendererController {
    override val kind: String = "upnp"

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    @Volatile private var upnpService: UpnpService? = null
    private var pollJob: Job? = null

    private val _renderers = MutableStateFlow<List<DeviceRendererInfo>>(emptyList())
    override val renderers: StateFlow<List<DeviceRendererInfo>> = _renderers.asStateFlow()

    private val _state = MutableStateFlow(DeviceRendererPlaybackState())
    override val state: StateFlow<DeviceRendererPlaybackState> = _state.asStateFlow()

    private val endpoints = RendererEndpointIndex()

    /**
     * Mints a fresh stream URL for a track at load/staging time. UPnP stream
     * tokens are short-lived, so the URLs resolved when the queue was built
     * may have expired by the time a later track plays. Null: use those.
     */
    @Volatile var streamUrlResolver: (suspend (QueuedTrack) -> String)? = null

    override val resolvesStreamUrls: Boolean get() = streamUrlResolver != null

    private val sequencer = UpnpTrackSequencer(resolveUri = ::resolveStreamUrl)

    /** Serialises the sequencer: loads, and each poll's reconcile + staging. */
    private val opLock = Mutex()

    /** Renderers whose SetNextAVTransportURI let us down this session. */
    private val setNextDisabled = mutableSetOf<String>()

    private val mediaRendererType = UDADeviceType("MediaRenderer")
    private val avTransportType = UDAServiceType("AVTransport")

    private val registryListener = object : DefaultRegistryListener() {
        override fun remoteDeviceAdded(registry: Registry, device: RemoteDevice) {
            onRootDevice(device)
        }
        override fun remoteDeviceUpdated(registry: Registry, device: RemoteDevice) {
            onRootDevice(device)
        }
        override fun remoteDeviceRemoved(registry: Registry, device: RemoteDevice) {
            removeEndpoints(endpoints.removeRoot(device.identity.udn.identifierString))
        }
        override fun localDeviceAdded(registry: Registry, device: LocalDevice) {}
        override fun localDeviceRemoved(registry: Registry, device: LocalDevice) {}
    }

    private val engine = object : DiscoveryEngine {
        private var multicastLock: WifiManager.MulticastLock? = null

        override fun open() {
            val wifi = appContext.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
            val lock = wifi?.createMulticastLock("jamarr-upnp")?.apply {
                setReferenceCounted(false)
                acquire()
            }
            var service: UpnpServiceImpl? = null
            try {
                service = UpnpServiceImpl(AndroidUpnpServiceConfiguration())
                service.startup()
                service.registry.addListener(registryListener)
                multicastLock = lock
                upnpService = service
                Log.i(TAG, "UPnP service started")
            } catch (e: Throwable) {
                service?.let { teardown(it) }
                lock?.let { runCatching { it.release() } }
                throw e
            }
        }

        override fun close() {
            val service = upnpService
            upnpService = null
            try {
                service?.let { teardown(it) }
            } finally {
                multicastLock?.let { runCatching { it.release() } }
                multicastLock = null
                endpoints.clear()
                publishRenderers()
            }
            Log.i(TAG, "UPnP service stopped")
        }

        override fun search() {
            val cp = upnpService?.controlPoint ?: return
            cp.search()
            cp.search(UDADeviceTypeHeader(mediaRendererType))
            cp.search(UDAServiceTypeHeader(avTransportType))
        }

        override fun rebind() {
            val router = upnpService?.router ?: return
            Log.i(TAG, "network changed; rebinding UPnP router")
            router.disable()
            router.enable()
        }

        override fun forgetDevices() {
            // The registry fires remoteDeviceRemoved per device; clear our
            // side as well so nothing from the old network survives.
            runCatching { upnpService?.registry?.removeAllRemoteDevices() }
            val udns = endpoints.all().map { it.udn }.toSet()
            endpoints.clear()
            removeEndpoints(udns)
        }

        override fun addressSignature(): String = lanAddressSignature()
    }

    private val networkWatcher = object : NetworkWatcher {
        private var callback: ConnectivityManager.NetworkCallback? = null

        override fun register(onChange: (lost: Boolean) -> Unit) {
            if (callback != null) return
            val cm = appContext.getSystemService(ConnectivityManager::class.java) ?: return
            // Any network, VPNs and LANs without internet included: all of
            // them change the interfaces jUPnP binds to.
            val request = NetworkRequest.Builder()
                .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                .removeCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
                .build()
            val cb = object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) = onChange(false)
                override fun onLost(network: Network) = onChange(true)
                override fun onLinkPropertiesChanged(network: Network, linkProperties: LinkProperties) =
                    onChange(false)
            }
            cm.registerNetworkCallback(request, cb)
            callback = cb
        }

        override fun unregister() {
            val cb = callback ?: return
            callback = null
            appContext.getSystemService(ConnectivityManager::class.java)?.unregisterNetworkCallback(cb)
        }
    }

    private val discovery = DiscoveryLifecycle(
        engine = engine,
        network = networkWatcher,
        scope = scope,
        onError = { msg, e -> Log.w(TAG, msg, e) },
    )

    /** Starts discovery; idempotent. Searches once in a short burst, then listens. */
    override fun start() = discovery.start()

    /** Stops discovery and releases the multicast lock, callbacks and sockets; idempotent. */
    override fun stop() {
        stopPolling()
        discovery.stop()
    }

    /** A short burst of searches; a no-op while one is already in flight. */
    override fun search() = discovery.searchBurst()

    /** For the renderer picker: search now, since the user is looking. */
    fun searchBurst() = discovery.searchBurst()

    private fun onRootDevice(root: RemoteDevice) {
        val gone = endpoints.update(root)
        if (gone.isNotEmpty()) removeEndpoints(gone) else publishRenderers()
    }

    private fun removeEndpoints(udns: Set<String>) {
        publishRenderers()
        val active = _state.value.activeRendererId?.removePrefix("upnp:") ?: return
        if (active in udns) {
            stopPolling()
            sequencer.attach(supportsSetNext = false)
            _state.value = _state.value.copy(activeRendererId = null, isPlaying = false)
        }
    }

    private fun publishRenderers() {
        val list = endpoints.all().map { e ->
            val d = e.device
            val root = d.root
            DeviceRendererInfo(
                rendererId = "upnp:${e.udn}",
                kind = kind,
                name = d.details?.friendlyName ?: root.details?.friendlyName ?: d.displayString ?: "Renderer",
                manufacturer = (d.details ?: root.details)?.manufacturerDetails?.manufacturer,
                modelName = (d.details ?: root.details)?.modelDetails?.modelName,
                ip = root.identity?.descriptorURL?.host,
            )
        }.sortedBy { it.name.lowercase() }
        if (list != _renderers.value) {
            Log.i(TAG, "renderers: count=${list.size} ${list.map { it.name }}")
            _renderers.value = list
        }
    }

    override fun selectRenderer(rendererId: String) {
        val udn = rendererId.removePrefix("upnp:")
        val endpoint = endpoints[udn] ?: return
        if (_state.value.activeRendererId != "upnp:$udn") {
            val advertised = endpoint.service(AV_TRANSPORT)?.getAction(SET_NEXT_AV_TRANSPORT_URI) != null
            sequencer.attach(supportsSetNext = advertised && udn !in setNextDisabled)
        }
        _state.value = _state.value.copy(activeRendererId = "upnp:$udn")
        startPolling()
    }

    private fun activeEndpoint(): RendererEndpoint? =
        _state.value.activeRendererId?.removePrefix("upnp:")?.let { endpoints[it] }

    private fun avtService(): UpnpModelService<*, *>? = activeEndpoint()?.service(AV_TRANSPORT)

    private fun rcService(): UpnpModelService<*, *>? = activeEndpoint()?.service(RENDERING_CONTROL)

    override suspend fun playQueue(tracks: List<QueuedTrack>, startIndex: Int) {
        if (tracks.isEmpty()) return
        playTrackAt(startIndex.coerceIn(0, tracks.lastIndex), tracks)
    }

    /**
     * Loads [index] of [queue] and plays it. State moves to the new track
     * only once the renderer accepted its URI; on a failed load it keeps
     * reporting what the renderer still has, plus an error in `status`.
     */
    private suspend fun playTrackAt(index: Int, queue: List<QueuedTrack> = _state.value.queue) {
        val track = queue.getOrNull(index) ?: return
        val service = avtService() ?: run {
            Log.w(TAG, "No AVTransport service on active renderer")
            _state.value = _state.value.copy(status = "Renderer unavailable.")
            return
        }
        stopPolling()
        val before = _state.value
        val result = opLock.withLock { sequencer.load(JupnpAvTransport(service), index, queue) }
        _state.value = when (result) {
            LoadResult.Playing -> _state.value.copy(
                queue = sequencer.queue,
                currentIndex = sequencer.currentIndex,
                positionSeconds = 0.0,
                durationSeconds = track.durationSeconds,
                isPlaying = true,
                transportState = "TRANSITIONING",
                status = null,
            )
            is LoadResult.PlayFailed -> {
                Log.w(TAG, "Play failed: ${result.message}")
                _state.value.copy(
                    queue = sequencer.queue,
                    currentIndex = sequencer.currentIndex,
                    positionSeconds = 0.0,
                    durationSeconds = track.durationSeconds,
                    isPlaying = false,
                    transportState = "STOPPED",
                    status = "Renderer would not play “${track.title}”: ${result.message}",
                )
            }
            is LoadResult.LoadFailed -> {
                Log.w(TAG, "SetAVTransportURI failed: ${result.message}")
                before.copy(
                    queue = sequencer.queue,
                    currentIndex = sequencer.currentIndex,
                    status = "Renderer could not load “${track.title}”: ${result.message}",
                )
            }
        }
        startPolling()
    }

    override suspend fun pause() {
        val service = avtService() ?: return
        runCatching { pauseInternal(service) }
        _state.value = _state.value.copy(isPlaying = false, transportState = "PAUSED_PLAYBACK")
    }

    override suspend fun resume() {
        val service = avtService() ?: return
        runCatching { play(service) }
        _state.value = _state.value.copy(isPlaying = true, transportState = "PLAYING")
    }

    override suspend fun stopPlayback() {
        val service = avtService()
        if (service != null) runCatching { stopInternal(service) }
        stopPolling()
        opLock.withLock { sequencer.stop(service?.let { JupnpAvTransport(it) }) }
        _state.value = _state.value.copy(
            queue = emptyList(),
            currentIndex = -1,
            positionSeconds = 0.0,
            isPlaying = false,
            transportState = "STOPPED",
        )
    }

    override suspend fun seek(seconds: Double) {
        val service = avtService() ?: return
        val target = formatHms(seconds.toLong())
        runCatching { seekInternal(service, target) }
        _state.value = _state.value.copy(positionSeconds = seconds)
    }

    override suspend fun setVolumePercent(percent: Int) {
        val service = rcService() ?: return
        val v = percent.coerceIn(0, 100)
        runCatching { setVolumeInternal(service, v.toLong()) }
        _state.value = _state.value.copy(volumePercent = v)
    }

    override suspend fun next() {
        val s = _state.value
        if (s.queue.isEmpty()) return
        val nextIdx = (s.currentIndex + 1).coerceAtMost(s.queue.lastIndex)
        if (nextIdx == s.currentIndex) return
        playTrackAt(nextIdx)
    }

    override suspend fun previous() {
        val s = _state.value
        if (s.queue.isEmpty()) return
        val prevIdx = (s.currentIndex - 1).coerceAtLeast(0)
        if (prevIdx == s.currentIndex) return
        playTrackAt(prevIdx)
    }

    override suspend fun jumpTo(index: Int) {
        val s = _state.value
        if (s.queue.isEmpty()) return
        playTrackAt(index.coerceIn(0, s.queue.lastIndex))
    }

    private fun startPolling() {
        stopPolling()
        pollJob = scope.launch {
            delay(2000) // Renderer settle.
            while (true) {
                val service = avtService() ?: break
                val pos = runCatching { getPositionInfo(service) }.getOrNull()
                val xport = runCatching { getTransportInfo(service) }.getOrNull()
                val transportState = xport?.currentTransportState
                val rel = pos?.trackElapsedSeconds?.toDouble() ?: 0.0
                val dur = pos?.trackDurationSeconds?.toDouble() ?: 0.0
                val isPlaying = transportState == TransportState.PLAYING ||
                    transportState == TransportState.TRANSITIONING
                val stateName = transportState?.value ?: "STOPPED"

                val outcome = opLock.withLock {
                    val o = sequencer.observe(pos?.trackURI, transportState?.value)
                    if (o == PollOutcome.None && transportState == TransportState.PLAYING) {
                        sequencer.syncNext(JupnpAvTransport(service), rel, dur)
                    }
                    if (sequencer.stagingDisabled) noteSetNextDisabled()
                    o
                }

                val current = _state.value
                val transitioned = outcome is PollOutcome.Transitioned
                _state.value = current.copy(
                    currentIndex = if (transitioned) sequencer.currentIndex else current.currentIndex,
                    positionSeconds = if (rel > 0 || isPlaying) rel else current.positionSeconds,
                    durationSeconds = when {
                        dur > 0 -> dur
                        outcome is PollOutcome.Transitioned -> sequencer.queue[outcome.index].durationSeconds
                        else -> current.durationSeconds
                    },
                    isPlaying = isPlaying,
                    transportState = stateName,
                )

                when (outcome) {
                    is PollOutcome.Transitioned -> {
                        Log.i(TAG, "renderer moved onto staged track ${outcome.index}")
                        if (outcome.needsPlay) runCatching { play(service) }
                    }
                    is PollOutcome.Ended -> {
                        val next = outcome.nextIndex
                        if (next != null) {
                            // Load outside this job: playTrackAt stops polling.
                            scope.launch { playTrackAt(next) }
                            break
                        }
                        _state.value = _state.value.copy(isPlaying = false)
                    }
                    PollOutcome.None -> {}
                }

                delay(1000)
            }
        }
    }

    private fun noteSetNextDisabled() {
        val udn = _state.value.activeRendererId?.removePrefix("upnp:") ?: return
        if (setNextDisabled.add(udn)) {
            Log.w(TAG, "SetNextAVTransportURI unreliable on $udn; staging off for this session")
        }
    }

    private suspend fun resolveStreamUrl(track: QueuedTrack): String {
        val resolver = streamUrlResolver ?: return track.streamUrl
        return try {
            resolver(track)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Log.w(TAG, "stream URL refresh failed for ${track.id}: ${e.message}")
            // Queues are built without URLs when we resolve them; then there
            // is nothing to fall back on, and the load (or staging) fails.
            track.streamUrl.ifBlank { throw e }
        }
    }

    private inner class JupnpAvTransport(private val service: UpnpModelService<*, *>) : AvTransportPort {
        override suspend fun setUri(uri: String, metadata: String) = setAvTransportUri(service, uri, metadata)

        override suspend fun setNextUri(uri: String, metadata: String) = setNextAvTransportUri(service, uri, metadata)

        override suspend fun play() = play(service)
    }

    private fun stopPolling() {
        pollJob?.cancel()
        pollJob = null
    }

    // --- Action invocations (callback → coroutine adapters) ---

    private fun execute(callback: ActionCallback) {
        val cp = upnpService?.controlPoint ?: throw IllegalStateException("UPnP not started")
        cp.execute(callback)
    }

    private suspend fun setAvTransportUri(service: UpnpModelService<*, *>, uri: String, didl: String): Unit =
        withContext(Dispatchers.IO) {
            suspendCoroutine { cont: Continuation<Unit> ->
                execute(object : SetAVTransportURI(service, uri, didl) {
                    override fun success(invocation: ActionInvocation<*>?) { cont.resume(Unit) }
                    override fun failure(invocation: ActionInvocation<*>?, op: UpnpResponse?, defaultMsg: String?) {
                        cont.resumeWithException(RuntimeException(defaultMsg ?: "SetAVTransportURI failed"))
                    }
                })
            }
        }

    /** jUPnP ships no callback for this one, so the invocation is built by hand. */
    private suspend fun setNextAvTransportUri(service: UpnpModelService<*, *>, uri: String, didl: String): Unit =
        withContext(Dispatchers.IO) {
            @Suppress("UNCHECKED_CAST")
            val action = service.getAction(SET_NEXT_AV_TRANSPORT_URI) as? Action<UpnpModelService<*, *>>
                ?: throw IllegalStateException("$SET_NEXT_AV_TRANSPORT_URI not supported")
            val invocation = ActionInvocation(action).apply {
                setInput("InstanceID", UnsignedIntegerFourBytes(0))
                setInput("NextURI", uri)
                setInput("NextURIMetaData", didl)
            }
            suspendCoroutine { cont: Continuation<Unit> ->
                execute(object : ActionCallback(invocation) {
                    override fun success(invocation: ActionInvocation<*>?) { cont.resume(Unit) }
                    override fun failure(invocation: ActionInvocation<*>?, op: UpnpResponse?, defaultMsg: String?) {
                        cont.resumeWithException(RuntimeException(defaultMsg ?: "$SET_NEXT_AV_TRANSPORT_URI failed"))
                    }
                })
            }
        }

    private suspend fun play(service: UpnpModelService<*, *>): Unit = withContext(Dispatchers.IO) {
        suspendCoroutine { cont: Continuation<Unit> ->
            execute(object : Play(service) {
                override fun success(invocation: ActionInvocation<*>?) { cont.resume(Unit) }
                override fun failure(invocation: ActionInvocation<*>?, op: UpnpResponse?, defaultMsg: String?) {
                    val msg = defaultMsg ?: "Play failed"
                    if (msg.contains("701") || msg.contains("Transition", ignoreCase = true)) cont.resume(Unit)
                    else cont.resumeWithException(RuntimeException(msg))
                }
            })
        }
    }

    private suspend fun pauseInternal(service: UpnpModelService<*, *>): Unit = withContext(Dispatchers.IO) {
        suspendCoroutine { cont: Continuation<Unit> ->
            execute(object : Pause(service) {
                override fun success(invocation: ActionInvocation<*>?) { cont.resume(Unit) }
                override fun failure(invocation: ActionInvocation<*>?, op: UpnpResponse?, defaultMsg: String?) {
                    cont.resumeWithException(RuntimeException(defaultMsg ?: "Pause failed"))
                }
            })
        }
    }

    private suspend fun stopInternal(service: UpnpModelService<*, *>): Unit = withContext(Dispatchers.IO) {
        suspendCoroutine { cont: Continuation<Unit> ->
            execute(object : Stop(service) {
                override fun success(invocation: ActionInvocation<*>?) { cont.resume(Unit) }
                override fun failure(invocation: ActionInvocation<*>?, op: UpnpResponse?, defaultMsg: String?) {
                    cont.resumeWithException(RuntimeException(defaultMsg ?: "Stop failed"))
                }
            })
        }
    }

    private suspend fun seekInternal(service: UpnpModelService<*, *>, target: String): Unit =
        withContext(Dispatchers.IO) {
            suspendCoroutine { cont: Continuation<Unit> ->
                execute(object : Seek(service, SeekMode.REL_TIME, target) {
                    override fun success(invocation: ActionInvocation<*>?) { cont.resume(Unit) }
                    override fun failure(invocation: ActionInvocation<*>?, op: UpnpResponse?, defaultMsg: String?) {
                        cont.resumeWithException(RuntimeException(defaultMsg ?: "Seek failed"))
                    }
                })
            }
        }

    private suspend fun setVolumeInternal(service: UpnpModelService<*, *>, volume: Long): Unit =
        withContext(Dispatchers.IO) {
            suspendCoroutine { cont: Continuation<Unit> ->
                execute(object : SetVolume(service, volume) {
                    override fun success(invocation: ActionInvocation<*>?) { cont.resume(Unit) }
                    override fun failure(invocation: ActionInvocation<*>?, op: UpnpResponse?, defaultMsg: String?) {
                        cont.resumeWithException(RuntimeException(defaultMsg ?: "SetVolume failed"))
                    }
                })
            }
        }

    private suspend fun getPositionInfo(service: UpnpModelService<*, *>): PositionInfo =
        withContext(Dispatchers.IO) {
            suspendCoroutine { cont: Continuation<PositionInfo> ->
                execute(object : GetPositionInfo(service) {
                    override fun received(invocation: ActionInvocation<*>?, info: PositionInfo) {
                        cont.resume(info)
                    }
                    override fun failure(invocation: ActionInvocation<*>?, op: UpnpResponse?, defaultMsg: String?) {
                        cont.resumeWithException(RuntimeException(defaultMsg ?: "GetPositionInfo failed"))
                    }
                })
            }
        }

    private suspend fun getTransportInfo(service: UpnpModelService<*, *>): TransportInfo =
        withContext(Dispatchers.IO) {
            suspendCoroutine { cont: Continuation<TransportInfo> ->
                execute(object : GetTransportInfo(service) {
                    override fun received(invocation: ActionInvocation<*>?, info: TransportInfo) {
                        cont.resume(info)
                    }
                    override fun failure(invocation: ActionInvocation<*>?, op: UpnpResponse?, defaultMsg: String?) {
                        cont.resumeWithException(RuntimeException(defaultMsg ?: "GetTransportInfo failed"))
                    }
                })
            }
        }

    private fun lanAddressSignature(): String = runCatching {
        NetworkInterface.getNetworkInterfaces()?.toList().orEmpty()
            .filter { it.isUp && !it.isLoopback }
            .flatMap { nif -> nif.inetAddresses.toList().filterIsInstance<Inet4Address>().map { "${nif.name}/${it.hostAddress}" } }
            .sorted()
            .joinToString(",")
    }.getOrDefault("")

    /** Best-effort teardown, also for a service whose startup threw half way. */
    private fun teardown(service: UpnpService) {
        runCatching { service.registry?.removeListener(registryListener) }
        // shutdown() is a no-op unless startup() completed, so release the
        // parts a failed startup may already have created by hand.
        val wasRunning = runCatching { service.controlPoint != null }.getOrDefault(false)
        if (wasRunning) {
            runCatching { service.shutdown() }
        } else {
            runCatching { service.registry?.shutdown() }
            runCatching { service.router?.shutdown() }
            runCatching { service.configuration?.shutdown() }
        }
    }

    private fun formatHms(seconds: Long): String {
        val s = seconds.coerceAtLeast(0)
        val h = s / 3600
        val m = (s % 3600) / 60
        val sec = s % 60
        return "%d:%02d:%02d".format(h, m, sec)
    }
}
