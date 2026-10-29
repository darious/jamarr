"""UPnP event subscriptions (GENA) and the monitor's event/watchdog mode.

Real async_upnp_client device parsing, UpnpEventHandler and LastChange
handling, against in-memory fakes: FakeRequester answers description, SCPD
and SUBSCRIBE/UNSUBSCRIBE requests, FakeNotifyServer replaces the socket.
Nothing here touches the network.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from types import SimpleNamespace

import pytest

from app import config as app_config
from app.db import db_conn
from app.services.player import monitor as monitor_module
from app.services.player.globals import (
    last_playing_position,
    last_playing_seen,
    last_stop_reason,
    last_track_start_time,
    start_retries,
)
from app.services.player.state import get_renderer_state_db, update_renderer_state_db
from app.services.upnp import events as events_module
from app.services.upnp.events import (
    INITIAL_EVENT_TIMEOUT_S,
    MAX_SUBSCRIBE_FAILURES,
    MAX_UNRELIABLE_EPISODES,
    UpnpEventManager,
    parse_upnp_duration,
)
from app.services.upnp.staging import staging, staging_allowed
from app.services.upnp.tree import TreeKeepingUpnpFactory, make_dmr, playable_endpoints
from app.upnp import UPnPManager
from tests.helpers.upnp_fakes import (
    FakeClock,
    FakeNotifyServer,
    FakeRequester,
    description,
    device_xml,
    last_change,
    send_notify,
)

LOCATION = "http://192.0.2.10:49152/description.xml"
UDN = "uuid:evt-0001"
LOCAL_IP = "192.0.2.2"
URI_A = "http://192.0.2.2:8112/api/stream/900?token=aaa&x=1"
URI_B = "http://192.0.2.2:8112/api/stream/901?token=bbb"


async def _make_dmr(requester: FakeRequester, udn: str = UDN, location: str = LOCATION):
    requester.descriptions[location] = description(device_xml(udn, "Evented TV"))
    root = await TreeKeepingUpnpFactory(requester).async_create_device(location)
    return make_dmr(playable_endpoints(root)[0])


class FakeManager:
    """The slice of UPnPManager the event manager uses."""

    def __init__(self, requester: FakeRequester) -> None:
        self._requester = requester
        self.local_ip = LOCAL_IP
        self.dmr_devices: dict = {}
        self.renderers: dict = {}
        self.control_failures: list[str] = []

    async def _ensure_session(self) -> None:
        return None

    def note_control_failure(self, udn: str) -> None:
        self.control_failures.append(udn)


class Rig:
    def __init__(self, *, server_fails: bool = False, enabled: bool = True) -> None:
        self.requester = FakeRequester(rich_scpd=True)
        self.gena = self.requester.gena
        self.manager = FakeManager(self.requester)
        self.clock = FakeClock()
        self.servers: list[FakeNotifyServer] = []

        def factory(requester, source):
            server = FakeNotifyServer(requester, source, fail=server_fails)
            self.servers.append(server)
            return server

        self.events = UpnpEventManager(
            self.manager,
            server_factory=factory,
            clock=self.clock,
            config={"enabled": enabled, "port": 8113},
        )

    async def add(self, udn: str = UDN):
        dmr = await _make_dmr(self.requester, udn)
        self.manager.dmr_devices[udn] = dmr
        self.manager.renderers[udn] = {"udn": udn, "supports_events": False}
        return dmr

    def manual(self) -> None:
        """Drive subscription upkeep by hand (``step``) instead of the task."""

        async def idle(_st):
            return None

        self.events._run = idle

    async def step(self, udn: str = UDN) -> float:
        return await self.events._step(self.events._renderers[udn])

    @property
    def handler(self):
        return self.events._server.event_handler

    async def notify_avt(self, **values) -> int:
        sid = self.gena.sid_for("/AVTransport/")
        return await send_notify(self.handler, sid, last_change("AVT", **values))

    async def notify_rc(self, **values) -> int:
        sid = self.gena.sid_for("/RenderingControl/")
        return await send_notify(self.handler, sid, last_change("RCS", **values))

    async def healthy_rig(self, udn: str = UDN):
        """Subscribed, initial events delivered."""
        self.manual()
        await self.add(udn)
        self.events.acquire(udn)
        await self.step(udn)
        await self.notify_avt(
            TransportState="PLAYING", CurrentTrackURI=URI_A, CurrentTrackDuration="0:03:00"
        )
        await self.notify_rc(Volume={"Master": 30}, Mute="0")
        return self.events.snapshot(udn)


@pytest.fixture(autouse=True)
def _no_db_side_effects(monkeypatch):
    """Verdict/volume persistence is exercised by the DB tests only."""
    saved = []

    async def no_verdict(self, udn, usable):
        saved.append(("verdict", udn, usable))

    monkeypatch.setattr(UpnpEventManager, "_persist_verdict", no_verdict)
    yield saved


# --- LastChange parsing and the healthy path --------------------------------


async def test_subscribes_both_services_and_initial_events_make_it_healthy():
    rig = Rig()
    rig.manual()
    await rig.add()
    rig.events.acquire(UDN)
    await rig.step()

    server = rig.servers[0]
    assert server.started and server.source == (LOCAL_IP, 8113)
    subs = [c for c in rig.gena.calls if c[0] == "SUBSCRIBE"]
    assert sorted(url.rsplit("/", 2)[-2] for _m, url, _h in subs) == [
        "AVTransport",
        "RenderingControl",
    ]
    assert all(h["CALLBACK"] == f"<http://{LOCAL_IP}:8113/notify>" for _m, _u, h in subs)

    # Subscribed is not healthy: the device has not proven it can reach us.
    snap = rig.events.snapshot(UDN)
    assert snap.avt_healthy is False and snap.rc_healthy is False
    assert rig.events.supports_events(UDN) is False

    assert await rig.notify_avt(
        TransportState="PLAYING", CurrentTrackURI=URI_A, CurrentTrackDuration="0:03:00"
    ) == 200
    await rig.notify_rc(Volume={"Master": 30}, Mute="0")

    snap = rig.events.snapshot(UDN)
    assert snap.avt_healthy and snap.rc_healthy
    assert snap.transport_state == "PLAYING"
    assert snap.track_uri == URI_A  # XML-escaped '&' decoded
    assert snap.track_duration == 180
    assert snap.volume == 30 and snap.muted is False
    assert rig.events.supports_events(UDN) is True
    assert rig.manager.renderers[UDN]["supports_events"] is True

    diag = rig.events.diagnostics()
    avt = diag["renderers"][UDN]["services"]["AVTransport"]
    assert avt["healthy"] and avt["subscribed"] and avt["events"] == 1
    assert avt["sid"] == rig.gena.sid_for("/AVTransport/")
    assert avt["expires_in_seconds"] == 300
    assert diag["listening"] and diag["callback_url"] == f"http://{LOCAL_IP}:8113/notify"
    assert diag["renderers"][UDN]["supports_events"] is True


async def test_lastchange_parsing_channels_scaling_and_unknown_values():
    rig = Rig()
    rig.requester.max_volume = 50  # device volume range 0..50
    await rig.healthy_rig()

    await rig.notify_rc(Volume={"LF": 5, "Master": 25}, Mute="1")
    snap = rig.events.snapshot(UDN)
    assert snap.volume == 50  # 25 of 50, Master only
    assert snap.muted is True

    gen = snap.generation
    await rig.notify_avt(TransportState="PAUSED_PLAYBACK", CurrentTrackDuration="NOT_IMPLEMENTED")
    snap = rig.events.snapshot(UDN)
    assert snap.transport_state == "PAUSED_PLAYBACK"
    assert snap.track_duration is None
    assert snap.track_uri == URI_A  # untouched by an event that omits it
    assert snap.generation == gen + 1


def test_parse_upnp_duration():
    assert parse_upnp_duration("1:02:03") == 3723
    assert parse_upnp_duration("0:00:01.500") == 1.5
    assert parse_upnp_duration("NOT_IMPLEMENTED") is None
    assert parse_upnp_duration("") is None
    assert parse_upnp_duration("garbage") is None


async def test_av_transport_uri_stands_in_for_missing_track_uri():
    rig = Rig()
    rig.manual()
    await rig.add()
    rig.events.acquire(UDN)
    await rig.step()
    await rig.notify_avt(TransportState="PLAYING", AVTransportURI=URI_B)
    assert rig.events.snapshot(UDN).track_uri == URI_B


async def test_events_for_unknown_sid_before_subscribe_returns_are_replayed():
    """A device that NOTIFYs before its SUBSCRIBE reply is still counted."""
    rig = Rig()
    rig.manual()
    await rig.add()
    rig.events.acquire(UDN)
    await rig.events._ensure_server()
    # The device will hand out SID 1 for AVT; its initial event lands first.
    await send_notify(
        rig.events._server.event_handler,
        "uuid:sid-1",
        last_change("AVT", TransportState="STOPPED"),
    )
    await rig.step()
    snap = rig.events.snapshot(UDN)
    assert snap.transport_state == "STOPPED"
    assert snap.avt_healthy is True
    assert rig.events.supports_events(UDN) is True


# --- renewal, failures, fallback, resubscribe -------------------------------


async def test_renews_before_expiry_without_needing_a_new_initial_event():
    rig = Rig()
    await rig.healthy_rig()
    sid = rig.gena.sid_for("/AVTransport/")

    await rig.step()
    sub = rig.events._renderers[UDN].services["AVT"]
    assert sub.renew_at - rig.clock.now == 240  # 60 s before the 300 s expiry

    rig.clock.advance(241)
    await rig.step()
    assert rig.gena.count("SUBSCRIBE", renewal=True) == 2
    assert rig.gena.sid_for("/AVTransport/") == sid
    snap = rig.events.snapshot(UDN)
    assert snap.avt_healthy and snap.rc_healthy
    sub = rig.events._renderers[UDN].services["AVT"]
    assert sub.renewals == 1
    assert sub.expires_at == pytest.approx(rig.clock.now + 300)


async def test_dropped_subscription_falls_back_then_resubscribes():
    rig = Rig()
    await rig.healthy_rig()

    # Device unreachable at renewal time: the subscription is gone.
    rig.gena.offline = True
    rig.clock.advance(241)
    await rig.step()
    assert rig.events.avt_healthy(UDN) is False
    sub = rig.events._renderers[UDN].services["AVT"]
    assert sub.subscribed is False and sub.failures == 1
    assert "offline" in sub.last_error
    assert UDN in rig.manager.control_failures  # discovery re-checks it

    # Back online (rebooted, old SIDs forgotten): retried after the backoff,
    # healthy again only after the fresh subscription's initial event.
    rig.gena.offline = False
    rig.gena.active.clear()
    await rig.step()
    assert rig.gena.count("SUBSCRIBE", renewal=False) == 2  # no retry yet
    rig.clock.advance(6)
    await rig.step()
    assert rig.gena.count("SUBSCRIBE", renewal=False) == 4
    assert rig.events.avt_healthy(UDN) is False
    await rig.notify_avt(TransportState="PLAYING", CurrentTrackURI=URI_A)
    assert rig.events.avt_healthy(UDN) is True


async def test_device_that_forgot_the_sid_gets_a_full_subscribe():
    rig = Rig()
    await rig.healthy_rig()
    old_sid = rig.gena.sid_for("/AVTransport/")
    rig.gena.forget = True  # renewal answered 412
    rig.clock.advance(241)
    await rig.step()
    new_sid = rig.gena.sid_for("/AVTransport/")
    assert new_sid != old_sid
    # New SID: the device owes us a fresh initial event first.
    assert rig.events.avt_healthy(UDN) is False
    rig.gena.forget = False
    await rig.notify_avt(TransportState="PLAYING")
    assert rig.events.avt_healthy(UDN) is True


async def test_expired_subscription_is_not_healthy():
    rig = Rig()
    await rig.healthy_rig()
    rig.clock.advance(301)  # renewal never happened (task starved)
    assert rig.events.avt_healthy(UDN) is False


async def test_no_initial_event_means_unhealthy_and_retried():
    rig = Rig()
    rig.manual()
    await rig.add()
    rig.events.acquire(UDN)
    await rig.step()
    rig.clock.advance(INITIAL_EVENT_TIMEOUT_S + 1)
    await rig.step()
    sub = rig.events._renderers[UDN].services["AVT"]
    assert sub.subscribed is False
    assert "initial NOTIFY" in sub.last_error
    assert rig.gena.count("UNSUBSCRIBE") == 2
    assert rig.events.supports_events(UDN) is False


async def test_refused_subscription_is_reported_and_eventually_given_up():
    rig = Rig()
    rig.manual()
    await rig.add()
    rig.manager.renderers[UDN]["supports_events"] = True  # a stale claim
    rig.gena.refuse = 412
    rig.events.acquire(UDN)
    await rig.step()
    assert rig.events.supports_events(UDN) is False
    assert rig.manager.renderers[UDN]["supports_events"] is False
    for _ in range(MAX_SUBSCRIBE_FAILURES):
        rig.clock.advance(121)
        await rig.step()
    sub = rig.events._renderers[UDN].services["AVT"]
    assert sub.gave_up
    attempts = rig.gena.count("SUBSCRIBE")
    rig.clock.advance(1000)
    await rig.step()
    assert rig.gena.count("SUBSCRIBE") == attempts  # stopped trying


async def test_watchdog_mismatch_marks_unreliable_and_resubscribes():
    rig = Rig()
    await rig.healthy_rig()
    rig.clock.advance(5)  # events are settled

    # One disagreement: the polled value wins, still healthy.
    assert rig.events.note_poll(UDN, transport_state="STOPPED") is True
    snap = rig.events.snapshot(UDN)
    assert snap.transport_state == "STOPPED" and snap.avt_healthy
    # Agreement resets the count.
    assert rig.events.note_poll(UDN, transport_state="STOPPED", track_uri=URI_A) is False
    # Two in a row: unreliable -> monitor falls back to 1 s polling.
    rig.events.note_poll(UDN, track_uri=URI_B)
    rig.events.note_poll(UDN, transport_state="PLAYING")
    assert rig.events.avt_healthy(UDN) is False
    assert rig.events.snapshot(UDN).track_uri == URI_B

    old_sid = rig.gena.sid_for("/AVTransport/")
    await rig.step()  # re-subscribes the unreliable service
    assert rig.gena.sid_for("/AVTransport/") != old_sid
    await rig.notify_avt(TransportState="PLAYING")
    assert rig.events.avt_healthy(UDN) is True


async def test_poll_right_after_an_event_is_not_a_mismatch():
    rig = Rig()
    await rig.healthy_rig()
    # Event just arrived; a poll that raced it is not evidence of a miss.
    assert rig.events.note_poll(UDN, transport_state="STOPPED") is False
    assert rig.events.snapshot(UDN).transport_state == "PLAYING"


async def test_repeatedly_unreliable_events_are_given_up(_no_db_side_effects):
    rig = Rig()
    await rig.healthy_rig()
    for episode in range(MAX_UNRELIABLE_EPISODES):
        rig.clock.advance(5)
        rig.events.note_poll(UDN, transport_state="STOPPED")
        rig.events.note_poll(UDN, transport_state="PLAYING")
        await rig.step()
        if episode < MAX_UNRELIABLE_EPISODES - 1:
            await rig.notify_avt(TransportState="PLAYING")
    st = rig.events._renderers[UDN]
    assert st.disabled
    assert rig.events.supports_events(UDN) is False
    assert rig.manager.renderers[UDN]["supports_events"] is False
    await asyncio.sleep(0)  # let the persistence task run
    assert ("verdict", UDN, False) in _no_db_side_effects
    assert not rig.gena.active  # unsubscribed
    assert rig.events.avt_healthy(UDN) is False


# --- rebirth, address change, release, shutdown -----------------------------


async def test_renderer_rebirth_resubscribes_to_the_new_device():
    rig = Rig()
    old_dmr_snapshot = await rig.healthy_rig()
    assert old_dmr_snapshot.avt_healthy
    old_sids = set(rig.gena.active)
    old_dmr = rig.manager.dmr_devices[UDN]

    # Discovery re-hydrated it (new BOOTID): a new DmrDevice object.
    new_dmr = await _make_dmr(rig.requester)
    rig.manager.dmr_devices[UDN] = new_dmr
    st = rig.events._renderers[UDN]
    rig.events.check(UDN)
    assert st.kick.is_set()
    await rig.step()

    assert not (old_sids & set(rig.gena.active))  # old ones unsubscribed
    assert len(rig.gena.active) == 2
    assert rig.events.avt_healthy(UDN) is False
    # Late events on the old device's services are ignored.
    old_dmr._service("AVT").on_event(old_dmr._service("AVT"), [])
    assert rig.events.avt_healthy(UDN) is False
    await rig.notify_avt(TransportState="PLAYING")
    assert rig.events.avt_healthy(UDN) is True


async def test_local_address_change_moves_the_callback_server():
    rig = Rig()
    await rig.healthy_rig()
    rig.manager.local_ip = "192.0.2.77"
    rig.events.check(UDN)
    await rig.step()
    assert rig.servers[0].stopped
    assert rig.servers[1].source == ("192.0.2.77", 8113)
    callbacks = [h["CALLBACK"] for m, _u, h in rig.gena.calls if m == "SUBSCRIBE" and "CALLBACK" in h]
    assert callbacks[-1] == "<http://192.0.2.77:8113/notify>"
    assert len(rig.gena.active) == 2


async def test_release_lingers_then_unsubscribes():
    rig = Rig()
    await rig.healthy_rig()
    rig.events.release(UDN, linger=0.01)
    # Re-acquired within the linger: nothing is torn down.
    rig.events.acquire(UDN)
    await asyncio.sleep(0.05)
    assert len(rig.gena.active) == 2

    rig.events.release(UDN, linger=0.01)
    await asyncio.sleep(0.05)
    assert rig.gena.active == {}
    assert rig.events.avt_healthy(UDN) is False
    # Event-derived state and the verdict survive for the UI/diagnostics.
    assert rig.events.supports_events(UDN) is True


async def test_drop_and_stop_unsubscribe_everything():
    rig = Rig()
    await rig.healthy_rig()
    await rig.add("uuid:evt-0002")
    rig.events.acquire("uuid:evt-0002")
    await rig.step("uuid:evt-0002")
    assert len(rig.gena.active) == 4

    await rig.events.drop(UDN)
    assert len(rig.gena.active) == 2
    await rig.events.stop()
    assert rig.gena.active == {}
    assert rig.servers[0].stopped


async def test_callback_server_failure_leaves_polling_and_no_verdict():
    rig = Rig(server_fails=True)
    rig.manual()
    await rig.add()
    rig.events.acquire(UDN)
    delay = await rig.step()
    assert delay > 0
    assert rig.gena.calls == []
    assert rig.events.avt_healthy(UDN) is False
    assert "Address already in use" in rig.events.diagnostics()["server_error"]
    # Our problem, not the device's: no verdict either way.
    assert UDN not in rig.events._verdicts


async def test_disabled_by_config_never_subscribes():
    rig = Rig(enabled=False)
    await rig.add()
    rig.events.acquire(UDN)
    assert rig.events._renderers == {}
    assert rig.events.snapshot(UDN) is None


async def test_background_task_subscribes_on_acquire():
    rig = Rig()
    await rig.add()
    rig.events.acquire(UDN)
    for _ in range(50):
        if len(rig.gena.active) == 2:
            break
        await asyncio.sleep(0.01)
    assert len(rig.gena.active) == 2
    await rig.events.stop()
    assert rig.gena.active == {}


def test_event_config(monkeypatch):
    monkeypatch.setattr(app_config, "_config", {"renderer": {"upnp_event_port": 9000}})
    monkeypatch.delenv("UPNP_EVENT_PORT", raising=False)
    monkeypatch.delenv("UPNP_EVENTS", raising=False)
    assert app_config.get_upnp_event_config() == {"enabled": True, "port": 9000}
    monkeypatch.setenv("UPNP_EVENT_PORT", "9100")
    monkeypatch.setenv("UPNP_EVENTS", "false")
    assert app_config.get_upnp_event_config() == {"enabled": False, "port": 9100}
    monkeypatch.setattr(app_config, "_config", {"renderer": {"upnp_events": False}})
    monkeypatch.delenv("UPNP_EVENTS")
    monkeypatch.delenv("UPNP_EVENT_PORT")
    assert app_config.get_upnp_event_config() == {"enabled": False, "port": 8113}


# --- supports_events truthfulness -------------------------------------------


async def test_discovery_does_not_claim_events_until_they_work(monkeypatch):
    manager = UPnPManager()
    requester = FakeRequester(rich_scpd=True)
    requester.descriptions[LOCATION] = description(device_xml(UDN, "Evented TV"))
    root = await TreeKeepingUpnpFactory(requester).async_create_device(LOCATION)
    node = playable_endpoints(root)[0]

    async def protocols(udn, dmr=None):
        return {"audio/flac"}

    async def existing(udn):
        return None

    monkeypatch.setattr(manager, "get_supported_protocols", protocols)
    monkeypatch.setattr(manager, "_existing_mime_types", existing)

    info, _dmr, _icon = await manager.discovery._stage_endpoint(node, LOCATION)
    assert info["supports_events"] is False  # eventSubURL alone proves nothing

    manager.events._verdicts[UDN] = True
    info, _dmr, _icon = await manager.discovery._stage_endpoint(node, LOCATION)
    assert info["supports_events"] is True


async def test_save_renderer_keeps_a_persisted_verdict(db, monkeypatch):
    monkeypatch.undo()  # real _persist_verdict
    manager = UPnPManager()
    udn = "uuid:evt-save-0001"
    info = {
        "udn": udn,
        "friendly_name": "Evented TV",
        "location": LOCATION,
        "supports_events": True,  # whatever discovery says...
    }
    await db.execute("DELETE FROM renderer WHERE udn = $1", udn)
    await manager.save_renderer(info)
    assert info["supports_events"] is True  # new row: as given

    # ...a verdict from a real subscription wins over later hydrations.
    await manager.events._persist_verdict(udn, False)
    info["supports_events"] = True
    await manager.save_renderer(info)
    assert info["supports_events"] is False
    await manager.events._persist_verdict(udn, True)
    info["supports_events"] = False
    await manager.save_renderer(info)
    assert info["supports_events"] is True
    row = await db.fetchrow(
        "SELECT supports_events, renderer_metadata FROM renderer WHERE udn = $1", udn
    )
    assert row["supports_events"] is True
    assert '"usable": true' in str(row["renderer_metadata"])
    await db.execute("DELETE FROM renderer WHERE udn = $1", udn)


async def test_remote_volume_change_reaches_renderer_state(db):
    udn = "uuid:evt-volume-0001"
    rig = Rig()
    await update_renderer_state_db(
        db,
        udn,
        {"queue": [], "current_index": -1, "position_seconds": 0, "is_playing": False,
         "transport_state": "STOPPED", "volume": 20},
    )
    await rig.healthy_rig(udn)  # initial RC event says 30
    await rig.notify_rc(Volume={"Master": 55})
    for _ in range(100):
        state = await get_renderer_state_db(db, udn)
        if state["volume"] == 55:
            break
        await asyncio.sleep(0.01)
    assert state["volume"] == 55
    await rig.notify_rc(Mute="1")
    assert rig.events.muted(udn) is True


async def test_evented_volume_is_read_back_from_the_device():
    """A Volume event only signals a change: GetVolume gives the value. The
    Office TV (Sony XR-65X90J) events 6 while GetVolume and its screen say 2."""
    rig = Rig()
    reads = []

    async def get_volume(udn):
        reads.append(udn)
        return 2

    rig.manager.get_volume = get_volume
    await rig.healthy_rig()  # initial RC event says 30
    await rig.notify_rc(Volume={"Master": 6})
    assert await _until(lambda: rig.events.snapshot(UDN).volume == 2)
    assert reads and set(reads) == {UDN}


async def test_evented_volume_falls_back_to_the_event_when_read_back_fails():
    rig = Rig()

    async def get_volume(udn):
        raise OSError("unreachable")

    rig.manager.get_volume = get_volume
    await rig.healthy_rig()
    await rig.notify_rc(Volume={"Master": 45})
    assert await _until(lambda: rig.events.snapshot(UDN).volume == 45)

    async def no_answer(udn):
        return None

    rig.manager.get_volume = no_answer
    await rig.notify_rc(Volume={"Master": 40})
    assert await _until(lambda: rig.events.snapshot(UDN).volume == 40)


async def test_evented_volume_newest_read_back_wins():
    """Read-backs finish out of order: a slow one for an older event never
    overwrites the newer event's value."""
    rig = Rig()
    release_first = asyncio.Event()
    calls = 0

    async def get_volume(udn):
        nonlocal calls
        calls += 1
        if calls == 1:
            await release_first.wait()
            return 10
        return 20

    await rig.healthy_rig()
    rig.manager.get_volume = get_volume
    await rig.notify_rc(Volume={"Master": 11})
    await rig.notify_rc(Volume={"Master": 21})
    assert await _until(lambda: rig.events.snapshot(UDN).volume == 20)
    release_first.set()
    await _until(lambda: calls >= 2)
    await _REAL_SLEEP(0.05)
    assert rig.events.snapshot(UDN).volume == 20


