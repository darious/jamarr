"""UPnP discovery reliability (issue #315): coverage, liveness, caching, manual add.

Everything runs against in-memory fakes: descriptions are served to the real
async_upnp_client factory by FakeRequester, SSDP is FakeSsdp, HTTP probes and
DB writes are stubbed. Nothing touches the network.
"""

from __future__ import annotations

import asyncio
import ipaddress
import time

import pytest

from app.services.renderer.contracts import RendererDevice
from app.services.renderer.orchestrator import RendererOrchestrator
from app.services.renderer.registry import RendererRegistry
from app.services.renderer.upnp_backend import UpnpRendererBackend
from app.services.upnp import discovery as discovery_module
from app.services.upnp import network as network_module
from app.services.upnp.discovery import (
    LIVENESS_GRACE_SECONDS,
    SEARCH_TARGETS,
    SUBNET_CONCURRENCY,
)
from app.services.upnp.tree import TreeKeepingUpnpFactory
from app.upnp import UPnPManager
from tests.helpers.upnp_fakes import (
    AVTRANSPORT,
    BASIC_DEVICE,
    CONNECTION_MANAGER,
    MEDIA_RENDERER,
    MEDIA_SERVER,
    FakeClock,
    FakeRequester,
    FakeSsdp,
    advertisement,
    description,
    device_xml,
    search_reply,
)

LOC_A = "http://192.0.2.10:49152/description.xml"
LOC_B = "http://192.0.2.11:8080/description.xml"
UDN_A = "uuid:aaaa-0001"
UDN_B = "uuid:bbbb-0002"


class Harness:
    """A real UPnPManager + UPnPDiscovery wired to fakes."""

    def __init__(self) -> None:
        self.requester = FakeRequester()
        self.ssdp = FakeSsdp()
        self.clock = FakeClock()
        self.probe_results: dict[str, bool] = {}
        self.probes: list[str] = []
        self.saved: list[dict] = []
        self.persisted: list[tuple[list[str], bool]] = []
        self.protocol_queries: list[str] = []
        self.sink_entries: list[str] = ["http-get:*:audio/flac:*"]
        self.migrations: list[tuple[str, str]] = []

        manager = UPnPManager()
        manager.source_ip = None
        manager.local_ip = "192.0.2.2"

        async def ensure_session() -> None:
            manager._factory = manager._factory or TreeKeepingUpnpFactory(self.requester)

        async def save_renderer(info: dict) -> None:
            self.saved.append(dict(info))

        async def cache_icon(_udn, _icon) -> bool:
            return False

        async def existing_mimes(_udn):
            return None

        async def existing_protocol_info(_udn):
            return None

        async def protocols(udn, dmr=None):
            self.protocol_queries.append(udn)
            return list(self.sink_entries)

        manager._ensure_session = ensure_session
        manager.save_renderer = save_renderer
        manager._cache_renderer_icon = cache_icon
        manager._existing_mime_types = existing_mimes
        manager._existing_protocol_info = existing_protocol_info
        manager.get_sink_protocol_info = protocols

        async def migrate(old_udn, new_udn):
            self.migrations.append((old_udn, new_udn))
            manager.renderers.pop(old_udn, None)
            manager.dmr_devices.pop(old_udn, None)

        manager.migrate_renderer_udn = migrate
        self.manager = manager

        disc = manager.discovery
        disc._search_impl = self.ssdp
        disc._clock = self.clock

        async def probe(url: str, _timeout: float) -> bool:
            self.probes.append(url)
            return self.probe_results.get(url, False)

        async def persist(udns, available) -> None:
            self.persisted.append((sorted(udns), available))

        disc._probe_impl = probe
        disc._persist_availability = persist
        self.discovery = disc

    def serve(self, location: str, root_xml: str) -> None:
        self.requester.descriptions[location] = description(root_xml)

    def fetches(self, location: str) -> int:
        return self.requester.fetches[location]

    def available_udns(self) -> set[str]:
        return {r["udn"] for r in self.discovery.available_renderers()}


@pytest.fixture
def h() -> Harness:
    return Harness()


# --------------------------------------------------------------- search targets


@pytest.mark.asyncio
async def test_searches_renderer_device_and_avtransport_service(h):
    await h.discovery.discover(timeout=0)
    assert h.ssdp.calls[0]["targets"] == SEARCH_TARGETS
    assert AVTRANSPORT in SEARCH_TARGETS and MEDIA_RENDERER in SEARCH_TARGETS


@pytest.mark.asyncio
async def test_service_only_reply_is_registered(h):
    """A device answering only the AVTransport service ST is still found."""
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A, st=AVTRANSPORT)]

    found = await h.discovery.discover(timeout=0)

    assert [r["udn"] for r in found] == [UDN_A]
    info = h.manager.renderers[UDN_A]
    assert info["control_url"] == "http://192.0.2.10:49152/aaaa-0001/AVTransport/control"
    assert info["supported_mime_types"] == "audio/flac"
    assert info["sink_protocol_info"] == ["http-get:*:audio/flac:*"]


