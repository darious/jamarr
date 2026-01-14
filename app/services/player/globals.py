import asyncio
from typing import Dict

# Global map to track Playback Monitor Tasks (UDN -> Task)
playback_monitors: Dict[str, asyncio.Task] = {}
monitor_start_times: Dict[str, float] = {}  # Track when monitors were last started
# Track when we last started a new track to prevent false "track finished" detection during transitions
last_track_start_time: Dict[str, float] = {}
monitor_starting: Dict[str, float] = {}
