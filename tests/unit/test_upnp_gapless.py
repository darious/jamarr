"""UPnP next-track staging (SetNextAVTransportURI) and TrackURI-based
transition reconciliation in the playback monitor.

Devices are in-memory fakes; nothing here touches the network.
"""

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.services.upnp.protocol_info import SEEKABLE_ADDITIONAL_INFO
from async_upnp_client.exceptions import UpnpActionError, UpnpConnectionError

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
from app.services.renderer.contracts import RendererStatus
from app.services.renderer.token_policy import staged_stream_token_ttl_seconds
from app.services.renderer.upnp_backend import UpnpRendererBackend
from app.services.upnp import staging as staging_module
from app.services.upnp.device import UPnPDeviceControl
from app.services.upnp.staging import (
    MAX_STAGED_MISSES,
    StagedTrack,
    same_media_uri,
    staging,
    staging_allowed,
)

_REAL_SLEEP = asyncio.sleep
CURRENT_URI = "http://10.0.0.1:8111/api/stream/900?token=current"


def staged(n):
    """Script marker: the URI passed to the n-th SetNextAVTransportURI call."""
    return ("staged", n)


class GaplessUpnp:
    """UPnP manager fake with next-track staging.

    The script is a list of (position, transport_state, track_uri) polls; the
    last entry repeats forever and ``drained`` fires once it is reached.
    ``hooks[i]`` runs (awaited) when poll i is served, to edit the queue at a
    precise point in the transition.
    """

    def __init__(
        self,
        script,
        *,
        advertised=True,
        set_next_error=None,
        fail_after=0,
        clear_ok=True,
        hooks=None,
    ):
        self.script = list(script)
        self.index = 0
        self.advertised = advertised
        # set_next_error is raised once fail_after SetNext calls succeeded.
        self.set_next_error = set_next_error
        self.fail_after = fail_after
        # False: the renderer refuses an empty NextURI.
        self.clear_ok = clear_ok
        self.hooks = dict(hooks or {})
        self.drained = asyncio.Event()
        self.renderers = {}
        self.base_url = "http://10.0.0.1:8111"
        self.renderer_base_url = "http://10.0.0.1:8112"
        self.set_next_calls = []  # (track_id, url, metadata)
        self.clear_calls = 0
        self.play_calls = []
        self.stop_calls = 0
        self.stopped = False
        self._entry = self.script[0]

    def _resolve(self, uri):
        if isinstance(uri, tuple) and uri[0] == "staged":
            n = uri[1]
            return self.set_next_calls[n][1] if n < len(self.set_next_calls) else None
        return uri

    async def get_position(self, udn):
        i = min(self.index, len(self.script) - 1)
        hook = self.hooks.pop(i, None)
        if hook is not None:
            await hook()
        self._entry = (0, "STOPPED", None) if self.stopped else self.script[i]
        return self._entry[0], 0

    async def get_transport_info(self, udn):
        self.index += 1
        if self.index >= len(self.script):
            self.drained.set()
        return self._entry[1]

    def current_track_uri(self, udn):
        return self._resolve(self._entry[2])

    def next_track_staging_allowed(self, udn):
        return staging_allowed(udn, self.advertised)

    async def set_next_track(self, udn, track_id, metadata):
        if self.set_next_error is not None and len(self.set_next_calls) >= self.fail_after:
            self.set_next_calls.append((track_id, None, metadata))
            raise self.set_next_error
        url = metadata["stream_url"]
        self.set_next_calls.append((track_id, url, metadata))
        return url

    async def clear_next_track(self, udn):
        self.clear_calls += 1
        staging.cleared(udn, ok=self.clear_ok)

    async def play_track(self, track_id, track_path, metadata):
        self.play_calls.append(track_id)

    async def stop_renderer(self, udn):
        self.stop_calls += 1
        self.stopped = True

    async def get_volume(self, udn):
        return None

    @property
    def staged_ids(self):
        return [call[0] for call in self.set_next_calls]


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


def _state(ids=(900, 901, 902), duration=180):
    return {
        "queue": _queue(ids, duration),
        "current_index": 0,
        "position_seconds": 0,
        "is_playing": True,
        "transport_state": "PLAYING",
        "volume": 20,
    }