@pytest.mark.asyncio
async def test_hydration_keeps_complete_protocol_info(h):
    """Full Sink entries are kept verbatim; the MIME list is derived from them."""
    h.sink_entries = [
        "http-get:*:audio/x-flac:*",
        "http-get:*:audio/mpeg:DLNA.ORG_PN=MP3;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
        "http-get:*:audio/L16;rate=44100;channels=2:DLNA.ORG_PN=LPCM",
        "http-get:*:*:*",
    ]
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A)]

    await h.discovery.discover(timeout=0)

    info = h.manager.renderers[UDN_A]
    assert info["sink_protocol_info"] == h.sink_entries
    assert info["supported_mime_types"] == "audio/l16,audio/mpeg,audio/x-flac"
    assert h.saved[-1]["sink_protocol_info"] == h.sink_entries
    diag = h.manager.protocol_diagnostics()[UDN_A]
    assert diag["sink_protocol_info"][1]["dlna"]["PN"] == "MP3"
    assert diag["sink_protocol_info"][2]["mime_params"] == {"rate": "44100", "channels": "2"}


@pytest.mark.asyncio
async def test_hydration_keeps_saved_protocol_info_when_device_does_not_answer(h):
    h.sink_entries = []

    async def saved_entries(_udn):
        return ["http-get:*:audio/flac:*"]

    async def saved_mimes(_udn):
        return "audio/flac"

    h.manager._existing_protocol_info = saved_entries
    h.manager._existing_mime_types = saved_mimes
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A)]

    await h.discovery.discover(timeout=0)

    info = h.manager.renderers[UDN_A]
    assert info["sink_protocol_info"] == ["http-get:*:audio/flac:*"]
    assert info["supported_mime_types"] == "audio/flac"


@pytest.mark.asyncio
async def test_unrelated_search_target_is_ignored_without_fetching(h):
    h.serve(LOC_A, device_xml(UDN_A, "NAS", device_type=MEDIA_SERVER, services=(CONNECTION_MANAGER,)))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A, st=MEDIA_SERVER)]

    assert await h.discovery.discover(timeout=0) == []
    assert h.fetches(LOC_A) == 0


@pytest.mark.asyncio
async def test_renderer_without_avtransport_not_registered_and_not_refetched(h):
    h.serve(LOC_A, device_xml(UDN_A, "Odd", services=(CONNECTION_MANAGER,)))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A)]

    assert await h.discovery.discover(timeout=0) == []
    await h.discovery.discover(timeout=0)

    assert UDN_A not in h.manager.renderers
    assert h.fetches(LOC_A) == 1


@pytest.mark.asyncio
async def test_search_burst_retransmits_each_target(monkeypatch):
    sent: list[str] = []

    class FakeSearchListener:
        def __init__(self, callback, source, target, timeout):
            self.search_target = None

        async def async_start(self):
            pass

        def async_search(self):
            sent.append(self.search_target)

        def async_stop(self):
            pass

    monkeypatch.setattr(discovery_module, "SsdpSearchListener", FakeSearchListener)
    monkeypatch.setattr(discovery_module, "SEARCH_INTERVAL_SECONDS", 0.01)
    disc = discovery_module.UPnPDiscovery(UPnPManager())

    started = time.monotonic()
    await disc._ssdp_search(SEARCH_TARGETS, 0.05, lambda _h: None)

    assert sent == list(SEARCH_TARGETS) * discovery_module.SEARCH_TRANSMISSIONS
    assert time.monotonic() - started < 2.0  # bounded


@pytest.mark.asyncio
async def test_overlapping_scans_share_one_burst(h):
    h.ssdp.delay = 0.05
    await asyncio.gather(h.discovery.discover(timeout=0), h.discovery.discover(timeout=0))
    assert h.ssdp.multicast_calls == 1


# --------------------------------------------------------------- embedded devices


@pytest.mark.asyncio
async def test_embedded_renderer_under_non_renderer_root(h):
    child = device_xml(UDN_B, "Receiver Zone")
    h.serve(LOC_A, device_xml(UDN_A, "Receiver", device_type=BASIC_DEVICE, services=(), children=(child,)))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_B)]

    found = await h.discovery.discover(timeout=0)

    assert [r["udn"] for r in found] == [UDN_B]
    assert UDN_A not in h.manager.renderers
    assert h.manager.renderers[UDN_B]["control_url"].endswith("/bbbb-0002/AVTransport/control")
    dmr = h.manager.dmr_devices[UDN_B]
    assert dmr.device.udn == UDN_B and dmr.profile_device.udn == UDN_B


