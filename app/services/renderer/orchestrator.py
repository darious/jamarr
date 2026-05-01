from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import asyncpg
from fastapi import HTTPException, Request

from app.db import get_pool
from app.services.player.globals import last_track_start_time, monitor_start_times, playback_monitors
from app.services.player.history import (
    log_history,
    reset_history_tracker,
    should_log_history,
)
from app.services.player.monitor import (
    _clear_monitor_starting,
    _mark_monitor_starting,
    start_monitor_task,
)
from app.services.player.state import (
    enrich_track_metadata,
    get_renderer_state_db,
    track_path_exists,
    update_playback_progress_db,
    update_queue_logged_db,
    update_renderer_state_db,
)
from app.services.renderer.contracts import PlaybackContext, RendererStatus, is_local_renderer
from app.services.renderer.registry import RendererRegistry, get_renderer_registry
from app.services.renderer.token_policy import stream_token_ttl_seconds

logger = logging.getLogger(__name__)


class RendererOrchestrator:
    def __init__(self, registry: RendererRegistry | None = None) -> None:
        self.registry = registry or get_renderer_registry()
        self._status_unsubscribers: dict[str, Any] = {}
        self._last_ended_at: dict[str, float] = {}

    async def get_active(self, db: asyncpg.Connection, client_id: str) -> tuple[str, str]:
        return await self.registry.get_active(db, client_id)

    async def set_active(
        self,
        db: asyncpg.Connection,
        client_id: str,
        renderer_id_or_udn: str,
    ) -> tuple[str, str]:
        previous_renderer_id, previous_state_key = await self.get_active(db, client_id)
        renderer_id, state_key = await self.registry.set_active(db, client_id, renderer_id_or_udn)
        if previous_renderer_id.startswith("cast:") and previous_renderer_id != renderer_id:
            await self._stop_previous_cast(previous_renderer_id, previous_state_key)
        return renderer_id, state_key

    async def list_renderers(
        self,
        db: asyncpg.Connection,
        client_id: str,
        refresh: bool = False,
    ) -> list[dict[str, Any]]:
        devices = await self.registry.discover_all(refresh=refresh) if refresh else await self.registry.list_all()
        await self.registry.persist_all(db, devices)
        return [self.registry.local_renderer(client_id), *[d.as_api_dict() for d in devices]]

    async def add_manual(self, address: str) -> bool:
        backend = self.registry.backends.get("upnp")
        if not backend:
            return False
        return await backend.add_manual(address) is not None

    async def set_queue(
        self,
        db: asyncpg.Connection,
        client_id: str,
        queue: list[dict[str, Any]],
        start_index: int,
        user_id: int | None,
        request: Request,
    ) -> None:
        renderer_id, state_key = await self.get_active(db, client_id)
        state = await get_renderer_state_db(db, state_key)
        state["queue"] = queue
        state["current_index"] = max(0, min(start_index, len(queue) - 1 if queue else 0))
        state["position_seconds"] = 0
        state["is_playing"] = True
        state["transport_state"] = "PLAYING"
        await update_renderer_state_db(db, state_key, state)
        reset_history_tracker(state_key if not is_local_renderer(state_key) else client_id)

        if not is_local_renderer(renderer_id) and state["queue"]:
            playable_idx = await self._first_playable_index(db, state, state["current_index"])
            if playable_idx is None:
                raise HTTPException(
                    status_code=404,
                    detail="No playable tracks found on disk for this queue.",
                )
            state["current_index"] = playable_idx
            await update_renderer_state_db(db, state_key, state)
            track = state["queue"][state["current_index"]]
            asyncio.create_task(
                self._play_remote_background(renderer_id, state_key, track, user_id, request)
            )

    async def play_track(
        self,
        db: asyncpg.Connection,
        client_id: str,
        track: dict[str, Any],
        user_id: int | None,
        request: Request,
    ) -> dict[str, Any]:
        renderer_id, state_key = await self.get_active(db, client_id)
        if is_local_renderer(renderer_id):
            state = await get_renderer_state_db(db, state_key)
            current_index = self._replace_or_singleton_queue(state, track)
            state["current_index"] = current_index
            state["position_seconds"] = 0
            state["is_playing"] = True
            state["transport_state"] = "PLAYING"
            await update_renderer_state_db(db, state_key, state)
            return {"status": "local_playback", "message": "Handle playback in browser"}

        state = await get_renderer_state_db(db, state_key)
        current_track = self._current_track(state)
        if current_track and current_track.get("id") == track["id"] and state.get("is_playing"):
            backend = self.registry.get_backend(renderer_id)
            if hasattr(backend, "register_status_listener"):
                self._register_status_listener(backend, renderer_id, state_key)
            elif state_key not in playback_monitors or playback_monitors[state_key].done():
                start_monitor_task(state_key)
                last_track_start_time[state_key] = time.time()
            return {"status": "already_playing", "renderer": state_key}

        if current_track and current_track.get("id") == track["id"] and not state.get("is_playing"):
            await self.resume(db, client_id)
            return {"status": "resumed", "renderer": state_key}

        current_index = self._replace_or_singleton_queue(state, track)
        state["current_index"] = current_index
        state["position_seconds"] = 0
        state["is_playing"] = True
        state["transport_state"] = "PLAYING"
        await update_renderer_state_db(db, state_key, state)
        reset_history_tracker(state_key)
        await self._cancel_monitor(state_key)
        await self._play_remote(renderer_id, state_key, track, user_id, request)
        return {"status": "streaming_started", "renderer": state_key}

    async def pause(self, db: asyncpg.Connection, client_id: str) -> None:
        renderer_id, state_key = await self.get_active(db, client_id)
        state = await get_renderer_state_db(db, state_key)
        state["is_playing"] = False
        await update_renderer_state_db(db, state_key, state)
        if not is_local_renderer(renderer_id):
            await self.registry.get_backend(renderer_id).pause(renderer_id)
            if state_key in playback_monitors:
                playback_monitors[state_key].cancel()
                del playback_monitors[state_key]

    async def resume(self, db: asyncpg.Connection, client_id: str) -> None:
        renderer_id, state_key = await self.get_active(db, client_id)
        state = await get_renderer_state_db(db, state_key)
        state["is_playing"] = True
        await update_renderer_state_db(db, state_key, state)
        if not is_local_renderer(renderer_id):
            backend = self.registry.get_backend(renderer_id)
            await backend.resume(renderer_id)
            if hasattr(backend, "register_status_listener"):
                self._register_status_listener(backend, renderer_id, state_key)
            elif state_key not in playback_monitors or playback_monitors[state_key].done():
                start_monitor_task(state_key)
                monitor_start_times[state_key] = time.time()

    async def stop_or_clear(self, db: asyncpg.Connection, client_id: str) -> tuple[dict[str, Any], str]:
        renderer_id, state_key = await self.get_active(db, client_id)
        state = await get_renderer_state_db(db, state_key)
        state["queue"] = []
        state["current_index"] = -1
        state["position_seconds"] = 0
        state["is_playing"] = False
        state["transport_state"] = "STOPPED"
        await update_renderer_state_db(db, state_key, state)
        reset_history_tracker(client_id if is_local_renderer(state_key) else state_key)
        if not is_local_renderer(renderer_id):
            try:
                await self.registry.get_backend(renderer_id).stop_playback(renderer_id)
            except Exception:
                await self.registry.get_backend(renderer_id).pause(renderer_id)
            await self._cancel_monitor(state_key, remove=True)
        return state, state_key

    async def seek(self, db: asyncpg.Connection, client_id: str, seconds: float) -> str:
        renderer_id, state_key = await self.get_active(db, client_id)
        state = await get_renderer_state_db(db, state_key)
        state["position_seconds"] = seconds
        await update_renderer_state_db(db, state_key, state)
        if not is_local_renderer(renderer_id):
            await self.registry.get_backend(renderer_id).seek(renderer_id, seconds)
            return "remote"
        return "local"

    async def set_volume(self, db: asyncpg.Connection, client_id: str, percent: int) -> None:
        renderer_id, state_key = await self.get_active(db, client_id)
        state = await get_renderer_state_db(db, state_key)
        state["volume"] = percent
        await update_renderer_state_db(db, state_key, state)
        if not is_local_renderer(renderer_id):
            await self.registry.get_backend(renderer_id).set_volume(renderer_id, percent)

    async def skip_to_index(
        self,
        db: asyncpg.Connection,
        client_id: str,
        index: int,
        request: Request | None = None,
    ) -> tuple[dict[str, Any], str]:
        renderer_id, state_key = await self.get_active(db, client_id)
        state = await get_renderer_state_db(db, state_key)
        state["current_index"] = index
        state["position_seconds"] = 0
        state["is_playing"] = True
        state["transport_state"] = "PLAYING"
        await update_renderer_state_db(db, state_key, state)
        reset_history_tracker(client_id if is_local_renderer(state_key) else state_key)

        if not is_local_renderer(renderer_id):
            queue = state.get("queue") or []
            if queue and 0 <= state["current_index"] < len(queue):
                playable_idx = await self._first_playable_index(db, state, state["current_index"])
                if playable_idx is None:
                    raise HTTPException(status_code=404, detail="Selected track is missing on disk.")
                state["current_index"] = playable_idx
                await update_renderer_state_db(db, state_key, state)
                await self._cancel_monitor(state_key)
                track = state["queue"][state["current_index"]]
                await self._play_remote(renderer_id, state_key, track, track.get("user_id"), request)
        return state, state_key

    async def _play_remote_background(
        self,
        renderer_id: str,
        state_key: str,
        track: dict[str, Any],
        user_id: int | None,
        request: Request,
    ) -> None:
        _mark_monitor_starting(state_key)
        try:
            await self._cancel_monitor(state_key)
            await self._play_remote(renderer_id, state_key, track, user_id, request)
        finally:
            _clear_monitor_starting(state_key)

    async def _play_remote(
        self,
        renderer_id: str,
        state_key: str,
        track: dict[str, Any],
        user_id: int | None,
        request: Request | None,
    ) -> None:
        _mark_monitor_starting(state_key)
        try:
            context = PlaybackContext(
                base_url=self._base_url(request),
                user_id=user_id or track.get("user_id"),
                token_ttl_seconds=stream_token_ttl_seconds(
                    renderer_id.split(":", 1)[0] if ":" in renderer_id else None,
                    track.get("duration_seconds"),
                ),
            )
            backend = self.registry.get_backend(renderer_id)
            await backend.play_track(renderer_id, track, context)
            if hasattr(backend, "register_status_listener"):
                self._register_status_listener(backend, renderer_id, state_key)
            else:
                start_monitor_task(state_key)
                last_track_start_time[state_key] = time.time()
        finally:
            _clear_monitor_starting(state_key)

    async def _cancel_monitor(self, state_key: str, remove: bool = False) -> None:
        if state_key in playback_monitors:
            playback_monitors[state_key].cancel()
            try:
                await asyncio.wait([playback_monitors[state_key]], timeout=1)
            except Exception:
                pass
            if remove:
                playback_monitors.pop(state_key, None)

    async def _stop_previous_cast(self, renderer_id: str, state_key: str) -> None:
        unsubscribe = self._status_unsubscribers.pop(state_key, None)
        if unsubscribe:
            try:
                unsubscribe()
            except Exception:
                logger.debug("Cast status listener cleanup failed for %s", renderer_id, exc_info=True)
        try:
            await self.registry.get_backend(renderer_id).stop_playback(renderer_id)
        except Exception:
            logger.warning("Failed to close previous Cast session %s", renderer_id, exc_info=True)

    async def _log_history_if_due(
        self,
        db: asyncpg.Connection,
        state_key: str,
        renderer_id: str,
        state: dict[str, Any],
        allow_stopped: bool = False,
    ) -> None:
        if not state.get("is_playing") and not allow_stopped:
            return
        current_index = state.get("current_index")
        queue = state.get("queue") or []
        if current_index is None or current_index < 0 or current_index >= len(queue):
            return
        track = queue[current_index]
        if not isinstance(track, dict) or track.get("logged"):
            return
        track_id = track.get("id")
        if not track_id:
            return
        duration = track.get("duration_seconds") or 0
        if not should_log_history(
            state_key, track_id, state.get("position_seconds") or 0, duration
        ):
            return
        renderer_ip = await self._renderer_ip(db, renderer_id, state_key)
        await log_history(
            db,
            track_id,
            client_ip=renderer_ip or "unknown",
            client_id=state_key,
            user_id=track.get("user_id"),
        )
        track["logged"] = True
        await update_queue_logged_db(db, state_key, state)

    @staticmethod
    async def _renderer_ip(
        db: asyncpg.Connection,
        renderer_id: str,
        state_key: str,
    ) -> str | None:
        return await db.fetchval(
            """
            SELECT ip
            FROM renderer
            WHERE renderer_id = $1 OR udn = $2
            ORDER BY last_seen_at DESC NULLS LAST
            LIMIT 1
            """,
            renderer_id,
            state_key,
        )

    async def _first_playable_index(
        self,
        db: asyncpg.Connection,
        state: dict[str, Any],
        start_index: int,
    ) -> int | None:
        for idx in range(start_index, len(state.get("queue") or [])):
            candidate = await enrich_track_metadata(state["queue"][idx], db)
            if track_path_exists(candidate):
                state["queue"][idx] = candidate
                return idx
        return None

    def _base_url(self, request: Request | None) -> str:
        upnp_backend = self.registry.backends.get("upnp")
        manager = getattr(upnp_backend, "manager", None)
        local_ip = getattr(manager, "local_ip", "127.0.0.1")
        env_port = os.environ.get("HOST_PORT")
        port = env_port if env_port else ((request.url.port if request else None) or 8111)
        return f"http://{local_ip}:{port}"

    def _register_status_listener(self, backend: Any, renderer_id: str, state_key: str) -> None:
        unsubscribe = self._status_unsubscribers.pop(state_key, None)
        if unsubscribe:
            try:
                unsubscribe()
            except Exception:
                pass

        async def callback(status: RendererStatus) -> None:
            await self.handle_status(state_key, status)

        self._status_unsubscribers[state_key] = backend.register_status_listener(
            renderer_id,
            callback,
        )

    async def handle_status(self, state_key: str, status: RendererStatus) -> None:
        async with get_pool().acquire() as db:
            state = await get_renderer_state_db(db, state_key)
            await self._apply_status(db, state_key, state, status)

    async def sync_status(
        self,
        db: asyncpg.Connection,
        renderer_id: str,
        state_key: str,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        backend = self.registry.get_backend(renderer_id)
        try:
            status = await backend.get_status(renderer_id)
        except Exception:
            logger.debug("Renderer status sync failed for %s", renderer_id, exc_info=True)
            return state or await get_renderer_state_db(db, state_key)
        current_state = state or await get_renderer_state_db(db, state_key)
        return await self._apply_status(db, state_key, current_state, status)

    async def _apply_status(
        self,
        db: asyncpg.Connection,
        state_key: str,
        state: dict[str, Any],
        status: RendererStatus,
    ) -> dict[str, Any]:
        if status.state == "UNKNOWN" and not status.current_media_url:
            return state
        prev_position = state.get("position_seconds") or 0
        if status.position_seconds is not None:
            state["position_seconds"] = status.position_seconds
        if status.volume_percent is not None:
            state["volume"] = status.volume_percent
        if status.state != "UNKNOWN":
            state["transport_state"] = status.state
            state["is_playing"] = status.state == "PLAYING"
        await update_playback_progress_db(db, state_key, state)
        await self._log_history_if_due(
            db,
            state_key,
            status.renderer_id,
            state,
            allow_stopped=status.ended,
        )
        if status.ended or self._detect_track_ended(state, status, prev_position):
            await self._advance_queue_from_status(db, state_key, state)
            state = await get_renderer_state_db(db, state_key)
        return state

    @staticmethod
    def _detect_track_ended(
        state: dict[str, Any],
        status: RendererStatus,
        prev_position: float,
    ) -> bool:
        """Detect track completion from position vs duration.

        Uses the larger of previous and current position because some
        devices reset position to 0 on idle.  Only triggers when the
        device is not actively playing or paused.
        """
        if status.state in ("PLAYING", "PAUSED"):
            return False
        queue = state.get("queue") or []
        idx = state.get("current_index", -1)
        if idx < 0 or idx >= len(queue):
            return False
        track = queue[idx]
        if not isinstance(track, dict):
            return False
        duration = track.get("duration_seconds") or 0
        if duration <= 0:
            return False
        position = max(prev_position, state.get("position_seconds") or 0)
        return position >= duration - 5

    async def _advance_queue_from_status(
        self,
        db: asyncpg.Connection,
        state_key: str,
        state: dict[str, Any],
    ) -> None:
        now = time.time()
        if now - self._last_ended_at.get(state_key, 0) < 3:
            return
        self._last_ended_at[state_key] = now
        reset_history_tracker(state_key)
        queue = state.get("queue") or []
        next_index = int(state.get("current_index", -1)) + 1
        if next_index >= len(queue):
            state["is_playing"] = False
            state["transport_state"] = "STOPPED"
            await update_renderer_state_db(db, state_key, state)
            return
        state["current_index"] = next_index
        state["position_seconds"] = 0
        state["is_playing"] = True
        state["transport_state"] = "PLAYING"
        await update_renderer_state_db(db, state_key, state)
        track = queue[next_index]
        renderer_id = self.registry.state_key_to_renderer_id(state_key)
        await self._play_remote(renderer_id, state_key, track, track.get("user_id"), None)

    @staticmethod
    def _current_track(state: dict[str, Any]) -> dict[str, Any] | None:
        queue = state.get("queue") or []
        idx = state.get("current_index")
        if idx is not None and 0 <= idx < len(queue):
            return queue[idx]
        return None

    @staticmethod
    def _replace_or_singleton_queue(state: dict[str, Any], track: dict[str, Any]) -> int:
        existing_queue = state.get("queue") or []
        try:
            current_index = next(i for i, item in enumerate(existing_queue) if item.get("id") == track["id"])
            existing_queue[current_index] = track
        except StopIteration:
            existing_queue = [track]
            current_index = 0
        state["queue"] = existing_queue
        return current_index


_orchestrator: RendererOrchestrator | None = None


def get_renderer_orchestrator() -> RendererOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = RendererOrchestrator()
    return _orchestrator