@pytest.fixture
def harness(monkeypatch):
    real_sleep = asyncio.sleep

    async def scaled(delay, *args, **kwargs):
        await real_sleep(min(delay, 0.001))

    monkeypatch.setattr(monitor_module.asyncio, "sleep", scaled)
    # Queue items point at files that do not exist in the test container.
    monkeypatch.setattr(monitor_module, "track_path_exists", lambda track: True)
    # No config.yaml overrides unless a test sets them.
    monkeypatch.setattr(app_config, "_config", {"renderer": {}})

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


async def _run(monkeypatch, udn, upnp, timeout=5.0):
    monkeypatch.setattr(monitor_module.UPnPManager, "get_instance", lambda: upnp)
    task = asyncio.create_task(monitor_module.monitor_upnp_playback(udn))
    try:
        await asyncio.wait_for(upnp.drained.wait(), timeout=timeout)
        await _REAL_SLEEP(0.3)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _set_queue_ids(udn, ids):
    async with db_conn() as conn:
        state = await get_renderer_state_db(conn, udn)
        by_id = {t["id"]: t for t in state["queue"]}
        state["queue"] = [by_id.get(i) or _queue([i])[0] for i in ids]
        await update_renderer_state_db(conn, udn, state)


# --- monitor: staging and transitions ---------------------------------------


