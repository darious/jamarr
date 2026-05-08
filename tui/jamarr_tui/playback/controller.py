"""Unified playback controller.

The controller drives mpv for local playback and mirrors queue/index/progress
to the server's `local:<client_id>` renderer state. When the active renderer is
remote (UPnP / Cast), it treats the server as the playback backend: controls go
to `/api/player/*`, state is polled from `/api/player/state`, and the backend
handles progress/history.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from jamarr_tui.api.client import AuthError, JamarrClient
from jamarr_tui.playback.mpv import MpvController, PlaybackState

log = logging.getLogger("jamarr_tui.controller")


@dataclass
class CurrentTrack:
    """Lightweight view PlayerBar consumes — keeps the widget off raw dicts."""

    track_id: int
    title: str
    artist: str
    album: str
    duration_s: float
    art_sha1: str | None = None


StreamUrlResolver = Callable[[int], Awaitable[str]]


class PlaybackController:
    def __init__(self, *, client: JamarrClient) -> None:
        self._client = client
        self._mpv = MpvController()
        self._local_queue: list[dict[str, Any]] = []
        self._local_index: int = -1
        self._remote_queue: list[dict[str, Any]] = []
        self._remote_index: int = -1
        self._remote_state = PlaybackState()
        self._active_renderer_id = f"local:{client.client_id}"
        self._active_renderer_kind = "local"
        self._last_state_sync = 0.0
        self._state_sync_inflight = False
        self._mpv.on_track_end(self._on_track_end)
        self._auto_advance_pending = False
        self._volume: float = 1.0

    @property
    def is_local_active(self) -> bool:
        return self._active_renderer_id.startswith("local:")

    @property
    def state(self) -> PlaybackState:
        if self.is_local_active:
            return self._mpv.state
        return self._remote_state

    @property
    def queue(self) -> list[dict[str, Any]]:
        return list(self._active_queue)

    @property
    def current(self) -> CurrentTrack | None:
        queue = self._active_queue
        index = self._active_index
        if not (0 <= index < len(queue)):
            return None
        t = queue[index]
        return CurrentTrack(
            track_id=int(t["id"]),
            title=t.get("title") or "",
            artist=t.get("artist") or "",
            album=t.get("album") or "",
            duration_s=float(t.get("duration_seconds") or 0.0),
            art_sha1=t.get("art_sha1"),
        )

    async def start(self) -> None:
        await self._mpv.start()
        await self.sync_server_state(force=True)

    async def stop(self) -> None:
        await self._mpv.stop()

    async def sync_server_state(self, *, force: bool = False) -> None:
        """Poll server player state for remote renderers, throttled to ~1 Hz."""
        now = time.monotonic()
        if not force and now - self._last_state_sync < 1.0:
            return
        if self._state_sync_inflight:
            return
        self._state_sync_inflight = True
        try:
            data = await self._client.player_state()
        except Exception:
            log.exception("player_state sync failed")
            return
        finally:
            self._state_sync_inflight = False
            self._last_state_sync = now
        self._apply_server_state(data)

    async def activate_renderer(self, renderer_id: str | None = None) -> None:
        await self.sync_server_state(force=True)
        if renderer_id:
            self._active_renderer_id = renderer_id
            self._active_renderer_kind = renderer_id.split(":", 1)[0]
        if not self.is_local_active:
            await self._mpv.stop_playback()

    async def set_queue(
        self, tracks: list[dict[str, Any]], start_index: int = 0
    ) -> None:
        # Re-read server's active renderer before deciding local vs remote, in
        # case the user activated a remote renderer outside this controller's
        # state (e.g. via the web UI, or the RendererPicker's marker reflecting
        # a server-side selection the controller never adopted).
        await self.sync_server_state(force=True)
        queue = [t for t in tracks if t.get("id") is not None]
        self._set_active_queue(queue)
        if not queue:
            self._set_active_index(-1)
            return
        start_index = max(0, min(start_index, len(queue) - 1))
        try:
            await self._client.set_player_queue(queue, start_index)
        except Exception:
            log.exception("set_player_queue failed; history will not log")
            if not self.is_local_active:
                return
        if self.is_local_active:
            await self.play_index(start_index, _push_index=False)
        else:
            # Make sure no local stream is still playing in parallel with the
            # remote renderer the server is driving.
            await self._mpv.stop_playback()
            await self.sync_server_state(force=True)

    async def play_index(self, idx: int, *, _push_index: bool = True) -> None:
        queue = self._active_queue
        if not (0 <= idx < len(queue)):
            return
        if not self.is_local_active:
            await self._client.set_player_index(idx)
            await self.sync_server_state(force=True)
            return
        track = queue[idx]
        track_id = int(track["id"])
        log.info(
            "play_index idx=%d track_id=%s title=%r",
            idx,
            track_id,
            track.get("title"),
        )
        try:
            url = await self._client.stream_url(track_id)
        except Exception:
            log.exception("stream_url resolve failed for track %s", track_id)
            raise
        log.info("resolved stream url: %s", url)
        self._local_index = idx
        if _push_index:
            try:
                await self._client.set_player_index(idx)
            except Exception:
                log.exception("set_player_index failed; history will not log")
        await self._mpv.load(url)

    async def toggle_pause(self) -> None:
        if self.is_local_active:
            await self._mpv.toggle_pause()
            return
        try:
            if self._remote_state.paused:
                await self._client.resume_player()
            else:
                await self._client.pause_player()
        except Exception:
            log.exception("remote toggle_pause failed")
            return
        await self.sync_server_state(force=True)

    async def next(self) -> None:
        if self._active_index + 1 < len(self._active_queue):
            try:
                await self.play_index(self._active_index + 1)
            except Exception:
                log.exception("next failed")

    async def prev(self) -> None:
        if self._active_index > 0:
            try:
                await self.play_index(self._active_index - 1)
            except Exception:
                log.exception("prev failed")

    async def seek(self, position_s: float) -> None:
        if not self.is_local_active:
            try:
                await self._client.seek_player(position_s)
            except Exception:
                log.exception("remote seek failed")
                return
            await self.sync_server_state(force=True)
            return
        await self._mpv.seek(position_s)

    async def seek_relative(self, delta_s: float) -> None:
        new_pos = max(0.0, self.state.position_s + delta_s)
        await self.seek(new_pos)

    @property
    def volume(self) -> float:
        return self._volume

    async def set_volume(self, level: float) -> None:
        self._volume = max(0.0, min(1.0, level))
        if not self.is_local_active:
            await self._client.set_player_volume(round(self._volume * 100))
            await self.sync_server_state(force=True)
            return
        await self._mpv.set_volume(self._volume)

    async def vol_up(self, step: float = 0.05) -> None:
        await self.set_volume(self._volume + step)

    async def vol_down(self, step: float = 0.05) -> None:
        await self.set_volume(self._volume - step)

    @property
    def index(self) -> int:
        return self._active_index

    async def remove_at(self, idx: int) -> None:
        queue = self._active_queue
        index = self._active_index
        if not (0 <= idx < len(queue)):
            return
        was_current = idx == index
        new_queue = list(queue)
        del new_queue[idx]
        if was_current and self.is_local_active:
            await self._mpv.stop_playback()
        if not new_queue:
            self._set_active_queue([])
            self._set_active_index(-1)
            try:
                await self._client.clear_player_queue()
            except Exception:
                log.exception("clear_player_queue failed")
            if not self.is_local_active:
                await self.sync_server_state(force=True)
            return
        # Adjust the current index to point at the same logical track when
        # something earlier in the queue was removed.
        if idx < index:
            new_index = index - 1
        elif was_current:
            new_index = min(index, len(new_queue) - 1)
        else:
            new_index = index
        self._set_active_queue(new_queue)
        self._set_active_index(new_index)
        try:
            await self._client.reorder_player_queue(new_queue)
        except Exception:
            log.exception("reorder_player_queue failed")
        if was_current:
            await self.play_index(new_index)

    async def move(self, src: int, dst: int) -> None:
        queue = self._active_queue
        if not (0 <= src < len(queue)):
            return
        dst = max(0, min(dst, len(queue) - 1))
        if dst == src:
            return
        new_queue = list(queue)
        item = new_queue.pop(src)
        new_queue.insert(dst, item)
        # Track the currently-playing item so the index follows the move.
        current_id = (
            queue[self._active_index]["id"]
            if 0 <= self._active_index < len(queue)
            else None
        )
        self._set_active_queue(new_queue)
        if current_id is not None:
            for i, t in enumerate(new_queue):
                if t.get("id") == current_id:
                    self._set_active_index(i)
                    break
        try:
            await self._client.reorder_player_queue(new_queue)
        except Exception:
            log.exception("reorder_player_queue failed")
        if not self.is_local_active:
            await self.sync_server_state(force=True)

    async def clear(self) -> None:
        self._set_active_queue([])
        self._set_active_index(-1)
        if self.is_local_active:
            await self._mpv.stop_playback()
        try:
            await self._client.clear_player_queue()
        except Exception:
            log.exception("clear_player_queue failed")
        if not self.is_local_active:
            await self.sync_server_state(force=True)

    async def report_progress(self) -> None:
        if not self.is_local_active:
            await self.sync_server_state()
            return
        st = self._mpv.state
        if not st.loaded or self._local_index < 0:
            return
        try:
            await self._client.update_progress(st.position_s, not st.paused)
        except Exception:
            log.exception("update_progress failed")

    def _on_track_end(self) -> None:
        self._auto_advance_pending = True

    async def advance_if_pending(self) -> bool:
        if not self.is_local_active:
            await self.sync_server_state()
            return False
        if not self._auto_advance_pending:
            return False
        self._auto_advance_pending = False
        if self._local_index + 1 < len(self._local_queue):
            try:
                await self.play_index(self._local_index + 1)
            except AuthError:
                log.exception("auto-advance failed: session is unauthenticated")
                return False
            return True
        self._local_index = -1
        return False

    @property
    def _active_queue(self) -> list[dict[str, Any]]:
        return self._local_queue if self.is_local_active else self._remote_queue

    @property
    def _active_index(self) -> int:
        return self._local_index if self.is_local_active else self._remote_index

    def _set_active_queue(self, queue: list[dict[str, Any]]) -> None:
        if self.is_local_active:
            self._local_queue = queue
        else:
            self._remote_queue = queue

    def _set_active_index(self, index: int) -> None:
        if self.is_local_active:
            self._local_index = index
        else:
            self._remote_index = index

    def _apply_server_state(self, data: dict[str, Any]) -> None:
        renderer_id = data.get("renderer_id") or data.get("renderer") or ""
        if renderer_id:
            self._active_renderer_id = str(renderer_id)
        self._active_renderer_kind = (
            data.get("renderer_kind")
            or self._active_renderer_id.split(":", 1)[0]
            or "local"
        )
        if self.is_local_active:
            return
        self._remote_queue = [
            t for t in data.get("queue") or [] if isinstance(t, dict)
        ]
        current_index = data.get("current_index")
        self._remote_index = int(current_index) if current_index is not None else -1
        transport_state = str(data.get("transport_state") or "").upper()
        is_playing = bool(data.get("is_playing"))
        current = (
            self._remote_queue[self._remote_index]
            if 0 <= self._remote_index < len(self._remote_queue)
            else None
        )
        self._remote_state.loaded = current is not None and transport_state != "STOPPED"
        self._remote_state.paused = not is_playing
        self._remote_state.position_s = float(data.get("position_seconds") or 0.0)
        self._remote_state.duration_s = (
            float(current.get("duration_seconds") or 0.0) if current else 0.0
        )
        if data.get("volume") is not None:
            self._volume = max(0.0, min(1.0, float(data["volume"]) / 100.0))