async def test_seek_and_pause_reach_a_device_that_names_its_actions_its_own_way():
    """Sonos events CurrentTransportActions without a plain "Seek" (it lists
    X_DLNA_SeekTime). Once events fill that list in, DmrDevice's own seek
    helper silently does nothing; Jamarr sends the action regardless."""
    from app.services.upnp.device import UPnPDeviceControl

    rig = Rig()
    await rig.healthy_rig()
    await rig.notify_avt(CurrentTransportActions="Set, Stop, Pause, Play, X_DLNA_SeekTime, Next")
    dmr = rig.manager.dmr_devices[UDN]
    assert not dmr._can_transport_action("seek")  # the library's gate is shut

    manager = SimpleNamespace(
        active_renderer=UDN, dmr_devices=rig.manager.dmr_devices, log=lambda _msg: None
    )
    avt_url = dmr._service("AVT").control_url
    rig.requester.soap[(avt_url, "Seek")] = {}
    rig.requester.soap[(avt_url, "Pause")] = {}
    rig.requester.soap[(avt_url, "Stop")] = {}
    rig.requester.soap_calls.clear()
    await UPnPDeviceControl(manager).seek(54.76)
    await UPnPDeviceControl(manager).pause()
    # Clearing the queue stops the device (it used to only pause it: the
    # backend called a control.stop() that did not exist).
    await UPnPDeviceControl(manager).stop()
    assert [action for _url, action in rig.requester.soap_calls] == ["Seek", "Pause", "Stop"]
    await rig.events.stop()


