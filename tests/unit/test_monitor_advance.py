"""Playback monitor auto-advance: position-based end/fail/stop classification,
transition guard, start retries, watchdog, prewarm."""

import asyncio
import time

import pytest

from app.services.player import monitor as monitor_module
from app.services.player.globals import (
    last_playing_position,
    last_playing_seen,
    last_stop_reason,
    last_track_start_time,
    start_retries,
)
from app.services.player.state import get_renderer_state_db, update_renderer_state_db

# Captured before fast_sleep patches asyncio.sleep, so the harness can wait
# real wall-clock time while monitor sleeps stay scaled down.
_REAL_SLEEP = asyncio.sleep


def _reset_globals(udn):
    last_playing_seen.pop(udn, None)
    last_playing_position.pop(udn, None)
    start_retries.pop(udn, None)
    last_stop_reason.pop(udn, None)
    monitor_module._prewarmed_index.pop(udn, None)


class ScriptedUpnp:
    """UPnP manager stub replaying a scripted (position, transport_state) sequence.

    The final entry repeats forever; `drained` fires once the script is consumed.
    """

    def __init__(self, script, volume=None):
        self.script = list(script)
        self.index = 0
        self.renderers = {}
        self.drained = asyncio.Event()
        self.play_calls = []
        self.volume = volume

    def _current(self):
        if self.index >= len(self.script):
            self.drained.set()
            return self.script[-1]
        return self.script[self.index]

    async def get_position(self, udn):
        pos, _state = self._current()
        return pos, 0

    async def get_transport_info(self, udn):
        _pos, state = self._current()
        self.index += 1
        if self.index >= len(self.script):
            self.drained.set()
        return state

    async def play_track(self, track_id, track_path, metadata):
        self.play_calls.append(track_id)

    async def get_volume(self, udn):
        return self.volume


@pytest.fixture
def fast_sleep(monkeypatch):
    real_sleep = asyncio.sleep

    async def scaled(delay, *args, **kwargs):
        await real_sleep(min(delay, 0.001))

    monkeypatch.setattr(monitor_module.asyncio, "sleep", scaled)


@pytest.fixture
def advances(monkeypatch):
    calls = []

    async def fake_advance(udn):
        calls.append(udn)
        # The real helper starts the next track; emulate its bookkeeping so the
        # transition guard suppresses the renderer's post-advance STOPPED churn.
        last_track_start_time[udn] = time.time()

    monkeypatch.setattr(monitor_module, "play_next_track_internal", fake_advance)

    async def no_history(*args, **kwargs):
        return None

    monkeypatch.setattr(monitor_module, "log_history", no_history)
    return calls


async def _run_monitor(monkeypatch, udn, upnp, timeout=5.0):
    monkeypatch.setattr(monitor_module.UPnPManager, "get_instance", lambda: upnp)
    task = asyncio.create_task(monitor_module.monitor_upnp_playback(udn))
    try:
        await asyncio.wait_for(upnp.drained.wait(), timeout=timeout)
        # Let the loop process the tail of the script. The advance hook fires
        # after a real DB await (connection release), so bare event-loop yields
        # can elapse before it runs on a loaded runner — this flaked in CI.
        # Give it wall-clock time instead.
        await _REAL_SLEEP(0.3)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def _state(queue_len=2, duration=180, is_playing=True):
    return {
        "queue": [
            {
                "id": 900 + i,
                "title": f"Track {i}",
                "artist": "Artist",
                "album": "Album",
                "path": f"/music/{i}.flac",
                "duration_seconds": duration,
            }
            for i in range(queue_len)
        ],
        "current_index": 0,
        "position_seconds": 0,
        "is_playing": is_playing,
        "transport_state": "PLAYING" if is_playing else "STOPPED",
        "volume": 20,
    }


