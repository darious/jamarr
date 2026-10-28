package com.jamarr.android.upnp

import org.jupnp.model.meta.RemoteDevice
import org.jupnp.model.meta.RemoteService

/** Service type names, matched in any namespace and at any version. */
internal const val AV_TRANSPORT = "AVTransport"
internal const val RENDERING_CONTROL = "RenderingControl"

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
    fun service(type: String): RemoteService? = ownService(device, type)
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
        if (ownService(device, AV_TRANSPORT) != null) {
            out += RendererEndpoint(device.identity.udn.identifierString, rootUdn, device)
        }
        device.embeddedDevices.orEmpty().forEach(::walk)
    }
    walk(root)
    return out.distinctBy { it.udn }
}

/**
 * The device's own service of type [type] (embedded devices not searched).
 * Matched on the service *type*, as the server does: serviceIds are often
 * non-standard (`AVTransport1`, vendor ids). The serviceId is only a fallback
 * for the odd device with a mangled type.
 */
internal fun ownService(device: RemoteDevice, type: String): RemoteService? {
    val services = device.services.orEmpty()
    return services.firstOrNull { it.serviceType?.type == type }
        ?: services.firstOrNull { it.serviceId?.id == type }
}

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
