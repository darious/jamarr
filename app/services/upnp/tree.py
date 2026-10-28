"""Device-tree helpers: find every playable endpoint in a UPnP description.

A UPnP description is a tree: a root device plus nested ``deviceList``
entries. Renderers are often *embedded* (a NAS or AV receiver whose root is a
generic device, with a MediaRenderer child), and multi-zone devices embed one
renderer per zone. Each node has its own UDN and its own services, so each
node with an AVTransport service is a separate endpoint.
"""

from __future__ import annotations

from typing import Iterator
from xml.etree import ElementTree as ET

from async_upnp_client.client import UpnpDevice, UpnpService
from async_upnp_client.client_factory import UpnpFactory
from async_upnp_client.const import NS
from async_upnp_client.profiles.dlna import DmrDevice

AVTRANSPORT_SERVICE_PREFIX = "urn:schemas-upnp-org:service:AVTransport:"
RENDERING_CONTROL_SERVICE_PREFIX = "urn:schemas-upnp-org:service:RenderingControl:"


class TreeKeepingUpnpFactory(UpnpFactory):
    """UpnpFactory that keeps *every* embedded device.

    ``UpnpDevice.embedded_devices`` is a dict keyed by device type, so a
    description embedding two devices of the same type (two MediaRenderer
    zones) loses all but the last. This override builds the device exactly as
    the library does and additionally records the full, ordered child list on
    ``device.jamarr_embedded``.
    """

    async def _async_create_device(self, device_el: ET.Element, description_url: str) -> UpnpDevice:
        device_info = self._parse_device_el(device_el, description_url)

        services = []
        for service_desc_el in device_el.findall("./device:serviceList/device:service", NS):
            service = await self._async_create_service(service_desc_el, description_url)
            if service is not None:
                services.append(service)

        embedded_devices = []
        for embedded_device_el in device_el.findall("./device:deviceList/device:device", NS):
            embedded_devices.append(await self._async_create_device(embedded_device_el, description_url))

        device = UpnpDevice(
            self.requester,
            device_info,
            services,
            embedded_devices,
            self._on_pre_receive_device_spec,
            self._on_post_receive_device_spec,
        )
        device.jamarr_embedded = list(embedded_devices)
        return device


def _children(node: UpnpDevice) -> list[UpnpDevice]:
    kept = getattr(node, "jamarr_embedded", None)
    if kept is not None:
        return list(kept)
    return list(node.embedded_devices.values())


def iter_device_tree(root: UpnpDevice) -> Iterator[UpnpDevice]:
    """Depth-first walk over root and all (nested) embedded devices."""
    stack = [root]
    seen: set[int] = set()
    while stack:
        node = stack.pop(0)
        if id(node) in seen:
            continue
        seen.add(id(node))
        yield node
        stack[0:0] = _children(node)


def _own_service(node: UpnpDevice, type_prefix: str) -> UpnpService | None:
    """A service on this node only (``find_service`` would descend into children)."""
    for service in node.services.values():
        if service.service_type.startswith(type_prefix):
            return service
    return None


def avtransport_service(node: UpnpDevice) -> UpnpService | None:
    return _own_service(node, AVTRANSPORT_SERVICE_PREFIX)


def rendering_control_service(node: UpnpDevice) -> UpnpService | None:
    return _own_service(node, RENDERING_CONTROL_SERVICE_PREFIX)


def playable_endpoints(root: UpnpDevice) -> list[UpnpDevice]:
    """Every node in the tree that exposes its own AVTransport service."""
    return [node for node in iter_device_tree(root) if avtransport_service(node) is not None]


def make_dmr(node: UpnpDevice) -> DmrDevice:
    """Wrap one endpoint node in a DmrDevice bound to *that* node.

    DmrDevice picks the first MediaRenderer in ``node.all_devices`` (node
    first), so passing the endpoint itself scopes it correctly. A node with an
    AVTransport but a non-standard device type would make DmrDevice refuse it;
    widen the accepted types for that instance only.
    """
    if node.device_type in DmrDevice.DEVICE_TYPES:
        return DmrDevice(node, event_handler=None)
    dmr = DmrDevice.__new__(DmrDevice)
    dmr.DEVICE_TYPES = [node.device_type]
    DmrDevice.__init__(dmr, node, event_handler=None)
    return dmr