def test_seek_target_is_upnp_rel_time():
    from app.services.upnp.device import _rel_time

    assert _rel_time(54.76) == "0:00:54"
    assert _rel_time(3725) == "1:02:05"
    assert _rel_time(-3) == "0:00:00"


async def test_evented_mute_expires_with_the_subscription():
    """Mute last evented is only the device's state while RenderingControl
    events are healthy: not once they lapse, nor after the drop."""
    rig = Rig()
    await rig.healthy_rig()
    await rig.notify_rc(Mute="1")
    assert rig.events.muted(UDN) is True
    muted, evented_at = rig.events.muted_state(UDN)
    assert muted is True and evented_at == pytest.approx(time.time(), abs=5)

    # Unrenewed past its expiry: unhealthy, so no evented mute.
    rig.clock.advance(10_000)
    assert not rig.events.rc_healthy(UDN)
    assert rig.events.muted(UDN) is None
    assert rig.events.muted_state(UDN) is None

    await rig.events.drop(UDN)
    st = rig.events._renderers[UDN]
    assert st.muted is None and st.muted_at is None
    await rig.events.stop()


# --- monitor integration ----------------------------------------------------

_REAL_SLEEP = asyncio.sleep


class EventedUpnp:
    """UPnP manager fake whose device answers polls from mutable state and
    whose events go through a real UpnpEventManager."""

    def __init__(self, rig: Rig) -> None:
        self.rig = rig
        self.events = rig.events
        self.renderers = {}
        self.base_url = "http://10.0.0.1:8111"
        self.renderer_base_url = "http://10.0.0.1:8112"
        self.position = 60
        self.transport = "PLAYING"
        self.track_uri = URI_A
        self.position_calls = 0
        self.transport_calls = 0
        self.volume_calls = 0
        self.set_next_calls: list[tuple[int, str]] = []
        self.play_calls: list[int] = []
        self._polled_uri = None

    async def get_position(self, udn):
        self.position_calls += 1
        self._polled_uri = self.track_uri
        return self.position, 180

    async def get_transport_info(self, udn):
        self.transport_calls += 1
        return self.transport

    def current_track_uri(self, udn):
        return self._polled_uri

    def next_track_staging_allowed(self, udn):
        return staging_allowed(udn, True)

    async def set_next_track(self, udn, track_id, metadata):
        self.set_next_calls.append((track_id, metadata["stream_url"]))
        return metadata["stream_url"]

    async def clear_next_track(self, udn):
        staging.cleared(udn, ok=True)

    async def play_track(self, track_id, track_path, metadata):
        self.play_calls.append(track_id)

    async def get_volume(self, udn):
        self.volume_calls += 1
        return None


