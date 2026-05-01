package com.jamarr.android.upnp

import android.content.Context
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
import kotlinx.coroutines.withContext
import org.jupnp.UpnpService
import org.jupnp.UpnpServiceImpl
import org.jupnp.android.AndroidUpnpServiceConfiguration
import org.jupnp.controlpoint.ActionCallback
import org.jupnp.model.action.ActionInvocation
import org.jupnp.model.message.UpnpResponse
import org.jupnp.model.message.header.UDADeviceTypeHeader
import org.jupnp.model.meta.LocalDevice
import org.jupnp.model.meta.RemoteDevice
import org.jupnp.model.meta.RemoteService
import org.jupnp.model.meta.Service as UpnpModelService
import org.jupnp.model.types.UDADeviceType
import org.jupnp.model.types.UDAServiceId
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
import kotlin.coroutines.Continuation
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlin.coroutines.suspendCoroutine

private const val TAG = "UpnpDeviceController"

class UpnpDeviceController(private val appContext: Context) : DeviceRendererController {
    override val kind: String = "upnp"

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var upnpService: UpnpService? = null
    private var multicastLock: WifiManager.MulticastLock? = null
    private var pollJob: Job? = null

    private val _renderers = MutableStateFlow<List<DeviceRendererInfo>>(emptyList())
    override val renderers: StateFlow<List<DeviceRendererInfo>> = _renderers.asStateFlow()

    private val _state = MutableStateFlow(DeviceRendererPlaybackState())
    override val state: StateFlow<DeviceRendererPlaybackState> = _state.asStateFlow()

    private val devicesByUdn = mutableMapOf<String, RemoteDevice>()

    private val mediaRendererType = UDADeviceType("MediaRenderer")
    private val avTransportId = UDAServiceId("AVTransport")

    private fun looksLikeRenderer(device: RemoteDevice): Boolean {
        if (device.type.implementsVersion(mediaRendererType)) return true
        if (device.findService(avTransportId) != null) return true
        for (embedded in device.embeddedDevices.orEmpty()) {
            if (embedded.findService(avTransportId) != null) return true
        }
        return false
    }

    private val registryListener = object : DefaultRegistryListener() {
        override fun remoteDeviceAdded(registry: Registry, device: RemoteDevice) {
            if (looksLikeRenderer(device)) {
                Log.i(TAG, "renderer added: ${device.details?.friendlyName} (${device.type})")
                addDevice(device)
            }
        }
        override fun remoteDeviceUpdated(registry: Registry, device: RemoteDevice) {
            if (looksLikeRenderer(device)) addDevice(device)
        }
        override fun remoteDeviceRemoved(registry: Registry, device: RemoteDevice) {
            removeDevice(device.identity.udn.identifierString)
        }
        override fun localDeviceAdded(registry: Registry, device: LocalDevice) {}
        override fun localDeviceRemoved(registry: Registry, device: LocalDevice) {}
    }

    override fun start() {
        if (upnpService != null) return
        try {
            val wifi = appContext.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
            multicastLock = wifi?.createMulticastLock("jamarr-upnp")?.apply {
                setReferenceCounted(true)
                acquire()
            }
            val config = AndroidUpnpServiceConfiguration()
            val service = UpnpServiceImpl(config)
            service.startup()
            service.registry.addListener(registryListener)
            upnpService = service
            Log.i(TAG, "UPnP service started")
            // Initial searches; re-issue periodically to catch slow renderers.
            scope.launch {
                repeat(6) {
                    search()
                    delay(5_000)
                }
            }
        } catch (e: Throwable) {
            Log.e(TAG, "start failed", e)
        }
    }

    override fun stop() {
        pollJob?.cancel()
        pollJob = null
        try { upnpService?.shutdown() } catch (_: Throwable) {}
        upnpService = null
        multicastLock?.let { runCatching { it.release() } }
        multicastLock = null
        devicesByUdn.clear()
        _renderers.value = emptyList()
    }

    override fun search() {
        val cp = upnpService?.controlPoint ?: return
        cp.search()
        cp.search(UDADeviceTypeHeader(mediaRendererType))
    }

    private fun addDevice(device: RemoteDevice) {
        val udn = device.identity.udn.identifierString
        devicesByUdn[udn] = device
        publishRenderers()
    }

    private fun removeDevice(udn: String) {
        devicesByUdn.remove(udn)
        publishRenderers()
        if (_state.value.activeRendererId == "upnp:$udn") {
            stopPolling()
            _state.value = _state.value.copy(activeRendererId = null, isPlaying = false)
        }
    }

    private fun publishRenderers() {
        val list = devicesByUdn.values.map { d ->
            val udn = d.identity.udn.identifierString
            DeviceRendererInfo(
                rendererId = "upnp:$udn",
                kind = kind,
                name = d.details?.friendlyName ?: d.displayString ?: "Renderer",
                manufacturer = d.details?.manufacturerDetails?.manufacturer,
                modelName = d.details?.modelDetails?.modelName,
                ip = d.identity?.descriptorURL?.host,
            )
        }.sortedBy { it.name.lowercase() }
        if (list != _renderers.value) {
            Log.i(TAG, "renderers: count=${list.size} ${list.map { it.name }}")
            _renderers.value = list
        }
    }

