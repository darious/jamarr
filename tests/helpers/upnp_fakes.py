"""In-memory UPnP devices for discovery tests: no sockets, no real devices.

``FakeRequester`` serves description/SCPD XML to the real async_upnp_client
factory, so tests exercise the library's actual device-tree parsing.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from async_upnp_client.client import UpnpRequester
from async_upnp_client.const import HttpRequest, HttpResponse
from async_upnp_client.utils import CaseInsensitiveDict

MEDIA_RENDERER = "urn:schemas-upnp-org:device:MediaRenderer:1"
MEDIA_SERVER = "urn:schemas-upnp-org:device:MediaServer:1"
BASIC_DEVICE = "urn:schemas-upnp-org:device:Basic:1"
AVTRANSPORT = "urn:schemas-upnp-org:service:AVTransport:1"
RENDERING_CONTROL = "urn:schemas-upnp-org:service:RenderingControl:1"
CONNECTION_MANAGER = "urn:schemas-upnp-org:service:ConnectionManager:1"
RENDERER_SERVICES = (AVTRANSPORT, RENDERING_CONTROL, CONNECTION_MANAGER)

_SCPD = """<?xml version="1.0"?>
<scpd xmlns="urn:schemas-upnp-org:service-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <actionList/>
  <serviceStateTable/>
</scpd>"""


def service_xml(service_type: str, prefix: str) -> str:
    short = service_type.split(":")[-2]
    return f"""
      <service>
        <serviceType>{service_type}</serviceType>
        <serviceId>urn:upnp-org:serviceId:{short}</serviceId>
        <SCPDURL>/{prefix}/{short}/scpd.xml</SCPDURL>
        <controlURL>/{prefix}/{short}/control</controlURL>
        <eventSubURL>/{prefix}/{short}/event</eventSubURL>
      </service>"""


def device_xml(
    udn: str,
    name: str,
    device_type: str = MEDIA_RENDERER,
    services: tuple[str, ...] = RENDERER_SERVICES,
    children: tuple[str, ...] = (),
) -> str:
    prefix = udn.replace("uuid:", "")
    service_list = "".join(service_xml(s, prefix) for s in services)
    child_list = f"<deviceList>{''.join(children)}</deviceList>" if children else ""
    return f"""
    <device>
      <deviceType>{device_type}</deviceType>
      <friendlyName>{name}</friendlyName>
      <manufacturer>Acme</manufacturer>
      <modelName>Model {name}</modelName>
      <UDN>{udn}</UDN>
      <iconList>
        <icon><mimetype>image/png</mimetype><width>120</width><height>120</height>
        <depth>24</depth><url>/{prefix}/icon.png</url></icon>
      </iconList>
      <serviceList>{service_list}</serviceList>
      {child_list}
    </device>"""


def description(root_device: str) -> str:
    return f"""<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  {root_device}
</root>"""


class FakeRequester(UpnpRequester):
    """Serves registered descriptions; any */scpd.xml gets a minimal SCPD."""

    def __init__(self) -> None:
        self.descriptions: dict[str, str] = {}
        self.delays: dict[str, float] = {}
        self.fetches: Counter = Counter()

    async def async_http_request(self, http_request: HttpRequest) -> HttpResponse:
        url = http_request.url
        self.fetches[url] += 1
        delay = self.delays.get(url)
        if delay:
            await asyncio.sleep(delay)
        if url in self.descriptions:
            return HttpResponse(200, {}, self.descriptions[url])
        if url.endswith("/scpd.xml"):
            return HttpResponse(200, {}, _SCPD)
        return HttpResponse(404, {}, "")


def search_reply(
    location: str,
    udn: str,
    st: str = MEDIA_RENDERER,
    bootid: str | None = None,
    configid: str | None = None,
    max_age: int | None = 1800,
) -> CaseInsensitiveDict:
    headers: dict[str, Any] = {
        "LOCATION": location,
        "ST": st,
        "USN": f"{udn}::{st}",
        "_udn": udn,
    }
    if bootid is not None:
        headers["BOOTID.UPNP.ORG"] = bootid
    if configid is not None:
        headers["CONFIGID.UPNP.ORG"] = configid
    if max_age is not None:
        headers["CACHE-CONTROL"] = f"max-age={max_age}"
    return CaseInsensitiveDict(headers)


def advertisement(
    location: str,
    udn: str,
    nts: str = "ssdp:alive",
    nt: str = MEDIA_RENDERER,
    bootid: str | None = None,
) -> CaseInsensitiveDict:
    headers: dict[str, Any] = {
        "LOCATION": location,
        "NT": nt,
        "NTS": nts,
        "USN": f"{udn}::{nt}",
        "_udn": udn,
        "CACHE-CONTROL": "max-age=1800",
    }
    if bootid is not None:
        headers["BOOTID.UPNP.ORG"] = bootid
    return CaseInsensitiveDict(headers)


class FakeSsdp:
    """Stands in for UPnPDiscovery._search_impl."""

    def __init__(self) -> None:
        self.multicast_replies: list[CaseInsensitiveDict] = []
        self.unicast_replies: dict[str, list[CaseInsensitiveDict]] = {}
        self.calls: list[dict[str, Any]] = []
        self.delay = 0.0

    async def __call__(self, targets, timeout, on_headers, target_addr=None, transmissions=3):
        self.calls.append(
            {"targets": tuple(targets), "target_addr": target_addr, "transmissions": transmissions}
        )
        if self.delay:
            await asyncio.sleep(self.delay)
        if target_addr is None:
            replies = list(self.multicast_replies)
        else:
            replies = list(self.unicast_replies.get(target_addr[0], []))
        for headers in replies:
            on_headers(headers)

    @property
    def multicast_calls(self) -> int:
        return sum(1 for c in self.calls if c["target_addr"] is None)


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