@pytest.mark.asyncio
async def test_two_embedded_renderers_each_registered_from_one_fetch(h):
    zone1 = device_xml("uuid:zone-1", "Zone 1")
    zone2 = device_xml("uuid:zone-2", "Zone 2")
    h.serve(LOC_A, device_xml(UDN_A, "Amp", device_type=BASIC_DEVICE, services=(), children=(zone1, zone2)))
    h.ssdp.multicast_replies = [
        search_reply(LOC_A, "uuid:zone-1"),
        search_reply(LOC_A, "uuid:zone-2"),
        search_reply(LOC_A, "uuid:zone-1", st=AVTRANSPORT),
    ]

    found = await h.discovery.discover(timeout=0)

    assert sorted(r["udn"] for r in found) == ["uuid:zone-1", "uuid:zone-2"]
    assert h.fetches(LOC_A) == 1
    urls = {h.manager.renderers[u]["control_url"] for u in ("uuid:zone-1", "uuid:zone-2")}
    assert len(urls) == 2
    assert h.manager.dmr_devices["uuid:zone-1"] is not h.manager.dmr_devices["uuid:zone-2"]


@pytest.mark.asyncio
async def test_root_renderer_with_embedded_renderer_registers_both(h):
    child = device_xml(UDN_B, "Second Output")
    h.serve(LOC_A, device_xml(UDN_A, "Main", children=(child,)))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A)]

    found = await h.discovery.discover(timeout=0)

    assert sorted(r["udn"] for r in found) == sorted([UDN_A, UDN_B])
    assert h.manager.dmr_devices[UDN_A].device.udn == UDN_A
    assert h.manager.dmr_devices[UDN_B].device.udn == UDN_B


# --------------------------------------------------------------- duplicates & caching


@pytest.mark.asyncio
async def test_duplicate_advertisements_hydrate_once(h):
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [
        search_reply(LOC_A, UDN_A),
        search_reply(LOC_A, UDN_A, st=AVTRANSPORT),
        search_reply(LOC_A, UDN_A),
    ]
    await h.discovery.discover(timeout=0)
    await h.discovery._on_advertisement(advertisement(LOC_A, UDN_A))
    await h.discovery._on_advertisement(advertisement(LOC_A, UDN_A, nt=AVTRANSPORT))

    assert h.fetches(LOC_A) == 1
    assert len(h.saved) == 1
    assert h.discovery.hydration_count == 1


@pytest.mark.asyncio
async def test_unchanged_device_is_not_rehydrated_each_scan(h):
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A, bootid="1", configid="7")]

    for _ in range(3):
        h.clock.advance(30)
        await h.discovery.discover(timeout=0)

    assert h.discovery.hydration_count == 1
    assert h.protocol_queries == [UDN_A]
    assert len(h.saved) == 1
    record = h.discovery._locations[LOC_A]
    assert record.last_seen == h.clock.now  # liveness still bumped


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    [{"bootid": "2", "configid": "7"}, {"bootid": "1", "configid": "8"}],
    ids=["bootid", "configid"],
)
async def test_changed_bootid_or_configid_rehydrates(h, changed):
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A, bootid="1", configid="7")]
    await h.discovery.discover(timeout=0)

    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A, **changed)]
    await h.discovery.discover(timeout=0)
    await h.discovery.discover(timeout=0)

    assert h.discovery.hydration_count == 2


@pytest.mark.asyncio
async def test_changed_location_rehydrates_and_drops_old_record(h):
    new_loc = "http://192.0.2.99:49152/description.xml"
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.serve(new_loc, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A)]
    await h.discovery.discover(timeout=0)

    h.ssdp.multicast_replies = [search_reply(new_loc, UDN_A)]
    await h.discovery.discover(timeout=0)

    assert h.discovery.hydration_count == 2
    assert h.manager.renderers[UDN_A]["location"] == new_loc
    assert h.manager.renderers[UDN_A]["ip"] == "192.0.2.99"
    assert LOC_A not in h.discovery._locations


@pytest.mark.asyncio
async def test_explicit_refresh_rehydrates(h):
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A)]
    await h.discovery.discover(timeout=0)
    await h.discovery.discover(timeout=0, refresh=True)
    assert h.discovery.hydration_count == 2


@pytest.mark.asyncio
async def test_concurrent_hydrations_of_one_url_share_a_fetch(h):
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.requester.delays[LOC_A] = 0.05

    results = await asyncio.gather(*(h.discovery.hydrate(LOC_A) for _ in range(5)))

    assert h.fetches(LOC_A) == 1
    assert all(r and r[0]["udn"] == UDN_A for r in results)


@pytest.mark.asyncio
async def test_slow_descriptor_does_not_block_others(h, monkeypatch):
    monkeypatch.setattr(discovery_module, "HYDRATE_DEADLINE_SECONDS", 0.3)
    h.serve(LOC_A, device_xml(UDN_A, "Slow TV"))
    h.serve(LOC_B, device_xml(UDN_B, "Fast Speaker"))
    h.requester.delays[LOC_A] = 5
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A), search_reply(LOC_B, UDN_B)]

    started = time.monotonic()
    found = await h.discovery.discover(timeout=0)
    elapsed = time.monotonic() - started

    assert [r["udn"] for r in found] == [UDN_B]
    assert elapsed < 2.0  # the deadline, not the 5 s device, bounds the scan
    assert h.discovery._failure_state[LOC_A]["failures"] == 1
    assert h.discovery.diagnostics()["descriptor_failures"][0]["location"] == LOC_A


