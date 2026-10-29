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


def _state_var(name: str, data_type: str = "string", events: bool = False, extra: str = "") -> str:
    send = "yes" if events else "no"
    return (
        f'<stateVariable sendEvents="{send}"><name>{name}</name>'
        f"<dataType>{data_type}</dataType>{extra}</stateVariable>"
    )


def _action(name: str, args: list[tuple[str, str, str]]) -> str:
    arg_xml = "".join(
        f"<argument><name>{a}</name><direction>{d}</direction>"
        f"<relatedStateVariable>{v}</relatedStateVariable></argument>"
        for a, d, v in args
    )
    return f"<action><name>{name}</name><argumentList>{arg_xml}</argumentList></action>"


def _scpd(actions: list[str], variables: list[str]) -> str:
    return f"""<?xml version="1.0"?>
<scpd xmlns="urn:schemas-upnp-org:service-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <actionList>{"".join(actions)}</actionList>
  <serviceStateTable>{"".join(variables)}</serviceStateTable>
</scpd>"""


# SCPDs with the evented state variables a real DMR declares, so the library
# can parse LastChange into them (served by FakeRequester(rich_scpd=True)).
AVT_SCPD = _scpd(
    [
        _action(
            "GetTransportInfo",
            [
                ("InstanceID", "in", "A_ARG_TYPE_InstanceID"),
                ("CurrentTransportState", "out", "TransportState"),
            ],
        ),
        _action(
            "Seek",
            [
                ("InstanceID", "in", "A_ARG_TYPE_InstanceID"),
                ("Unit", "in", "A_ARG_TYPE_SeekMode"),
                ("Target", "in", "A_ARG_TYPE_SeekTarget"),
            ],
        ),
        _action("Pause", [("InstanceID", "in", "A_ARG_TYPE_InstanceID")]),
        _action("Stop", [("InstanceID", "in", "A_ARG_TYPE_InstanceID")]),
    ],
    [
        _state_var("LastChange", events=True),
        _state_var("A_ARG_TYPE_InstanceID", "ui4"),
        _state_var("A_ARG_TYPE_SeekMode"),
        _state_var("A_ARG_TYPE_SeekTarget"),
        _state_var("CurrentTransportActions"),
        _state_var("TransportState"),
        _state_var("CurrentTrackURI"),
        _state_var("AVTransportURI"),
        _state_var("CurrentTrackDuration"),
        _state_var("CurrentTrackMetaData"),
    ],
)
RC_SCPD = _scpd(
    [
        _action(
            "GetVolume",
            [
                ("InstanceID", "in", "A_ARG_TYPE_InstanceID"),
                ("Channel", "in", "A_ARG_TYPE_Channel"),
                ("CurrentVolume", "out", "Volume"),
            ],
        )
    ],
    [
        _state_var("LastChange", events=True),
        _state_var("A_ARG_TYPE_InstanceID", "ui4"),
        _state_var("A_ARG_TYPE_Channel"),
        _state_var(
            "Volume",
            "ui2",
            extra="<allowedValueRange><minimum>0</minimum><maximum>{max_volume}</maximum>"
            "<step>1</step></allowedValueRange>",
        ),
        _state_var("Mute", "boolean"),
    ],
)


class FakeGena:
    """Device side of UPnP eventing: answers SUBSCRIBE/UNSUBSCRIBE.

    ``refuse`` (HTTP status) or ``offline`` make SUBSCRIBEs fail; ``forget``
    makes renewals of existing SIDs fail with 412 (the device rebooted and
    lost them), so the library falls back to a full SUBSCRIBE.
    """

    def __init__(self, timeout: int = 300) -> None:
        self.timeout = timeout
        self.refuse: int | None = None
        self.offline = False
        self.forget = False
        self.active: dict[str, str] = {}  # SID -> event URL
        self.calls: list[tuple[str, str, dict]] = []  # (method, url, headers)
        self._n = 0

    def sid_for(self, fragment: str) -> str:
        """Current SID of the subscription whose URL contains fragment."""
        matches = [sid for sid, url in self.active.items() if fragment in url]
        assert len(matches) == 1, (fragment, self.active)
        return matches[0]

    def count(self, method: str, renewal: bool | None = None) -> int:
        return sum(
            1
            for m, _url, headers in self.calls
            if m == method and (renewal is None or ("SID" in headers) == renewal)
        )

    def handle(self, http_request: HttpRequest) -> HttpResponse:
        from async_upnp_client.exceptions import UpnpConnectionError

        headers = dict(http_request.headers or {})
        self.calls.append((http_request.method, http_request.url, headers))
        if self.offline:
            raise UpnpConnectionError("device offline")
        if http_request.method == "UNSUBSCRIBE":
            self.active.pop(headers.get("SID"), None)
            return HttpResponse(200, {}, "")
        if self.refuse is not None:
            return HttpResponse(self.refuse, {}, "")
        sid = headers.get("SID")
        if sid is not None:  # renewal
            if self.forget or sid not in self.active:
                self.active.pop(sid, None)
                return HttpResponse(412, {}, "")
        else:
            self._n += 1
            sid = f"uuid:sid-{self._n}"
            self.active[sid] = http_request.url
        return HttpResponse(
            200,
            CaseInsensitiveDict({"SID": sid, "TIMEOUT": f"Second-{self.timeout}"}),
            "",
        )