def _reset(udn):
    for store in (
        last_playing_seen,
        last_playing_position,
        start_retries,
        last_stop_reason,
        monitor_module._prewarmed_index,
        monitor_module._staged_stop_seen,
    ):
        store.pop(udn, None)
    staging.reset(udn)


def _queue(ids, duration=180):
    return [
        {
            "id": track_id,
            "title": f"Track {track_id}",
            "artist": "Artist",
            "album": "Album",
            "path": f"/music/{track_id}.flac",
            "duration_seconds": duration,
        }
        for track_id in ids
    ]


@pytest.fixture
def monitor_harness(monkeypatch):
    async def scaled(delay, *args, **kwargs):
        await _REAL_SLEEP(min(delay, 0.001))

    monkeypatch.setattr(monitor_module.asyncio, "sleep", scaled)
    monkeypatch.setattr(monitor_module, "track_path_exists", lambda track: True)
    monkeypatch.setattr(app_config, "_config", {"renderer": {}})

    real_wait = UpnpEventManager.wait_for_change

    async def quick_wait(self, udn, seen, timeout):
        return await real_wait(self, udn, seen, min(timeout, 0.01))

    monkeypatch.setattr(UpnpEventManager, "wait_for_change", quick_wait)

    calls = SimpleNamespace(advances=[], history=[])

    async def fake_advance(udn):
        calls.advances.append(udn)
        last_track_start_time[udn] = time.time()

    async def fake_history(db, track_id, **kwargs):
        calls.history.append(track_id)

    monkeypatch.setattr(monitor_module, "play_next_track_internal", fake_advance)
    monkeypatch.setattr(monitor_module, "log_history", fake_history)
    yield calls
    staging.reset()