@pytest.mark.asyncio
async def test_failure_cooldown_still_applies(h):
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A)]  # description 404s
    await h.discovery.discover(timeout=0)
    await h.discovery.discover(timeout=0)
    assert h.fetches(LOC_A) == 1
    assert h.discovery.diagnostics()["cooldowns"][0]["location"] == LOC_A


# --------------------------------------------------------------- liveness


@pytest.mark.asyncio
async def test_byebye_marks_unavailable_but_keeps_metadata(h, monkeypatch):
    monkeypatch.setattr(discovery_module, "BYEBYE_PROBE_DELAY_SECONDS", 0)
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A)]
    await h.discovery.discover(timeout=0)

    await h.discovery._on_byebye(advertisement(LOC_A, UDN_A, nts="ssdp:byebye"))
    await asyncio.gather(*h.discovery._probe_tasks.values())

    assert h.available_udns() == set()
    assert h.manager.renderers[UDN_A]["friendly_name"] == "Kitchen"  # metadata kept
    assert h.discovery.is_available(UDN_A) is False
    assert h.persisted == [([UDN_A], False)]
    assert await h.manager.get_renderers() == []
    transitions = h.discovery.diagnostics()["transitions"]
    assert transitions[-1]["available"] is False

    # Re-alive brings it back (re-hydrated: whatever it cached may be stale).
    await h.discovery._on_advertisement(advertisement(LOC_A, UDN_A))
    assert h.available_udns() == {UDN_A}
    assert h.discovery.hydration_count == 2


@pytest.mark.asyncio
async def test_byebye_followed_by_successful_probe_keeps_device(h, monkeypatch):
    monkeypatch.setattr(discovery_module, "BYEBYE_PROBE_DELAY_SECONDS", 0)
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A)]
    await h.discovery.discover(timeout=0)
    h.probe_results[LOC_A] = True

    await h.discovery._on_byebye(advertisement(LOC_A, UDN_A, nts="ssdp:byebye"))
    await asyncio.gather(*h.discovery._probe_tasks.values())

    assert h.available_udns() == {UDN_A}
    assert h.persisted == []


@pytest.mark.asyncio
async def test_byebye_then_quick_alive_cancels_probe(h, monkeypatch):
    monkeypatch.setattr(discovery_module, "BYEBYE_PROBE_DELAY_SECONDS", 0.2)
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A)]
    await h.discovery.discover(timeout=0)

    await h.discovery._on_byebye(advertisement(LOC_A, UDN_A, nts="ssdp:byebye"))
    await h.discovery._on_advertisement(advertisement(LOC_A, UDN_A))
    await asyncio.sleep(0.3)

    assert h.probes == []
    assert h.available_udns() == {UDN_A}


@pytest.mark.asyncio
async def test_transient_multicast_loss_does_not_drop_device(h):
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A, max_age=1800)]
    await h.discovery.discover(timeout=0)

    h.ssdp.multicast_replies = []  # replies lost
    for _ in range(10):
        h.clock.advance(60)
        await h.discovery.discover(timeout=0)

    assert h.available_udns() == {UDN_A}
    assert h.probes == []  # nothing even probed inside the lifetime


@pytest.mark.asyncio
async def test_expired_lifetime_probes_then_marks_unavailable(h):
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A, max_age=100)]
    await h.discovery.discover(timeout=0)
    h.ssdp.multicast_replies = []

    # Past the lifetime + grace but still answering HTTP: stays.
    h.clock.advance(100 + LIVENESS_GRACE_SECONDS + 1)
    h.probe_results[LOC_A] = True
    await h.discovery.discover(timeout=0)
    assert h.available_udns() == {UDN_A}
    assert h.probes == [LOC_A]

    # Lifetime lapses again and the probe fails: unavailable.
    h.clock.advance(100 + LIVENESS_GRACE_SECONDS + 1)
    h.probe_results[LOC_A] = False
    await h.discovery.discover(timeout=0)
    assert h.available_udns() == set()
    assert UDN_A in h.manager.renderers


@pytest.mark.asyncio
async def test_listener_bind_failure_falls_back_to_polling(h):
    def broken_listener(**_kwargs):
        raise OSError("Address already in use")

    h.discovery._listener_factory = broken_listener
    await h.discovery._start_listener()

    assert h.discovery._listener is None
    assert "polling" in h.discovery.diagnostics()["listener"]


@pytest.mark.asyncio
async def test_listener_alive_registers_device(h):
    captured = {}

    class FakeListener:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def async_start(self):
            pass

        async def async_stop(self):
            captured["stopped"] = True

    h.discovery._listener_factory = FakeListener
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    await h.discovery._start_listener()
    assert h.discovery.diagnostics()["listener"] == "running"

    await captured["async_on_alive"](advertisement(LOC_A, UDN_A))
    assert h.available_udns() == {UDN_A}

    await h.discovery._stop_listener()
    assert captured["stopped"]


# --------------------------------------------------------------- manual add


