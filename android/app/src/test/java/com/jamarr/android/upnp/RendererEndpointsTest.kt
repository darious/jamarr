package com.jamarr.android.upnp

import org.jupnp.model.meta.DeviceDetails
import org.jupnp.model.meta.RemoteDevice
import org.jupnp.model.meta.RemoteDeviceIdentity
import org.jupnp.model.meta.RemoteService
import org.jupnp.model.types.UDADeviceType
import org.jupnp.model.types.UDAServiceId
import org.jupnp.model.types.UDAServiceType
import org.jupnp.model.types.UDN
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.InetAddress
import java.net.URI
import java.net.URL

class RendererEndpointsTest {

    private fun service(type: String, path: String) = RemoteService(
        UDAServiceType(type),
        UDAServiceId(type),
        URI("/$path/desc.xml"),
        URI("/$path/control"),
        URI("/$path/event"),
    )

    private fun device(
        udn: String,
        type: String,
        services: List<RemoteService>,
        embedded: List<RemoteDevice> = emptyList(),
    ) = RemoteDevice(
        RemoteDeviceIdentity(
            UDN(udn),
            1800,
            URL("http://192.168.0.50:49152/desc.xml"),
            null,
            InetAddress.getByName("192.168.0.22"),
        ),
        UDADeviceType(type),
        DeviceDetails(udn),
        services.toTypedArray(),
        embedded.toTypedArray(),
    )

    private fun rendererServices(path: String) =
        listOf(service("AVTransport", "$path/avt"), service("RenderingControl", "$path/rc"))

    @Test
    fun plainRendererIsOneEndpointUnderItsOwnUdn() {
        val root = device("root-1", "MediaRenderer", rendererServices("r"))

        val endpoints = rendererEndpoints(root)

        assertEquals(listOf("root-1"), endpoints.map { it.udn })
        assertEquals("root-1", endpoints.single().rootUdn)
    }

    @Test
    fun embeddedRenderersEachGetTheirOwnUdnAndServices() {
        val zoneA = device("zone-a", "MediaRenderer", rendererServices("a"))
        val zoneB = device("zone-b", "MediaRenderer", rendererServices("b"))
        val root = device("root-1", "Basic", emptyList(), listOf(zoneA, zoneB))

        val endpoints = rendererEndpoints(root).associateBy { it.udn }

        assertEquals(setOf("zone-a", "zone-b"), endpoints.keys)
        assertTrue(endpoints.values.all { it.rootUdn == "root-1" })
        assertEquals(
            URI("/a/avt/control"),
            endpoints.getValue("zone-a").service(AV_TRANSPORT_ID)!!.controlURI,
        )
        assertEquals(
            URI("/b/avt/control"),
            endpoints.getValue("zone-b").service(AV_TRANSPORT_ID)!!.controlURI,
        )
        assertEquals(
            URI("/b/rc/control"),
            endpoints.getValue("zone-b").service(RENDERING_CONTROL_ID)!!.controlURI,
        )
    }

    @Test
    fun nestedEmbeddedRendererIsFound() {
        val inner = device("inner", "MediaRenderer", rendererServices("i"))
        val middle = device("middle", "Basic", emptyList(), listOf(inner))
        val root = device("root-1", "Basic", emptyList(), listOf(middle))

        assertEquals(listOf("inner"), rendererEndpoints(root).map { it.udn })
    }

    @Test
    fun rootServicesAreNotLentToAnEmbeddedEndpoint() {
        val embedded = device("emb", "MediaRenderer", listOf(service("AVTransport", "e/avt")))
        val root = device("root-1", "MediaRenderer", rendererServices("r"), listOf(embedded))

        val byUdn = rendererEndpoints(root).associateBy { it.udn }

        assertEquals(setOf("root-1", "emb"), byUdn.keys)
        assertNull("no RenderingControl of its own", byUdn.getValue("emb").service(RENDERING_CONTROL_ID))
        assertEquals(URI("/r/avt/control"), byUdn.getValue("root-1").service(AV_TRANSPORT_ID)!!.controlURI)
    }

    @Test
    fun deviceWithoutAvTransportIsNotAnEndpoint() {
        val root = device("root-1", "MediaRenderer", listOf(service("RenderingControl", "r/rc")))

        assertTrue(rendererEndpoints(root).isEmpty())
    }

    @Test
    fun indexReplacesAndRemovesEndpointsPerRoot() {
        val index = RendererEndpointIndex()
        val zoneA = device("zone-a", "MediaRenderer", rendererServices("a"))
        val zoneB = device("zone-b", "MediaRenderer", rendererServices("b"))
        val other = device("other", "MediaRenderer", rendererServices("o"))

        assertTrue(index.update(device("root-1", "Basic", emptyList(), listOf(zoneA, zoneB))).isEmpty())
        index.update(other)
        assertEquals(setOf("zone-a", "zone-b", "other"), index.all().map { it.udn }.toSet())

        // The root re-advertises with one zone gone.
        val zoneA2 = device("zone-a", "MediaRenderer", rendererServices("a2"))
        val gone = index.update(device("root-1", "Basic", emptyList(), listOf(zoneA2)))
        assertEquals(setOf("zone-b"), gone)
        assertSame(zoneA2, index["zone-a"]!!.device)

        assertEquals(setOf("zone-a"), index.removeRoot("root-1"))
        assertEquals(listOf("other"), index.all().map { it.udn })
    }
}
