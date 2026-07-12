"""Playback monitor auto-advance: PAUSED->STOPPED transitions, transition guard, watchdog."""

import asyncio
import time

import pytest

from app.services.player import monitor as monitor_module
from app.services.player.globals import last_playing_seen, last_track_start_time
from app.services.player.state import update_renderer_state_db


class ScriptedUpnp:
    """UPnP manager stub replaying a scripted (position, transport_state) sequence.

    The final entry repeats forever; `drained` fires once the script is consumed.
    """

    def __init__(self, script):
        self.script = list(script)
        self.index = 0
        self.renderers = {}
        self.drained = asyncio.Event()

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
        # Let the loop process the tail of the script
        for _ in range(50):
            await asyncio.sleep(0)
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


async def test_clean_stop_advances(db, monkeypatch, fast_sleep, advances):
    udn = "uuid:monitor-clean-stop"
    last_playing_seen.pop(udn, None)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = ScriptedUpnp([(10, "PLAYING"), (11, "PLAYING"), (0, "STOPPED")])
    await _run_monitor(monkeypatch, udn, upnp)

    assert advances == [udn]


async def test_paused_then_stopped_advances(db, monkeypatch, fast_sleep, advances):
    """PLAYING -> PAUSED_PLAYBACK -> STOPPED is how some renderers end a track.

    The PAUSED poll writes is_playing=false, so detection must not rely on the
    DB flag alone (this was the bug that stopped playback between tracks).
    """
    udn = "uuid:monitor-paused-stop"
    last_playing_seen.pop(udn, None)
    last_track_start_time[udn] = time.time() - 60
    await update_renderer_state_db(db, udn, _state())

    upnp = ScriptedUpnp([(170, "PLAYING"), (171, "PAUSED_PLAYBACK"), (0, "STOPPED")])
    await _run_monitor(monkeypatch, udn, upnp)

    assert advances == [udn]


async def test_stopped_during_transition_does_not_advance(
    db, monkeypatch, fast_sleep, advances
):
    udn = "uuid:monitor-transition"
    last_playing_seen.pop(udn, None)
    last_track_start_time[udn] = time.time()  # just started
    await update_renderer_state_db(db, udn, _state())

    upnp = ScriptedUpnp([(0, "STOPPED"), (0, "STOPPED"), (0, "STOPPED")])
    await _run_monitor(monkeypatch, udn, upnp)

    assert advances == []


async def test_idle_stopped_does_not_advance(db, monkeypatch, fast_sleep, advances):
    udn = "uuid:monitor-idle"
    last_playing_seen.pop(udn, None)
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
    last_playing_seen.pop(udn, None)
    last_track_start_time[udn] = time.time() - 300  # 300s > 180s track + 60s margin
    await update_renderer_state_db(db, udn, _state(duration=180))

    upnp = ScriptedUpnp([(0, "PLAYING"), (0, "PLAYING"), (0, "PLAYING")])
    await _run_monitor(monkeypatch, udn, upnp)

    assert advances == [udn]


async def test_watchdog_ignores_renderers_reporting_position(
    db, monkeypatch, fast_sleep, advances
):
    udn = "uuid:monitor-watchdog-pos"
    last_playing_seen.pop(udn, None)
    last_track_start_time[udn] = time.time() - 300
    await update_renderer_state_db(db, udn, _state(duration=180))

    upnp = ScriptedUpnp([(90, "PLAYING"), (91, "PLAYING"), (92, "PLAYING")])
    await _run_monitor(monkeypatch, udn, upnp)

    assert advances == []