@pytest.mark.asyncio
async def test_manual_add_by_ip_uses_unicast_ssdp_and_returns_device(h):
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.unicast_replies["192.0.2.10"] = [search_reply(LOC_A, UDN_A)]

    result = await h.manager.add_device_by_ip("192.0.2.10")

    assert [r["udn"] for r in result] == [UDN_A]
    unicast = [c for c in h.ssdp.calls if c["target_addr"]]
    assert unicast[0]["target_addr"] == ("192.0.2.10", 1900)
    assert h.probes == []  # no guessing needed


@pytest.mark.asyncio
async def test_manual_add_falls_back_to_guessed_urls(h):
    guessed = "http://192.0.2.10:8080/description.xml"
    h.serve(guessed, device_xml(UDN_A, "Kitchen"))
    h.probe_results[guessed] = True

    result = await h.manager.add_device_by_ip("192.0.2.10")

    assert [r["udn"] for r in result] == [UDN_A]


@pytest.mark.asyncio
async def test_manual_add_returns_none_when_nothing_registers(h):
    # A guessed URL answers 200, but it is not a playable device.
    guessed = "http://192.0.2.10:49152/description.xml"
    h.serve(guessed, device_xml(UDN_A, "NAS", device_type=MEDIA_SERVER, services=(CONNECTION_MANAGER,)))
    h.probe_results[guessed] = True

    assert await h.manager.add_device_by_ip("192.0.2.10") is None
    assert not any("Successfully" in line for line in h.manager.debug_log)


@pytest.mark.asyncio
async def test_manual_add_accepts_description_url(h):
    url = "http://192.0.2.50:1234/dev/desc.xml"
    h.serve(url, device_xml(UDN_A, "Kitchen"))

    result = await h.manager.add_device_by_ip(f"  {url} ")

    assert [r["location"] for r in result] == [url]
    assert h.ssdp.calls == []  # no SSDP for an explicit URL


@pytest.mark.asyncio
async def test_manual_add_ignores_cooldown(h):
    url = "http://192.0.2.50:1234/dev/desc.xml"
    h.discovery._track_failure(url, RuntimeError("earlier"), None)
    h.serve(url, device_xml(UDN_A, "Kitchen"))

    assert await h.manager.add_device_by_ip(url)


@pytest.mark.asyncio
async def test_backend_add_manual_returns_registered_device(h):
    url = "http://192.0.2.50:1234/dev/desc.xml"
    h.serve(url, device_xml(UDN_A, "Kitchen"))
    backend = UpnpRendererBackend(h.manager)

    device = await backend.add_manual(url)

    assert isinstance(device, RendererDevice)
    assert device.renderer_id == f"upnp:{UDN_A}"
    assert device.ip == "192.0.2.50"
    assert await backend.add_manual("192.0.2.77") is None

    orchestrator = RendererOrchestrator(registry=_registry(backend))
    added = await orchestrator.add_manual(url)
    assert added is not None and added.udn == UDN_A


# --------------------------------------------------------------- subnet scan


def test_scan_network_uses_interface_prefix():
    net, clipped = network_module.scan_network("192.168.0.27", prefix=23)
    assert net == ipaddress.ip_network("192.168.0.0/23") and not clipped


def test_scan_network_clips_wide_networks():
    net, clipped = network_module.scan_network("10.1.2.3", prefix=16)
    assert net.prefixlen == network_module.MAX_SCAN_PREFIX and clipped
    assert ipaddress.ip_address("10.1.2.3") in net


def test_scan_network_falls_back_to_24(monkeypatch):
    monkeypatch.setattr(network_module, "interface_prefix", lambda _ip: None)
    net, clipped = network_module.scan_network("192.0.2.7")
    assert net == ipaddress.ip_network("192.0.2.0/24") and not clipped


@pytest.mark.asyncio
async def test_subnet_scan_progress_from_real_host_count(h, monkeypatch):
    monkeypatch.setattr(
        discovery_module,
        "scan_network",
        lambda ip: (ipaddress.ip_network("192.0.2.0/29"), False),
    )
    probed: list[str] = []

    async def probe_host(host, *, manual):
        probed.append(host)
        return None

    h.discovery._probe_host = probe_host
    await h.manager.scan_subnet()

    assert sorted(probed) == [f"192.0.2.{i}" for i in (1, 3, 4, 5, 6)]  # .2 is us
    assert h.discovery.scan_total_hosts == 5
    assert h.discovery.scan_progress == 100
    assert not h.manager.is_scanning_subnet
    assert h.manager.scan_msg.startswith("Scan complete")


@pytest.mark.asyncio
async def test_subnet_scan_bounded_concurrency_and_cancel(h, monkeypatch):
    monkeypatch.setattr(
        discovery_module,
        "scan_network",
        lambda ip: (ipaddress.ip_network("192.0.2.0/24"), False),
    )
    active = 0
    peak = 0
    started = asyncio.Event()

    async def probe_host(host, *, manual):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        started.set()
        try:
            await asyncio.sleep(3600)
        finally:
            active -= 1

    h.discovery._probe_host = probe_host
    task = asyncio.create_task(h.manager.scan_subnet())
    await asyncio.wait_for(started.wait(), 1)
    await asyncio.sleep(0.01)
    assert h.manager.is_scanning_subnet
    assert peak == SUBNET_CONCURRENCY

    assert h.manager.cancel_subnet_scan() is True
    await asyncio.wait_for(task, 1)

    assert not h.manager.is_scanning_subnet
    assert h.manager.scan_msg == "Scan cancelled"
    assert active == 0