async def test_staged_transition_under_playing_advances_exactly_once(
    db, monkeypatch, harness
):
    """The renderer rolls into the staged URI without ever reporting STOPPED:
    the queue and history move on once, and nothing is reloaded."""
    udn = "uuid:gapless-transition"
    _reset(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = GaplessUpnp(
        [
            (60, "PLAYING", CURRENT_URI),  # stage 901
            (120, "PLAYING", CURRENT_URI),
            (178, "PLAYING", CURRENT_URI),
            (1, "PLAYING", staged(0)),  # renderer is now playing 901
            (2, "PLAYING", staged(0)),
            (15, "PLAYING", staged(0)),  # stage 902
            (40, "PLAYING", staged(0)),  # 901 passes the history threshold
        ]
    )
    await _run(monkeypatch, udn, upnp)

    state = await get_renderer_state_db(db, udn)
    assert state["current_index"] == 1
    assert state["is_playing"] is True
    assert upnp.play_calls == []  # never reloaded the started track
    assert harness.advances == []  # STOPPED fallback never involved
    assert upnp.staged_ids == [901, 902]
    assert harness.history == [900, 901]  # each track logged exactly once
    assert staging.get(udn).track_id == 902


async def test_staged_url_is_a_valid_long_lived_stream_url(db, monkeypatch, harness):
    udn = "uuid:gapless-url"
    _reset(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = GaplessUpnp([(60, "PLAYING", CURRENT_URI), (61, "PLAYING", CURRENT_URI)])
    await _run(monkeypatch, udn, upnp)

    track_id, url, metadata = upnp.set_next_calls[0]
    assert track_id == 901
    # Via the renderer proxy, with a token bound to the staged track.
    assert url.startswith("http://10.0.0.1:8112/api/stream/901?token=")
    from app.auth_tokens import verify_stream_token

    claims = verify_stream_token(url.split("token=", 1)[1], 901)
    assert "loudness_gain_mode" in claims
    record = staging.get(udn)
    # Covers the rest of the current track plus the staged one, with margin.
    assert record.expires_at - record.staged_at >= 120 + 180
    assert metadata["stream_url"] == url


async def test_paused_on_staged_track_still_reconciles(db, monkeypatch, harness):
    """A renderer that reports PAUSED_PLAYBACK once it is on the staged track
    has still moved on; the queue follows and shows it paused."""
    udn = "uuid:gapless-paused"
    _reset(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = GaplessUpnp(
        [
            (60, "PLAYING", CURRENT_URI),
            (178, "PLAYING", CURRENT_URI),
            (0, "PAUSED_PLAYBACK", staged(0)),
        ]
    )
    await _run(monkeypatch, udn, upnp)

    state = await get_renderer_state_db(db, udn)
    assert state["current_index"] == 1
    assert state["is_playing"] is False
    assert upnp.play_calls == []
    assert harness.advances == []


async def test_queue_reorder_restages_the_new_next_track(db, monkeypatch, harness):
    udn = "uuid:gapless-reorder"
    _reset(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = GaplessUpnp(
        [
            (60, "PLAYING", CURRENT_URI),  # stage 901
            (170, "PLAYING", CURRENT_URI),  # user moves 902 up: re-stage
            (175, "PLAYING", CURRENT_URI),
            (1, "PLAYING", staged(1)),  # renderer rolls into 902
            (2, "PLAYING", staged(1)),
        ],
        hooks={1: lambda: _set_queue_ids(udn, [900, 902, 901])},
    )
    await _run(monkeypatch, udn, upnp)

    assert upnp.staged_ids == [901, 902]
    state = await get_renderer_state_db(db, udn)
    assert state["current_index"] == 1
    assert state["queue"][1]["id"] == 902
    assert upnp.play_calls == []
    assert harness.advances == []


async def test_queue_truncated_clears_the_staged_next(db, monkeypatch, harness):
    udn = "uuid:gapless-truncate"
    _reset(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = GaplessUpnp(
        [(60, "PLAYING", CURRENT_URI), (90, "PLAYING", CURRENT_URI), (91, "PLAYING", CURRENT_URI)],
        hooks={1: lambda: _set_queue_ids(udn, [900])},
    )
    await _run(monkeypatch, udn, upnp)

    assert upnp.staged_ids == [901]
    assert upnp.clear_calls == 1
    assert staging.get(udn) is None


async def test_edit_racing_the_transition_loads_the_right_track(
    db, monkeypatch, harness
):
    """The renderer already started the old staged track when the queue edit
    landed: Jamarr loads the track that is actually next instead of letting
    the dropped one play on, and does so once."""
    udn = "uuid:gapless-stale"
    _reset(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = GaplessUpnp(
        [
            (60, "PLAYING", CURRENT_URI),  # stage 901
            (178, "PLAYING", CURRENT_URI),
            (1, "PLAYING", staged(0)),  # 901 started... but it was just removed
            (2, "PLAYING", staged(0)),
        ],
        hooks={2: lambda: _set_queue_ids(udn, [900, 902])},
    )
    await _run(monkeypatch, udn, upnp)

    assert harness.advances == [udn]  # play_next_track_internal -> 902
    state = await get_renderer_state_db(db, udn)
    assert state["current_index"] == 0  # the helper (stubbed) owns the move


async def test_edit_racing_the_transition_at_queue_end_stops(db, monkeypatch, harness):
    udn = "uuid:gapless-stale-end"
    _reset(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = GaplessUpnp(
        [
            (60, "PLAYING", CURRENT_URI),
            (178, "PLAYING", CURRENT_URI),
            (1, "PLAYING", staged(0)),
        ],
        hooks={2: lambda: _set_queue_ids(udn, [900])},
    )
    await _run(monkeypatch, udn, upnp)

    assert harness.advances == []
    assert upnp.stop_calls == 1
    assert upnp.play_calls == []  # the stop is not mistaken for a failed start
    state = await get_renderer_state_db(db, udn)
    assert state["is_playing"] is False


async def test_set_next_fault_disables_staging_and_falls_back(db, monkeypatch, harness):
    """Advertised support is provisional: a SOAP fault switches staging off for
    the renderer and the STOPPED-based advance carries on as before."""
    udn = "uuid:gapless-fault"
    _reset(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = GaplessUpnp(
        [
            (60, "PLAYING", CURRENT_URI),
            (120, "PLAYING", CURRENT_URI),
            (174, "PLAYING", CURRENT_URI),
            (0, "STOPPED", CURRENT_URI),
        ],
        set_next_error=UpnpActionError(error_code=401, error_desc="Invalid Action"),
    )
    await _run(monkeypatch, udn, upnp)

    assert upnp.staged_ids == [901]  # tried once, never again
    assert staging.is_disabled(udn)
    assert harness.advances == [udn]


async def test_transient_failures_disable_only_after_repeats(db, monkeypatch, harness):
    udn = "uuid:gapless-transient"
    _reset(udn)
    exc = UpnpConnectionError("timed out")
    staging.note_failure(udn, exc)
    staging.note_failure(udn, exc)
    assert not staging.is_disabled(udn)
    staging.note_failure(udn, exc)
    assert staging.is_disabled(udn)


async def test_staged_renderer_that_stops_falls_back_after_grace(
    db, monkeypatch, harness
):
    """Accepting SetNext is not proof of playing it. A renderer that stops at
    the end anyway gets the next track loaded after a short grace; repeated
    misses switch staging off."""
    udn = "uuid:gapless-miss"
    _reset(udn)
    monkeypatch.setattr(monitor_module, "STAGED_STOP_GRACE_S", 0.05)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = GaplessUpnp(
        [
            (60, "PLAYING", CURRENT_URI),
            (174, "PLAYING", CURRENT_URI),
            (0, "STOPPED", CURRENT_URI),
        ]
    )
    await _run(monkeypatch, udn, upnp)

    assert upnp.staged_ids == [901]
    assert harness.advances == [udn]  # exactly one fallback load
    assert staging.get(udn) is None
    assert not staging.is_disabled(udn)  # one miss is not yet a verdict
    for _ in range(MAX_STAGED_MISSES - 1):
        staging.note_staged_miss(udn)
    assert staging.is_disabled(udn)


async def test_config_override_turns_staging_off(db, monkeypatch, harness):
    udn = "uuid:gapless-override-off"
    _reset(udn)
    monkeypatch.setattr(
        app_config,
        "_config",
        {"renderer": {"upnp_gapless": {"disabled_udns": ["UUID:GAPLESS-OVERRIDE-OFF"]}}},
    )
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = GaplessUpnp(
        [(60, "PLAYING", CURRENT_URI), (174, "PLAYING", CURRENT_URI), (0, "STOPPED", CURRENT_URI)]
    )
    await _run(monkeypatch, udn, upnp)

    assert upnp.set_next_calls == []
    assert harness.advances == [udn]


async def test_non_gapless_renderer_is_unchanged(db, monkeypatch, harness):
    """No advert, no override: no SetNext calls, STOPPED drives the queue."""
    udn = "uuid:gapless-none"
    _reset(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = GaplessUpnp(
        [
            (60, "PLAYING", CURRENT_URI),
            (172, "PLAYING", CURRENT_URI),
            (174, "PLAYING", CURRENT_URI),
            (0, "STOPPED", CURRENT_URI),
        ],
        advertised=False,
    )
    await _run(monkeypatch, udn, upnp)

    assert upnp.set_next_calls == []
    assert upnp.clear_calls == 0
    assert harness.advances == [udn]


async def test_no_staging_without_a_reported_track_uri(db, monkeypatch, harness):
    """A renderer that never reports TrackURI could not be followed into the
    staged track, so it is not given one."""
    udn = "uuid:gapless-no-uri"
    _reset(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = GaplessUpnp([(60, "PLAYING", None), (61, "PLAYING", None)])
    await _run(monkeypatch, udn, upnp)

    assert upnp.set_next_calls == []


async def test_fault_on_restage_clears_old_uri_and_still_recognises_it(
    db, monkeypatch, harness
):
    """Re-staging after a queue edit faults, which switches staging off. The
    device still holds the old staged URI: it is cleared anyway, and if the
    renderer rolls into it regardless, the queue is put right instead of
    silently falling a track behind."""
    udn = "uuid:gapless-fault-restage"
    _reset(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = GaplessUpnp(
        [
            (60, "PLAYING", CURRENT_URI),  # stage 901
            (120, "PLAYING", CURRENT_URI),  # 902 moved up: re-stage faults
            (178, "PLAYING", CURRENT_URI),
            (1, "PLAYING", staged(0)),  # renderer plays the dropped 901
            (2, "PLAYING", staged(0)),
        ],
        set_next_error=UpnpActionError(error_code=401, error_desc="Invalid Action"),
        fail_after=1,
        clear_ok=False,
        hooks={1: lambda: _set_queue_ids(udn, [900, 902, 901])},
    )
    await _run(monkeypatch, udn, upnp)

    assert upnp.staged_ids == [901, 902]
    assert staging.is_disabled(udn)
    assert upnp.clear_calls == 1  # issued although staging was just disabled
    # 901 is no longer next: load the track that is (stubbed helper), once.
    assert harness.advances == [udn]
    assert staging.dropped.get(udn) is None


async def test_unplayable_next_clears_and_refused_clear_is_still_recognised(
    db, monkeypatch, harness
):
    udn = "uuid:gapless-missing-next"
    _reset(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    def missing_902(track):
        return track.get("id") != 902

    async def move_missing_track_up():
        monkeypatch.setattr(monitor_module, "track_path_exists", missing_902)
        await _set_queue_ids(udn, [900, 902, 901])

    upnp = GaplessUpnp(
        [
            (60, "PLAYING", CURRENT_URI),  # stage 901
            (120, "PLAYING", CURRENT_URI),  # next is now 902, not on disk
            (178, "PLAYING", CURRENT_URI),
            (1, "PLAYING", staged(0)),  # renderer plays the dropped 901
            (2, "PLAYING", staged(0)),
        ],
        clear_ok=False,
        hooks={1: move_missing_track_up},
    )
    await _run(monkeypatch, udn, upnp)

    assert upnp.staged_ids == [901]
    assert upnp.clear_calls == 1
    assert harness.advances == [udn]


async def test_rolling_into_a_dropped_uri_that_is_still_next_advances(
    db, monkeypatch, harness
):
    """Staging was switched off with a URI already on the device, and the
    track behind it is still next: the transition is simply followed."""
    udn = "uuid:gapless-dropped-next"
    _reset(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())
    url = "http://10.0.0.1:8112/api/stream/901?token=dropped"
    staging.record(udn, StagedTrack(1, 901, url, time.time()))
    staging.disable(udn, "test")
    assert staging.get(udn) is None
    assert staging.dropped[udn].track_id == 901

    upnp = GaplessUpnp([(1, "PLAYING", url), (2, "PLAYING", url)], clear_ok=False)
    await _run(monkeypatch, udn, upnp)

    state = await get_renderer_state_db(db, udn)
    assert state["current_index"] == 1
    assert harness.advances == []
    assert upnp.play_calls == []
    assert upnp.clear_calls == 1  # disabled, but the device is still told


def test_staging_keeps_dropped_records_until_cleared_or_replaced():
    udn = "uuid:dropped-bookkeeping"
    staging.reset(udn)
    first = StagedTrack(1, 7, "http://x/api/stream/7?token=a", time.time())
    staging.record(udn, first)
    staging.forget(udn)
    assert staging.dropped[udn] is first
    assert udn in staging.needs_clear
    staging.cleared(udn, ok=False)  # refused: still recognisable
    assert staging.dropped[udn] is first
    assert udn not in staging.needs_clear  # but not retried every poll
    staging.record(udn, StagedTrack(1, 8, "http://x/api/stream/8?token=b", time.time()))
    assert udn not in staging.dropped  # SetNext replaced it on the device
    staging.forget(udn)
    staging.cleared(udn, ok=True)
    assert udn not in staging.dropped
    staging.reset(udn)


# --- policy and helpers ------------------------------------------------------


def test_gapless_override_config(monkeypatch):
    monkeypatch.setattr(
        app_config,
        "_config",
        {
            "renderer": {
                "upnp_gapless": {
                    "disabled_udns": ["uuid:AAA"],
                    "forced_udns": ["bbb"],
                }
            }
        },
    )
    assert app_config.upnp_gapless_override("uuid:aaa") == "off"
    assert app_config.upnp_gapless_override("aaa") == "off"
    assert app_config.upnp_gapless_override("uuid:bbb") == "on"
    assert app_config.upnp_gapless_override("uuid:ccc") is None

    monkeypatch.setattr(
        app_config, "_config", {"renderer": {"upnp_gapless": {"enabled": False, "forced_udns": ["bbb"]}}}
    )
    assert app_config.upnp_gapless_override("uuid:bbb") == "off"


def test_staging_allowed_precedence(monkeypatch):
    udn = "uuid:policy"
    staging.reset(udn)
    monkeypatch.setattr(app_config, "_config", {"renderer": {"upnp_gapless": {"forced_udns": [udn]}}})
    assert staging_allowed(udn, advertised=False) is True
    staging.disable(udn, "test")
    assert staging_allowed(udn, advertised=True) is False  # faults beat force
    staging.reset(udn)
    monkeypatch.setattr(app_config, "_config", {"renderer": {}})
    assert staging_allowed(udn, advertised=True) is True
    assert staging_allowed(udn, advertised=False) is False


def test_same_media_uri():
    url = "http://10.0.0.1:8112/api/stream/5?token=abc.def"
    assert same_media_uri(url, url)
    assert same_media_uri(url.replace("?", "?x=1&amp;"), url)
    assert same_media_uri("http://other-host:9/api/stream/5?token=abc.def", url)
    assert not same_media_uri("http://10.0.0.1:8112/api/stream/5?token=zzz", url)
    assert not same_media_uri(None, url)
    assert not same_media_uri("", url)


def test_staged_token_ttl_covers_lead_and_track():
    assert staged_stream_token_ttl_seconds(100, 200) == 1800  # floor
    assert staged_stream_token_ttl_seconds(1200, 900) == 3000
    assert staged_stream_token_ttl_seconds(10**6, 10**6) == 86400  # cap


# --- device control ----------------------------------------------------------


class FakeDmr:
    def __init__(self, advertised=True):
        self.has_next_transport_uri = advertised
        self.set_uri_calls = []
        self.set_next_calls = []

    async def async_set_transport_uri(self, media_url, media_title, meta_data):
        self.set_uri_calls.append(media_url)

    async def async_set_next_transport_uri(self, media_url, media_title, meta_data):
        self.set_next_calls.append({"media_url": media_url, "meta_data": meta_data})

    async def async_wait_for_can_play(self, max_wait_time=5):
        pass

    async def async_play(self):
        pass


def _control(udn, dmr, mimes="audio/x-flac"):
    manager = SimpleNamespace(
        active_renderer=udn,
        dmr_devices={udn: dmr},
        renderers={udn: {"friendly_name": "Amp", "supported_mime_types": mimes}},
        base_url="http://10.0.0.1:8111",
        renderer_base_url="http://10.0.0.1:8112",
    )
    return UPnPDeviceControl(manager)


async def test_set_next_track_sends_the_same_didl_as_a_load():
    udn = "uuid:device-next"
    staging.reset(udn)
    dmr = FakeDmr()
    control = _control(udn, dmr)
    meta = {
        "title": "Next",
        "artist": "Artist",
        "album": "Album",
        "mime": "audio/flac",
        "duration_seconds": 181,
        "art_sha1": "cafe",
        "stream_url": "http://10.0.0.1:8112/api/stream/7?token=t",
    }

    url = await control.set_next_track(udn, 7, meta)

    # Relabelled to the advertised alias: the URL asks /api/stream to serve
    # the same name, and still matches the plain URL by its stream token.
    assert url == meta["stream_url"] + "&mime=audio%2Fx-flac"
    assert same_media_uri(meta["stream_url"], url)
    call = dmr.set_next_calls[0]
    assert call["media_url"] == url
    didl = call["meta_data"]
    assert f'protocolInfo="http-get:*:audio/x-flac:{SEEKABLE_ADDITIONAL_INFO}"' in didl  # as for SetAVTransportURI
    assert 'duration="0:03:01.000"' in didl
    assert "http://10.0.0.1:8112/art/file/cafe" in didl


async def test_loading_a_track_supersedes_the_staged_one():
    udn = "uuid:device-load"
    staging.reset(udn)
    dmr = FakeDmr()
    control = _control(udn, dmr)
    staging.record(udn, StagedTrack(1, 7, "http://x/api/stream/7?token=t", time.time()))

    await control.play_track(8, "/music/8.flac", {"stream_url": "http://x/api/stream/8?token=u"})

    assert staging.get(udn) is None
    assert udn in staging.needs_clear  # device may still hold the old next
    await control.clear_next_track(udn)
    assert dmr.set_next_calls == [{"media_url": "", "meta_data": ""}]
    assert udn not in staging.needs_clear
    await control.clear_next_track(udn)  # nothing staged: no device call
    assert len(dmr.set_next_calls) == 1


async def test_clear_tolerates_renderers_rejecting_empty_uri():
    udn = "uuid:device-clear-reject"
    staging.reset(udn)

    class Rejecting(FakeDmr):
        async def async_set_next_transport_uri(self, media_url, media_title, meta_data):
            raise UpnpActionError(error_code=402, error_desc="Invalid Args")

    control = _control(udn, Rejecting())
    staging.record(udn, StagedTrack(1, 7, "http://x/api/stream/7?token=t", time.time()))
    await control.clear_next_track(udn)
    assert staging.get(udn) is None
    assert not staging.is_disabled(udn)


async def test_clear_is_sent_even_when_staging_was_disabled():
    udn = "uuid:device-clear-disabled"
    staging.reset(udn)
    dmr = FakeDmr()
    control = _control(udn, dmr)
    staging.record(udn, StagedTrack(1, 7, "http://x/api/stream/7?token=t", time.time()))
    staging.disable(udn, "SetNextAVTransportURI fault")

    await control.clear_next_track(udn)

    assert dmr.set_next_calls == [{"media_url": "", "meta_data": ""}]
    assert udn not in staging.dropped
    staging.reset(udn)


def test_device_staging_allowed_uses_advert_and_override(monkeypatch):
    udn = "uuid:device-allowed"
    staging.reset(udn)
    monkeypatch.setattr(app_config, "_config", {"renderer": {}})
    assert _control(udn, FakeDmr(advertised=True)).next_track_staging_allowed(udn)
    assert not _control(udn, FakeDmr(advertised=False)).next_track_staging_allowed(udn)
    monkeypatch.setattr(
        app_config, "_config", {"renderer": {"upnp_gapless": {"forced_udns": [udn]}}}
    )
    assert _control(udn, FakeDmr(advertised=False)).next_track_staging_allowed(udn)


async def test_get_position_records_track_uri():
    udn = "uuid:device-trackuri"

    class Action:
        async def async_call(self, **kwargs):
            return {"RelTime": "0:00:05", "TrackDuration": "0:03:00", "TrackURI": "http://u"}

    dmr = SimpleNamespace(_action=lambda service, name: Action())
    control = _control(udn, dmr)
    assert await control.get_position(udn) == (5, 180)
    assert control.current_track_uri(udn) == "http://u"



async def test_get_position_reads_fractional_seconds():
    """Sony Bravias report RelTime with milliseconds. Reading that as 0 froze
    the position: nothing was ever staged, and every track end looked like a
    failed start that re-played the same track."""
    udn = "uuid:device-millis"

    class Action:
        async def async_call(self, **kwargs):
            return {"RelTime": "0:00:15.618", "TrackDuration": "0:01:14.760", "TrackURI": "http://u"}

    dmr = SimpleNamespace(_action=lambda service, name: Action())
    control = _control(udn, dmr)
    assert await control.get_position(udn) == (15, 74)

# --- renderer backend ----------------------------------------------------------


class BackendManager:
    def __init__(self):
        self.renderers = {"uuid:be": {"friendly_name": "Amp"}}
        self.cleared = []
        self.paused = False

    async def set_renderer(self, udn):
        self.active_renderer = udn

    async def get_position(self, udn):
        return 12, 180

    async def get_transport_info(self, udn):
        return "PLAYING"

    def current_track_uri(self, udn):
        return "http://10.0.0.1:8112/api/stream/1?token=a"

    async def clear_next_track(self, udn):
        self.cleared.append(udn)

    async def pause(self):
        self.paused = True


async def test_backend_status_carries_track_uri():
    backend = UpnpRendererBackend(manager=BackendManager())
    status = await backend.get_status("upnp:uuid:be")
    assert isinstance(status, RendererStatus)
    assert status.current_media_url == "http://10.0.0.1:8112/api/stream/1?token=a"


async def test_backend_stop_clears_staged_next():
    manager = BackendManager()
    backend = UpnpRendererBackend(manager=manager)
    await backend.stop_playback("upnp:uuid:be")
    assert manager.cleared == ["uuid:be"]
    assert manager.paused


def test_staging_module_singleton():
    assert staging_module.staging is staging