async def _until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if inspect.isawaitable(result):
            result = await result
        if result:
            return True
        await _REAL_SLEEP(0.01)
    raise AssertionError("condition not reached")


async def _start_monitor(monkeypatch, udn, upnp):
    monkeypatch.setattr(monitor_module.UPnPManager, "get_instance", lambda: upnp)
    return asyncio.create_task(monitor_module.monitor_upnp_playback(udn))


async def _stop(task):
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def test_monitor_follows_a_staged_transition_by_event(db, monkeypatch, monitor_harness):
    """Healthy events: transport is polled only as a watchdog, and the
    renderer rolling into the staged track is seen from the TrackURI event."""
    udn = "uuid:evt-monitor-0001"
    _reset(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(
        db,
        udn,
        {"queue": _queue([900, 901, 902]), "current_index": 0, "position_seconds": 0,
         "is_playing": True, "transport_state": "PLAYING", "volume": 20},
    )
    rig = Rig()
    rig.events._clock = time.monotonic
    await rig.add(udn)
    upnp = EventedUpnp(rig)
    task = await _start_monitor(monkeypatch, udn, upnp)
    try:
        await _until(lambda: len(rig.gena.active) == 2)
        await rig.notify_avt(TransportState="PLAYING", CurrentTrackURI=URI_A)
        await rig.notify_rc(Volume={"Master": 20}, Mute="0")
        await _until(lambda: upnp.set_next_calls)  # staged 901
        staged_url = upnp.set_next_calls[0][1]
        assert rig.events.rc_healthy(udn)
        transport_before = upnp.transport_calls
        positions_before = upnp.position_calls
        volume_before = upnp.volume_calls
        await _REAL_SLEEP(0.3)  # dozens of loops at the test's idle scale
        # Watchdog only: no per-loop transport polls, position not every loop,
        # and volume arrives by event instead of the periodic GetVolume.
        assert upnp.transport_calls - transport_before <= 1
        assert upnp.position_calls - positions_before <= 2
        assert upnp.volume_calls == volume_before

        # The renderer moves on by itself and says so by event.
        upnp.position = 1
        upnp.track_uri = staged_url
        await rig.notify_avt(CurrentTrackURI=staged_url)

        async def advanced():
            async with db_conn() as conn:
                return (await get_renderer_state_db(conn, udn))["current_index"] == 1

        await _until(advanced, timeout=2.0)
        assert upnp.play_calls == []  # not reloaded
        assert monitor_harness.advances == []
    finally:
        await _stop(task)
        await rig.events.stop()


async def test_monitor_falls_back_to_polling_when_events_drop_and_recovers(
    db, monkeypatch, monitor_harness
):
    udn = "uuid:evt-monitor-0002"
    _reset(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(
        db,
        udn,
        {"queue": _queue([900]), "current_index": 0, "position_seconds": 0,
         "is_playing": True, "transport_state": "PLAYING", "volume": 20},
    )
    rig = Rig()
    await rig.add(udn)
    upnp = EventedUpnp(rig)
    task = await _start_monitor(monkeypatch, udn, upnp)
    try:
        await _until(lambda: len(rig.gena.active) == 2)
        await rig.notify_avt(TransportState="PLAYING", CurrentTrackURI=URI_A)
        await _until(lambda: rig.events.avt_healthy(udn))
        await _REAL_SLEEP(0.1)
        before = upnp.transport_calls
        await _REAL_SLEEP(0.2)
        assert upnp.transport_calls - before <= 1  # event mode

        # Subscription lapses (device unreachable at renewal).
        rig.gena.offline = True
        rig.clock.advance(301)
        rig.events._renderers[udn].kick.set()
        await _until(lambda: not rig.events.avt_healthy(udn))
        before = upnp.transport_calls
        await _REAL_SLEEP(0.2)
        assert upnp.transport_calls - before >= 5  # back to polling every loop

        # Device back: re-subscribed after the backoff, healthy on its event.
        rig.gena.offline = False
        rig.gena.active.clear()
        rig.clock.advance(10)
        rig.events._renderers[udn].kick.set()
        await _until(lambda: len(rig.gena.active) == 2)
        await rig.notify_avt(TransportState="PLAYING", CurrentTrackURI=URI_A)
        await _until(lambda: rig.events.avt_healthy(udn))
        await _REAL_SLEEP(0.1)
        before = upnp.transport_calls
        await _REAL_SLEEP(0.2)
        assert upnp.transport_calls - before <= 1
    finally:
        await _stop(task)
        await rig.events.stop()


async def test_monitor_sees_a_remote_pause_by_event(db, monkeypatch, monitor_harness):
    udn = "uuid:evt-monitor-0003"
    _reset(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(
        db,
        udn,
        {"queue": _queue([900]), "current_index": 0, "position_seconds": 0,
         "is_playing": True, "transport_state": "PLAYING", "volume": 20},
    )
    rig = Rig()
    rig.events._clock = time.monotonic
    await rig.add(udn)
    upnp = EventedUpnp(rig)
    task = await _start_monitor(monkeypatch, udn, upnp)
    try:
        await _until(lambda: len(rig.gena.active) == 2)
        await rig.notify_avt(TransportState="PLAYING", CurrentTrackURI=URI_A)
        await _until(lambda: rig.events.avt_healthy(udn))
        await _REAL_SLEEP(0.1)
        transport_before = upnp.transport_calls
        upnp.transport = "PAUSED_PLAYBACK"
        await rig.notify_avt(TransportState="PAUSED_PLAYBACK")

        async def paused():
            async with db_conn() as conn:
                state = await get_renderer_state_db(conn, udn)
            return state["transport_state"] == "PAUSED_PLAYBACK" and not state["is_playing"]

        await _until(paused, timeout=2.0)
        assert upnp.transport_calls - transport_before <= 1
    finally:
        await _stop(task)
        await rig.events.stop()


async def test_monitor_without_event_support_polls_as_before(db, monkeypatch, monitor_harness):
    """A renderer refusing SUBSCRIBE stays on 1 s polling, unchanged."""
    udn = "uuid:evt-monitor-0004"
    _reset(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(
        db,
        udn,
        {"queue": _queue([900]), "current_index": 0, "position_seconds": 0,
         "is_playing": True, "transport_state": "PLAYING", "volume": 20},
    )
    rig = Rig()
    rig.gena.refuse = 501
    await rig.add(udn)
    upnp = EventedUpnp(rig)
    task = await _start_monitor(monkeypatch, udn, upnp)
    try:
        await _REAL_SLEEP(0.2)
        assert upnp.transport_calls >= 5
        assert rig.events.supports_events(udn) is False
    finally:
        await _stop(task)
        await rig.events.stop()


def test_events_module_constants_are_sane():
    assert events_module.RENEW_MARGIN_S < events_module.SUBSCRIBE_TIMEOUT_S
    assert monitor_module.EVENT_POSITION_POLL_S < monitor_module.EVENT_TRANSPORT_POLL_S


async def test_reader_repolls_position_after_a_seek_instead_of_extrapolating():
    """Between watchdog polls the reader extrapolates position; a seek (via
    the UPnP backend) must make the next read poll the device again, so
    progress, near-end staging and history never see the pre-seek place."""
    from app.services.renderer.upnp_backend import UpnpRendererBackend
    from tests.helpers.fake_renderers import FakeUpnpManager

    rig = Rig()
    await rig.healthy_rig()
    upnp = EventedUpnp(rig)
    upnp.position = 150
    reader = monitor_module._DeviceReader(upnp, UDN)

    position, state, _ = await reader.read()
    assert (position, state, upnp.position_calls) == (150, "PLAYING", 1)
    position, _, _ = await reader.read()
    assert upnp.position_calls == 1 and position >= 150  # extrapolated

    # The listener seeks back to 10 s; the device is there now.
    await UpnpRendererBackend(FakeUpnpManager()).seek(f"upnp:{UDN}", 10)
    upnp.position = 10
    position, _, _ = await reader.read()
    assert (position, upnp.position_calls) == (10, 2)
    # Then back to extrapolating, from the post-seek baseline.
    position, _, _ = await reader.read()
    assert upnp.position_calls == 2 and 10 <= position < 150
    await rig.events.stop()