@pytest.mark.asyncio
async def test_second_subnet_scan_does_not_overlap(h, monkeypatch):
    monkeypatch.setattr(
        discovery_module,
        "scan_network",
        lambda ip: (ipaddress.ip_network("192.0.2.0/30"), False),
    )
    calls = 0

    async def probe_host(host, *, manual):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)

    h.discovery._probe_host = probe_host
    await asyncio.gather(h.manager.scan_subnet(), h.manager.scan_subnet())
    assert calls == 1  # /30 minus our own address... and only one sweep


@pytest.mark.asyncio
async def test_subnet_probe_reuses_unicast_then_guess(h):
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.unicast_replies["192.0.2.10"] = [search_reply(LOC_A, UDN_A)]
    found = await h.discovery._probe_host("192.0.2.10", manual=False)
    assert [r["udn"] for r in found] == [UDN_A]
    assert h.probes == []


# --------------------------------------------------------------- orchestrator


def _registry(backend) -> RendererRegistry:
    registry = RendererRegistry()
    registry.backends["upnp"] = backend
    return registry


@pytest.mark.asyncio
async def test_orchestrator_uses_tracked_availability(h, monkeypatch):
    monkeypatch.setattr(discovery_module, "BYEBYE_PROBE_DELAY_SECONDS", 0)
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A)]
    await h.discovery.discover(timeout=0)
    orchestrator = RendererOrchestrator(registry=_registry(UpnpRendererBackend(h.manager)))
    renderer_id = f"upnp:{UDN_A}"

    assert await orchestrator._renderer_available(renderer_id) is True
    assert await orchestrator._renderer_available("upnp:uuid:never-seen") is False

    await h.discovery._on_byebye(advertisement(LOC_A, UDN_A, nts="ssdp:byebye"))
    await asyncio.gather(*h.discovery._probe_tasks.values())

    assert await orchestrator._renderer_available(renderer_id) is False


@pytest.mark.asyncio
async def test_orchestrator_heals_session_on_unavailable_upnp_renderer(h, monkeypatch):
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A)]
    await h.discovery.discover(timeout=0)
    await h.discovery._set_available(h.discovery._locations[LOC_A], False, "test")
    orchestrator = RendererOrchestrator(registry=_registry(UpnpRendererBackend(h.manager)))
    renderer_id = f"upnp:{UDN_A}"

    class Db:
        calls: list = []

        async def execute(self, sql, *args):
            self.calls.append(sql)
            return "UPDATE 1"

    async def get_active(_db, _cid):
        return renderer_id, UDN_A

    monkeypatch.setattr(orchestrator, "get_active", get_active)
    db = Db()
    await orchestrator._heal_if_renderer_gone(db, "client-1", ValueError("gone"))
    assert any("UPDATE client_session" in sql for sql in db.calls)


@pytest.mark.asyncio
async def test_control_failure_triggers_probe_and_rehydrate(h):
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A)]
    await h.discovery.discover(timeout=0)
    h.probe_results[LOC_A] = True

    async def failing_play(*_args, **_kwargs):
        raise ConnectionError("renderer reset the connection")

    h.manager.play_track = failing_play
    backend = UpnpRendererBackend(h.manager)
    from app.services.renderer.contracts import PlaybackContext, RendererLoadError

    # Surfaced as a load failure (player state rolls back), cause kept.
    with pytest.raises(RendererLoadError) as excinfo:
        await backend.play_track(
            f"upnp:{UDN_A}", {"id": 1}, PlaybackContext(base_url="http://x", user_id=None)
        )
    assert isinstance(excinfo.value.__cause__, ConnectionError)
    await asyncio.gather(*h.discovery._probe_tasks.values())

    assert h.probes == [LOC_A]
    assert h.discovery.hydration_count == 2


@pytest.mark.asyncio
async def test_persisted_renderers_hidden_until_reachable(h, monkeypatch):
    rows = [
        {"udn": UDN_A, "friendly_name": "Kitchen", "location_url": LOC_A, "icon_url": None,
         "has_local_icon": None, "kind": "upnp"},
        {"udn": UDN_B, "friendly_name": "Gone", "location_url": LOC_B, "icon_url": None,
         "has_local_icon": None, "kind": "upnp"},
    ]

    class Conn:
        async def fetch(self, _sql):
            return rows

    class Ctx:
        async def __aenter__(self):
            return Conn()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(discovery_module, "db_conn", lambda: Ctx())
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))  # B's description 404s

    await h.discovery.load_persisted_renderers()

    assert h.available_udns() == {UDN_A}
    assert h.manager.renderers[UDN_B]["friendly_name"] == "Gone"  # kept, hidden
    assert ([UDN_B], False) in h.persisted


