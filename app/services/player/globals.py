import asyncio
import time
from typing import Dict

# Global map to track Playback Monitor Tasks (UDN -> Task)
playback_monitors: Dict[str, asyncio.Task] = {}
monitor_start_times: Dict[str, float] = {}  # Track when monitors were last started
# Track when we last started a new track to prevent false "track finished" detection during transitions
last_track_start_time: Dict[str, float] = {}
# Wallclock of the last poll where the renderer reported PLAYING. Lets the monitor
# treat a quick PLAYING -> PAUSED_PLAYBACK -> STOPPED sequence (how some renderers
# signal end-of-track) as track-finished even after the PAUSED poll cleared is_playing.
last_playing_seen: Dict[str, float] = {}
# Last real position (seconds) reported while PLAYING. Together with the track
# duration this tells the monitor *where* playback stopped, which distinguishes
# "finished" from "failed to start" from "externally stopped".
last_playing_position: Dict[str, float] = {}
# Play re-issues attempted for the current track after a failed start.
start_retries: Dict[str, int] = {}
monitor_starting: Dict[str, float] = {}
# Why the queue last halted on its own, per renderer, for the UI to explain
# itself: {"reason": str, "position_seconds": float, "at": float}. A renderer
# that drops out mid-track otherwise just goes quiet, which is indistinguishable
# from the app being broken. Cleared when a new track is started.
last_stop_reason: Dict[str, dict] = {}
# Track rapid restart attempts: udn -> [(start_time, count_window_start)]
_monitor_restart_history: Dict[str, list] = {}
# Audio output plan per renderer and track (see app/services/playback_plan.py):
# state_key -> {track_id: plan.as_dict()}. Keyed by track so a plan made when
# a UPnP next track was staged is still there once it becomes current.
output_plans: Dict[str, Dict[int, dict]] = {}
_OUTPUT_PLANS_KEPT = 4


def record_output_plan(state_key: str, track_id: int, plan: dict) -> None:
    plans = output_plans.setdefault(state_key, {})
    plans.pop(track_id, None)
    plans[track_id] = plan
    while len(plans) > _OUTPUT_PLANS_KEPT:
        plans.pop(next(iter(plans)))


def output_plan_for(state_key: str, track_id) -> dict | None:
    if track_id is None:
        return None
    try:
        return (output_plans.get(state_key) or {}).get(int(track_id))
    except (TypeError, ValueError):
        return None


# Mute as last reported by the renderer itself (e.g. Cast receiver status:
# muted on the device or by another controller). Not persisted.
renderer_muted: Dict[str, bool] = {}
# Wall clock of the last renderer_muted write, so a mute Jamarr just set can
# be weighed against an older evented one (see api.player._upnp_muted).
renderer_muted_at: Dict[str, float] = {}


def note_renderer_muted(state_key: str, muted: bool) -> None:
    renderer_muted[state_key] = muted
    renderer_muted_at[state_key] = time.time()


# Seeks issued per renderer (state key = UPnP UDN). The monitor's device
# reader re-polls position when this moves instead of extrapolating from a
# baseline taken before the seek.
seek_generations: Dict[str, int] = {}


def note_seek(state_key: str) -> None:
    seek_generations[state_key] = seek_generations.get(state_key, 0) + 1
