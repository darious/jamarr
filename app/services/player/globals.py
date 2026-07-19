import asyncio
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
# Track rapid restart attempts: udn -> [(start_time, count_window_start)]
_monitor_restart_history: Dict[str, list] = {}