def test_diagnostics_shape(h):
    diag = h.manager.diagnostics()
    for key in (
        "source_ip",
        "stream_ip",
        "listener",
        "search_targets",
        "last_scan",
        "descriptor_failures",
        "cooldowns",
        "devices",
        "transitions",
    ):
        assert key in diag
    assert diag["stream_ip"] == "192.0.2.2"


def test_source_ip_config_drives_stream_address(monkeypatch):
    monkeypatch.setenv("UPNP_SOURCE_IP", "192.0.2.44")
    manager = UPnPManager()
    assert manager.source_ip == "192.0.2.44"
    assert manager.local_ip == "192.0.2.44"
    assert manager.discovery._source_addr() == ("192.0.2.44", 0)
    assert manager.refresh_local_ip() is False

    monkeypatch.delenv("UPNP_SOURCE_IP")
    manager = UPnPManager()
    assert manager.discovery._source_addr() is None


# --------------------------------------------------------------- review fixes


@pytest.mark.asyncio
async def test_not_a_renderer_is_rechecked_with_backoff(h):
    """A root-only description (booting TV) is re-read later, not ignored forever."""
    h.serve(LOC_A, device_xml(UDN_A, "Booting TV", services=(CONNECTION_MANAGER,)))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A)]
    await h.discovery.discover(timeout=0)

    h.clock.advance(discovery_module._FAILURE_COOLDOWN_STEPS[0] - 1)
    await h.discovery.discover(timeout=0)
    assert h.fetches(LOC_A) == 1  # still backing off

    h.serve(LOC_A, device_xml(UDN_A, "Booting TV"))  # finished booting
    h.clock.advance(2)
    found = await h.discovery.discover(timeout=0)
    assert h.fetches(LOC_A) == 2
    assert [r["udn"] for r in found] == [UDN_A]


@pytest.mark.asyncio
async def test_not_a_renderer_backoff_escalates(h):
    h.serve(LOC_A, device_xml(UDN_A, "Odd", services=(CONNECTION_MANAGER,)))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A)]
    await h.discovery.discover(timeout=0)
    h.clock.advance(discovery_module._FAILURE_COOLDOWN_STEPS[0] + 1)
    await h.discovery.discover(timeout=0)
    assert h.fetches(LOC_A) == 2
    h.clock.advance(discovery_module._FAILURE_COOLDOWN_STEPS[0] + 1)
    await h.discovery.discover(timeout=0)
    assert h.fetches(LOC_A) == 2  # second step is longer


@pytest.mark.asyncio
async def test_saved_renderer_serving_root_only_description_is_rechecked_every_scan(h):
    h.serve(LOC_A, device_xml(UDN_A, "TV"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A, bootid="1")]
    await h.discovery.discover(timeout=0)

    # Reboots into a root-only description for a while.
    h.serve(LOC_A, device_xml(UDN_A, "TV", services=(CONNECTION_MANAGER,)))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A, bootid="2")]
    await h.discovery.discover(timeout=0)
    assert h.fetches(LOC_A) == 2
    assert h.discovery._locations[LOC_A].is_renderer  # still a known renderer
    assert h.manager.renderers[UDN_A]["friendly_name"] == "TV"

    h.serve(LOC_A, device_xml(UDN_A, "TV"))
    h.clock.advance(discovery_module.POLL_INTERVAL_SECONDS + 1)
    await h.discovery.discover(timeout=0)
    assert h.fetches(LOC_A) == 3
    assert h.discovery._locations[LOC_A].recheck_at == 0.0
    assert h.available_udns() == {UDN_A}


@pytest.mark.asyncio
async def test_failed_save_leaves_no_half_registered_renderer(h):
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))

    async def failing_save(_info):
        raise RuntimeError("db down")

    h.manager.save_renderer = failing_save

    assert await h.discovery.hydrate(LOC_A) is None
    assert UDN_A not in h.manager.renderers
    assert UDN_A not in h.manager.dmr_devices
    assert h.available_udns() == set()


@pytest.mark.asyncio
async def test_deadline_mid_registration_commits_only_finished_endpoints(h, monkeypatch):
    monkeypatch.setattr(discovery_module, "HYDRATE_DEADLINE_SECONDS", 0.2)
    zone1 = device_xml("uuid:zone-1", "Zone 1")
    zone2 = device_xml("uuid:zone-2", "Zone 2")
    h.serve(LOC_A, device_xml(UDN_A, "Amp", device_type=BASIC_DEVICE, services=(), children=(zone1, zone2)))

    async def save(info):
        if info["udn"] == "uuid:zone-2":
            await asyncio.sleep(5)
        h.saved.append(info)

    h.manager.save_renderer = save

    assert await h.discovery.hydrate(LOC_A) is None  # deadline hit

    assert "uuid:zone-2" not in h.manager.renderers
    assert h.manager.renderers["uuid:zone-1"]["available"] is True
    record = h.discovery._locations[LOC_A]
    assert record.udns == ["uuid:zone-1"] and record.available  # tracked, so probed later


