import asyncio
from typing import Dict

# Global map to track Playback Monitor Tasks (UDN -> Task)
playback_monitors: Dict[str, asyncio.Task] = {}
monitor_start_times: Dict[str, float] = {}  # Track when monitors were last started
# Track when we last started a new track to prevent false "track finished" detection during transitions
last_track_start_time: Dict[str, float] = {}
monitor_starting: Dict[str, float] = {}
# Track rapid restart attempts: udn -> [(start_time, count_window_start)]
_monitor_restart_history: Dict[str, list] = {}
