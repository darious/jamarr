package com.jamarr.android.upnp

import org.jupnp.model.meta.RemoteDevice
import org.jupnp.model.meta.RemoteService
import org.jupnp.model.types.ServiceId
import org.jupnp.model.types.UDAServiceId

internal val AV_TRANSPORT_ID = UDAServiceId("AVTransport")
internal val RENDERING_CONTROL_ID = UDAServiceId("RenderingControl")

/**
 * One playable renderer: a device in a root's tree that carries its own
 * AVTransport. Keyed by its own UDN, which is not the root's when it is an
 * embedded device.
 */
data class RendererEndpoint(
    val udn: String,
    val rootUdn: String,
    val device: RemoteDevice,
) {
    /** The endpoint's own service, never one from a sibling or child device. */
    fun service(id: ServiceId): RemoteService? = ownService(device, id)
}

/**
 * The endpoints of one root device, root first and then embedded devices
 * depth first. jUPnP's `Device.findService` searches the whole tree and picks
 * from a HashSet, so a root with two embedded renderers would hand back
 * either one's AVTransport; this keeps each endpoint to its own services.
 */
fun rendererEndpoints(root: RemoteDevice): List<RendererEndpoint> {
    val rootUdn = root.identity.udn.identifierString
    val out = mutableListOf<RendererEndpoint>()
    fun walk(device: RemoteDevice) {
        if (ownService(device, AV_TRANSPORT_ID) != null) {
            out += RendererEndpoint(device.identity.udn.identifierString, rootUdn, device)
        }
        device.embeddedDevices.orEmpty().forEach(::walk)
    }
    walk(root)
    return out.distinctBy { it.udn }
}

internal fun ownService(device: RemoteDevice, id: ServiceId): RemoteService? =
    device.services.orEmpty().firstOrNull { it.serviceId == id }

/**
 * Endpoints by UDN, updated per root device as the registry reports it.
 * Thread-safe: jUPnP calls the registry listener from its own threads.
 */
class RendererEndpointIndex {
    private val byUdn = linkedMapOf<String, RendererEndpoint>()

    /** Replaces the endpoints of [root]; returns the UDNs that went away. */
    @Synchronized
    fun update(root: RemoteDevice): Set<String> {
        val rootUdn = root.identity.udn.identifierString
        val fresh = rendererEndpoints(root)
        val gone = byUdn.values.filter { it.rootUdn == rootUdn }.map { it.udn }.toMutableSet()
        for (endpoint in fresh) {
            gone.remove(endpoint.udn)
            byUdn[endpoint.udn] = endpoint
        }
        gone.forEach { byUdn.remove(it) }
        return gone
    }

    /** Drops every endpoint of the root [rootUdn]; returns their UDNs. */
    @Synchronized
    fun removeRoot(rootUdn: String): Set<String> {
        val gone = byUdn.values.filter { it.rootUdn == rootUdn }.map { it.udn }.toSet()
        gone.forEach { byUdn.remove(it) }
        return gone
    }

    @Synchronized
    operator fun get(udn: String): RendererEndpoint? = byUdn[udn]

    @Synchronized
    fun all(): List<RendererEndpoint> = byUdn.values.toList()

    @Synchronized
    fun clear() = byUdn.clear()
}