@pytest.mark.asyncio
async def test_root_udn_settings_move_to_single_embedded_endpoint(h):
    """Old installs saved the root UDN; now the embedded child is the endpoint."""
    h.manager.renderers[UDN_A] = {"udn": UDN_A, "friendly_name": "Receiver", "available": False}
    record = discovery_module.LocationRecord(location=LOC_A, udns=[UDN_A], needs_rehydrate=True)
    h.discovery._locations[LOC_A] = record
    child = device_xml(UDN_B, "Receiver Zone")
    h.serve(LOC_A, device_xml(UDN_A, "Receiver", device_type=BASIC_DEVICE, services=(), children=(child,)))

    found = await h.discovery.hydrate(LOC_A)

    assert [r["udn"] for r in found] == [UDN_B]
    assert h.migrations == [(UDN_A, UDN_B)]
    assert UDN_A not in h.manager.renderers
    assert h.discovery._locations[LOC_A].udns == [UDN_B]


@pytest.mark.asyncio
async def test_root_udn_left_unavailable_when_endpoints_are_ambiguous(h):
    h.manager.renderers[UDN_A] = {"udn": UDN_A, "friendly_name": "Amp", "available": True}
    h.discovery._locations[LOC_A] = discovery_module.LocationRecord(
        location=LOC_A, udns=[UDN_A], available=True, hydrated=True, needs_rehydrate=True
    )
    zone1 = device_xml("uuid:zone-1", "Zone 1")
    zone2 = device_xml("uuid:zone-2", "Zone 2")
    h.serve(LOC_A, device_xml(UDN_A, "Amp", device_type=BASIC_DEVICE, services=(), children=(zone1, zone2)))

    await h.discovery.hydrate(LOC_A)

    assert h.migrations == []
    assert h.manager.renderers[UDN_A]["available"] is False  # kept, hidden
    assert ([UDN_A], False) in h.persisted
    assert h.available_udns() == {"uuid:zone-1", "uuid:zone-2"}


@pytest.mark.asyncio
async def test_control_failure_rehydrate_survives_a_sighting(h):
    """A sighting cancels the pending probe, but the re-hydrate still happens."""
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A)]
    await h.discovery.discover(timeout=0)

    h.discovery.note_control_failure(UDN_A)
    await h.discovery._on_advertisement(advertisement(LOC_A, UDN_A))  # before the probe ran

    assert h.discovery.hydration_count == 2
    assert not h.discovery._locations[LOC_A].needs_rehydrate


@pytest.mark.asyncio
async def test_control_failure_rehydrate_survives_pending_byebye_probe(h, monkeypatch):
    monkeypatch.setattr(discovery_module, "BYEBYE_PROBE_DELAY_SECONDS", 0.05)
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A)]
    await h.discovery.discover(timeout=0)
    h.probe_results[LOC_A] = True

    await h.discovery._on_byebye(advertisement(LOC_A, UDN_A, nts="ssdp:byebye"))
    h.discovery.note_control_failure(UDN_A)  # probe already queued: early return
    await asyncio.gather(*h.discovery._probe_tasks.values())

    assert h.discovery.hydration_count == 2
    assert h.available_udns() == {UDN_A}


@pytest.mark.asyncio
async def test_refresh_waiting_on_background_scan_still_rehydrates(h):
    h.serve(LOC_A, device_xml(UDN_A, "Kitchen"))
    h.ssdp.multicast_replies = [search_reply(LOC_A, UDN_A)]
    await h.discovery.discover(timeout=0)
    assert h.discovery.hydration_count == 1

    h.ssdp.delay = 0.05
    background = asyncio.create_task(h.discovery.discover(timeout=0))
    await asyncio.sleep(0.01)
    await h.discovery.discover(timeout=0, refresh=True)
    await background

    assert h.ssdp.multicast_calls == 3  # initial, background, then the refresh
    assert h.discovery.hydration_count == 2


@pytest.mark.asyncio
async def test_non_refresh_waiting_on_scan_does_not_rescan(h):
    h.ssdp.delay = 0.05
    await asyncio.gather(
        h.discovery.discover(timeout=0, refresh=True), h.discovery.discover(timeout=0)
    )
    assert h.ssdp.multicast_calls == 1


@pytest.mark.asyncio
async def test_backend_refresh_does_not_sweep_subnet(h):
    calls = []

    async def sweep():
        calls.append("sweep")

    h.manager.scan_subnet = sweep
    backend = UpnpRendererBackend(h.manager)
    await backend.discover(refresh=True)
    assert calls == []
    assert h.ssdp.multicast_calls == 1


@pytest.mark.asyncio
async def test_start_subnet_scan_is_single_flight(h, monkeypatch):
    monkeypatch.setattr(
        discovery_module,
        "scan_network",
        lambda ip: (ipaddress.ip_network("192.0.2.0/30"), False),
    )

    async def probe_host(host, *, manual):
        await asyncio.sleep(0.05)

    h.discovery._probe_host = probe_host
    assert h.manager.start_subnet_scan() is True
    assert h.manager.start_subnet_scan() is False
    await h.discovery._subnet_task
    assert not h.manager.is_scanning_subnet