    override fun selectRenderer(rendererId: String) {
        val udn = rendererId.removePrefix("upnp:")
        if (devicesByUdn[udn] == null) return
        _state.value = _state.value.copy(activeRendererId = "upnp:$udn")
        startPolling()
    }

    private fun activeDevice(): RemoteDevice? =
        _state.value.activeRendererId?.removePrefix("upnp:")?.let { devicesByUdn[it] }

    private fun avtService(): UpnpModelService<*, *>? =
        activeDevice()?.findService(UDAServiceId("AVTransport"))

    private fun rcService(): UpnpModelService<*, *>? =
        activeDevice()?.findService(UDAServiceId("RenderingControl"))

    override suspend fun playQueue(tracks: List<QueuedTrack>, startIndex: Int) {
        if (tracks.isEmpty()) return
        val idx = startIndex.coerceIn(0, tracks.lastIndex)
        _state.value = _state.value.copy(
            queue = tracks,
            currentIndex = idx,
            positionSeconds = 0.0,
            durationSeconds = tracks[idx].durationSeconds,
            isPlaying = true,
            transportState = "TRANSITIONING",
        )
        playTrackAt(idx)
    }

    private suspend fun playTrackAt(index: Int) {
        val track = _state.value.queue.getOrNull(index) ?: return
        val service = avtService() ?: run {
            Log.w(TAG, "No AVTransport service on active renderer")
            return
        }
        val didl = DidlLite.build(track)
        runCatching { setAvTransportUri(service, track.streamUrl, didl) }
            .onFailure { Log.w(TAG, "SetAVTransportURI failed: ${it.message}") }
        delay(300)
        runCatching { play(service) }
            .onFailure { Log.w(TAG, "Play failed: ${it.message}") }
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
        _state.value = s.copy(currentIndex = nextIdx, positionSeconds = 0.0,
            durationSeconds = s.queue[nextIdx].durationSeconds)
        playTrackAt(nextIdx)
    }

    override suspend fun previous() {
        val s = _state.value
        if (s.queue.isEmpty()) return
        val prevIdx = (s.currentIndex - 1).coerceAtLeast(0)
        if (prevIdx == s.currentIndex) return
        _state.value = s.copy(currentIndex = prevIdx, positionSeconds = 0.0,
            durationSeconds = s.queue[prevIdx].durationSeconds)
        playTrackAt(prevIdx)
    }

    override suspend fun jumpTo(index: Int) {
        val s = _state.value
        if (s.queue.isEmpty()) return
        val target = index.coerceIn(0, s.queue.lastIndex)
        _state.value = s.copy(currentIndex = target, positionSeconds = 0.0,
            durationSeconds = s.queue.getOrNull(target)?.durationSeconds ?: 0.0)
        playTrackAt(target)
    }

    private fun startPolling() {
        stopPolling()
        pollJob = scope.launch {
            delay(2000) // Renderer settle.
            var trackStartTime = System.currentTimeMillis()
            while (true) {
                val service = avtService() ?: break
                val pos = runCatching { getPositionInfo(service) }.getOrNull()
                val xport = runCatching { getTransportInfo(service) }.getOrNull()
                val transportState = xport?.currentTransportState
                val rel = pos?.trackElapsedSeconds?.toDouble() ?: 0.0
                val dur = pos?.trackDurationSeconds?.toDouble() ?: 0.0

                val current = _state.value
                val isPlaying = transportState == TransportState.PLAYING ||
                    transportState == TransportState.TRANSITIONING
                val stateName = transportState?.value ?: "STOPPED"

                _state.value = current.copy(
                    positionSeconds = if (rel > 0 || isPlaying) rel else current.positionSeconds,
                    durationSeconds = if (dur > 0) dur else current.durationSeconds,
                    isPlaying = isPlaying,
                    transportState = stateName,
                )

                val now = System.currentTimeMillis()
                if (transportState == TransportState.STOPPED &&
                    now - trackStartTime > 5_000 &&
                    current.queue.isNotEmpty() &&
                    current.currentIndex >= 0
                ) {
                    val nextIdx = current.currentIndex + 1
                    if (nextIdx <= current.queue.lastIndex) {
                        trackStartTime = now
                        _state.value = current.copy(
                            currentIndex = nextIdx,
                            positionSeconds = 0.0,
                            durationSeconds = current.queue[nextIdx].durationSeconds,
                        )
                        playTrackAt(nextIdx)
                    } else {
                        _state.value = current.copy(isPlaying = false)
                    }
                }

                delay(1000)
            }
        }
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

    private fun formatHms(seconds: Long): String {
        val s = seconds.coerceAtLeast(0)
        val h = s / 3600
        val m = (s % 3600) / 60
        val sec = s % 60
        return "%d:%02d:%02d".format(h, m, sec)
    }
}