async def test_stop_near_end_advances(db, monkeypatch, fast_sleep, advances):
    udn = "uuid:monitor-clean-stop"
    _reset_globals(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = ScriptedUpnp([(172, "PLAYING"), (174, "PLAYING"), (0, "STOPPED")])
    await _run_monitor(monkeypatch, udn, upnp)

    assert advances == [udn]


async def test_paused_then_stopped_advances(db, monkeypatch, fast_sleep, advances):
    """PLAYING -> PAUSED_PLAYBACK -> STOPPED is how some renderers end a track.

    The PAUSED poll writes is_playing=false, so detection must not rely on the
    DB flag alone (this was the bug that stopped playback between tracks).
    """
    udn = "uuid:monitor-paused-stop"
    _reset_globals(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = ScriptedUpnp([(170, "PLAYING"), (171, "PAUSED_PLAYBACK"), (0, "STOPPED")])
    await _run_monitor(monkeypatch, udn, upnp)

    assert advances == [udn]


async def test_stopped_during_transition_does_not_advance(
    db, monkeypatch, fast_sleep, advances
):
    udn = "uuid:monitor-transition"
    _reset_globals(udn)
    last_track_start_time[udn] = time.time()  # just started
    await update_renderer_state_db(db, udn, _state())

    upnp = ScriptedUpnp([(0, "STOPPED"), (0, "STOPPED"), (0, "STOPPED")])
    await _run_monitor(monkeypatch, udn, upnp)

    assert advances == []


async def test_stop_mid_track_halts_queue(db, monkeypatch, fast_sleep, advances):
    """STOPPED at 90s of a 180s track is an external stop (TV remote, another
    controller) — the queue must halt, not fight the user by advancing."""
    udn = "uuid:monitor-mid-stop"
    _reset_globals(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = ScriptedUpnp([(90, "PLAYING"), (91, "PLAYING"), (0, "STOPPED")])
    await _run_monitor(monkeypatch, udn, upnp)

    assert advances == []
    assert upnp.play_calls == []


async def test_stop_mid_track_keeps_the_listeners_position(
    db, monkeypatch, fast_sleep, advances
):
    """The halt must not throw away where the listener had got to.

    A renderer reports position 0 once it stops, so persisting the reading taken
    at the moment of the stop rewinds the track to the beginning and Resume
    starts it over.
    """
    udn = "uuid:monitor-mid-stop-position"
    _reset_globals(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = ScriptedUpnp([(90, "PLAYING"), (91, "PLAYING"), (0, "STOPPED")])
    await _run_monitor(monkeypatch, udn, upnp)

    state = await get_renderer_state_db(db, udn)
    assert state["is_playing"] is False
    assert state["position_seconds"] == pytest.approx(91, abs=1)


async def test_stop_mid_track_records_a_reason(db, monkeypatch, fast_sleep, advances):
    """The UI needs to be able to say why it went quiet."""
    udn = "uuid:monitor-mid-stop-reason"
    _reset_globals(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = ScriptedUpnp([(90, "PLAYING"), (91, "PLAYING"), (0, "STOPPED")])
    await _run_monitor(monkeypatch, udn, upnp)

    assert last_stop_reason[udn]["reason"] == "renderer_stopped"
    assert last_stop_reason[udn]["position_seconds"] == pytest.approx(91, abs=1)


async def test_playing_again_clears_the_stop_reason(
    db, monkeypatch, fast_sleep, advances
):
    """However playback resumed, the old explanation must stop being shown."""
    udn = "uuid:monitor-stop-reason-cleared"
    _reset_globals(udn)
    last_track_start_time[udn] = time.time() - 60
    last_stop_reason[udn] = {
        "reason": "renderer_stopped",
        "position_seconds": 91.0,
        "at": time.time(),
    }
    await update_renderer_state_db(db, udn, _state())

    upnp = ScriptedUpnp([(92, "PLAYING"), (93, "PLAYING")])
    await _run_monitor(monkeypatch, udn, upnp)

    assert udn not in last_stop_reason


async def test_never_started_track_gets_play_retry(db, monkeypatch, fast_sleep, advances):
    """A renderer sitting in STOPPED without ever reaching PLAYING gets the
    Play re-issued instead of the track being skipped (Server room TV
    intermittently accepts the URI, fetches the stream, and never starts)."""
    udn = "uuid:monitor-retry-never-started"
    _reset_globals(udn)
    last_track_start_time[udn] = time.time() - 10  # past START_RETRY_AFTER_S
    last_playing_seen[udn] = time.time() - 12  # previous track, before this start
    await update_renderer_state_db(db, udn, _state())

    upnp = ScriptedUpnp([(0, "STOPPED"), (0, "STOPPED"), (0, "STOPPED")])
    await _run_monitor(monkeypatch, udn, upnp)

    assert advances == []
    assert upnp.play_calls == [900]  # current track re-played, not skipped


async def test_early_death_gets_play_retry(db, monkeypatch, fast_sleep, advances):
    """Playing a few seconds and then dropping to STOPPED is a failed start
    too — the audible variant of the same renderer flakiness."""
    udn = "uuid:monitor-retry-early-death"
    _reset_globals(udn)
    last_track_start_time[udn] = time.time() - 6  # past the transition guard
    await update_renderer_state_db(db, udn, _state())

    upnp = ScriptedUpnp([(3, "PLAYING"), (0, "STOPPED"), (0, "STOPPED")])
    await _run_monitor(monkeypatch, udn, upnp)

    assert advances == []
    assert upnp.play_calls == [900]


async def test_failed_start_skips_after_retry_budget(
    db, monkeypatch, fast_sleep, advances
):
    """Once the Play retries are exhausted the track is presumed unplayable
    and the queue moves on instead of wedging."""
    udn = "uuid:monitor-retries-exhausted"
    _reset_globals(udn)
    start_retries[udn] = monitor_module.MAX_START_RETRIES
    last_track_start_time[udn] = time.time() - 10
    last_playing_seen[udn] = time.time() - 12
    await update_renderer_state_db(db, udn, _state())

    upnp = ScriptedUpnp([(0, "STOPPED"), (0, "STOPPED"), (0, "STOPPED")])
    await _run_monitor(monkeypatch, udn, upnp)

    assert advances == [udn]
    assert upnp.play_calls == []


async def test_idle_stopped_does_not_advance(db, monkeypatch, fast_sleep, advances):
    udn = "uuid:monitor-idle"
    _reset_globals(udn)
    last_track_start_time[udn] = time.time() - 600
    await update_renderer_state_db(db, udn, _state(is_playing=False))

    upnp = ScriptedUpnp([(0, "STOPPED"), (0, "STOPPED"), (0, "STOPPED")])
    await _run_monitor(monkeypatch, udn, upnp)

    assert advances == []


async def test_watchdog_advances_when_stuck_playing_at_zero(
    db, monkeypatch, fast_sleep, advances
):
    """Renderers that never report position and never emit STOPPED get unstuck
    once wall-clock time exceeds the track duration plus margin."""
    udn = "uuid:monitor-watchdog"
    _reset_globals(udn)
    last_track_start_time[udn] = time.time() - 300  # 300s > 180s track + 60s margin
    await update_renderer_state_db(db, udn, _state(duration=180))

    upnp = ScriptedUpnp([(0, "PLAYING"), (0, "PLAYING"), (0, "PLAYING")])
    await _run_monitor(monkeypatch, udn, upnp)

    assert advances == [udn]


async def test_watchdog_ignores_renderers_reporting_position(
    db, monkeypatch, fast_sleep, advances
):
    udn = "uuid:monitor-watchdog-pos"
    _reset_globals(udn)
    last_track_start_time[udn] = time.time() - 300
    await update_renderer_state_db(db, udn, _state(duration=180))

    upnp = ScriptedUpnp([(90, "PLAYING"), (91, "PLAYING"), (92, "PLAYING")])
    await _run_monitor(monkeypatch, udn, upnp)

    assert advances == []


async def test_monitor_seeds_device_volume(db, monkeypatch, fast_sleep, advances):
    """The monitor reads the device's real volume so the app slider never has
    to guess (a guessed slider position is how first touch used to blast TVs)."""
    udn = "uuid:monitor-volume-seed"
    _reset_globals(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())  # stores volume=20

    upnp = ScriptedUpnp([(90, "PLAYING"), (91, "PLAYING"), (92, "PLAYING")], volume=37)
    await _run_monitor(monkeypatch, udn, upnp)

    from app.services.player.state import get_renderer_state_db

    state = await get_renderer_state_db(db, udn)
    assert state["volume"] == 37


async def test_prewarm_triggers_near_track_end(db, monkeypatch, fast_sleep, advances):
    """Approaching the end of the current track warms the next track's file,
    once, so the renderer's first fetch is served from the page cache."""
    udn = "uuid:monitor-prewarm"
    _reset_globals(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    warmed = []

    async def fake_prewarm(path):
        warmed.append(path)

    monkeypatch.setattr(monitor_module, "_prewarm_next_track", fake_prewarm)

    # 160s of 180s is inside the 30s prewarm lead.
    upnp = ScriptedUpnp([(159, "PLAYING"), (160, "PLAYING"), (161, "PLAYING")])
    await _run_monitor(monkeypatch, udn, upnp)

    assert warmed == ["/music/1.flac"]  # next track, warmed exactly once
    assert advances == []


async def test_advance_failure_does_not_kill_monitor(db, monkeypatch, fast_sleep):
    """A failing auto-advance must not take the monitor loop down.

    Regression: an unguarded play_next_track_internal raised, killing
    monitor_upnp_playback for the renderer, so auto-advance stayed dead
    until restart.
    """
    udn = "uuid:monitor-advance-raises"
    _reset_globals(udn)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    calls = []

    async def boom(target):
        calls.append(target)
        last_track_start_time[target] = time.time()
        raise RuntimeError("advance exploded")

    monkeypatch.setattr(monitor_module, "play_next_track_internal", boom)

    async def no_history(*args, **kwargs):
        return None

    monkeypatch.setattr(monitor_module, "log_history", no_history)

    upnp = ScriptedUpnp([(172, "PLAYING"), (174, "PLAYING"), (0, "STOPPED")])
    monkeypatch.setattr(monitor_module.UPnPManager, "get_instance", lambda: upnp)

    task = asyncio.create_task(monitor_module.monitor_upnp_playback(udn))
    try:
        await asyncio.wait_for(upnp.drained.wait(), timeout=5.0)
        await _REAL_SLEEP(0.3)
        assert calls == [udn]
        # The loop survived the raise and is still polling the renderer.
        assert not task.done()
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