class FakeRequester(UpnpRequester):
    """Serves registered descriptions; any */scpd.xml gets a minimal SCPD.

    ``rich_scpd=True`` serves AVTransport/RenderingControl SCPDs with their
    evented state variables instead. SUBSCRIBE/UNSUBSCRIBE go to ``gena``.
    SOAP POSTs are answered from ``soap[(control URL, action)]`` (a dict of
    output arguments); anything else gets a 500 UPnP fault.
    """

    def __init__(self, rich_scpd: bool = False, max_volume: int = 100) -> None:
        self.descriptions: dict[str, str] = {}
        self.delays: dict[str, float] = {}
        self.fetches: Counter = Counter()
        self.rich_scpd = rich_scpd
        self.max_volume = max_volume
        self.gena = FakeGena()
        self.soap: dict[tuple[str, str], dict[str, Any]] = {}
        self.soap_calls: list[tuple[str, str]] = []

    def _soap(self, http_request: HttpRequest) -> HttpResponse:
        from xml.sax.saxutils import escape

        headers = {k.lower(): v for k, v in dict(http_request.headers or {}).items()}
        service_type, _, action = headers.get("soapaction", "").strip('"').partition("#")
        self.soap_calls.append((http_request.url, action))
        outputs = self.soap.get((http_request.url, action))
        if outputs is None:
            fault = (
                '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
                "<s:Fault><faultcode>s:Client</faultcode><faultstring>UPnPError</faultstring>"
                '<detail><UPnPError xmlns="urn:schemas-upnp-org:control-1-0">'
                "<errorCode>401</errorCode><errorDescription>Invalid Action</errorDescription>"
                "</UPnPError></detail></s:Fault></s:Body></s:Envelope>"
            )
            return HttpResponse(500, {}, fault)
        args = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in outputs.items())
        body = (
            '<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{action}Response xmlns:u="{service_type}">{args}</u:{action}Response>'
            "</s:Body></s:Envelope>"
        )
        return HttpResponse(200, {}, body)

    async def async_http_request(self, http_request: HttpRequest) -> HttpResponse:
        url = http_request.url
        if http_request.method in ("SUBSCRIBE", "UNSUBSCRIBE"):
            return self.gena.handle(http_request)
        if http_request.method == "POST":
            return self._soap(http_request)
        self.fetches[url] += 1
        delay = self.delays.get(url)
        if delay:
            await asyncio.sleep(delay)
        if url in self.descriptions:
            return HttpResponse(200, {}, self.descriptions[url])
        if url.endswith("/scpd.xml"):
            if self.rich_scpd and url.endswith("/AVTransport/scpd.xml"):
                return HttpResponse(200, {}, AVT_SCPD)
            if self.rich_scpd and url.endswith("/RenderingControl/scpd.xml"):
                rc = RC_SCPD.replace("{max_volume}", str(self.max_volume))
                return HttpResponse(200, {}, rc)
            return HttpResponse(200, {}, _SCPD)
        return HttpResponse(404, {}, "")


class FakeNotifyServer:
    """Stands in for AiohttpNotifyServer: a real UpnpEventHandler, no socket."""

    def __init__(self, requester: UpnpRequester, source: tuple[str, int], fail: bool = False):
        from async_upnp_client.event_handler import UpnpEventHandler

        self.source = source
        self.fail = fail
        self.started = False
        self.stopped = False
        self.event_handler = UpnpEventHandler(self, requester)

    @property
    def callback_url(self) -> str:
        return f"http://{self.source[0]}:{self.source[1] or 40000}/notify"

    async def async_start_server(self) -> None:
        if self.fail:
            raise OSError(98, "Address already in use")
        self.started = True

    async def async_stop_server(self) -> None:
        await self.event_handler.async_unsubscribe_all()
        self.stopped = True


def last_change(namespace: str, **values: Any) -> str:
    """A LastChange document for InstanceID 0 (namespace: "AVT" or "RCS").

    A dict value lists channels, e.g. ``Volume={"Master": 30, "LF": 10}``.
    """
    from xml.sax.saxutils import quoteattr

    parts = []
    for name, value in values.items():
        if isinstance(value, dict):
            for channel, channel_value in value.items():
                parts.append(
                    f"<{name} channel={quoteattr(channel)} val={quoteattr(str(channel_value))}/>"
                )
        else:
            parts.append(f"<{name} val={quoteattr(str(value))}/>")
    return (
        f'<Event xmlns="urn:schemas-upnp-org:metadata-1-0/{namespace}/">'
        f'<InstanceID val="0">{"".join(parts)}</InstanceID></Event>'
    )


async def send_notify(handler, sid: str, last_change_xml: str) -> int:
    """Deliver a LastChange NOTIFY through a real UpnpEventHandler."""
    from xml.sax.saxutils import escape

    body = (
        '<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0"><e:property>'
        f"<LastChange>{escape(last_change_xml)}</LastChange>"
        "</e:property></e:propertyset>"
    )
    headers = CaseInsensitiveDict(
        {"NT": "upnp:event", "NTS": "upnp:propchange", "SID": sid, "SEQ": "0"}
    )
    status = await handler.handle_notify(HttpRequest("NOTIFY", "/notify", headers, body))
    return int(status)


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
