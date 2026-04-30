from __future__ import annotations

import asyncio
import mimetypes
import os
import time
from typing import Any

import asyncpg
from fastapi import HTTPException, Request

from app.services.player.globals import last_track_start_time, monitor_start_times, playback_monitors
from app.services.player.history import reset_history_tracker
from app.services.player.monitor import (
    _clear_monitor_starting,
    _mark_monitor_starting,
    start_monitor_task,
)
from app.services.player.state import (
    enrich_track_metadata,
    get_renderer_state_db,
    track_path_exists,
    update_renderer_state_db,
)
from app.services.renderer.contracts import PlaybackContext, is_local_renderer
from app.services.renderer.registry import RendererRegistry, get_renderer_registry
from app.services.renderer.token_policy import stream_token_ttl_seconds


class RendererOrchestrator:
    def __init__(self, registry: RendererRegistry | None = None) -> None:
        self.registry = registry or get_renderer_registry()

    async def get_active(self, db: asyncpg.Connection, client_id: str) -> tuple[str, str]:
        return await self.registry.get_active(db, client_id)

    async def set_active(
        self,
        db: asyncpg.Connection,
        client_id: str,
        renderer_id_or_udn: str,
    ) -> tuple[str, str]:
        return await self.registry.set_active(db, client_id, renderer_id_or_udn)

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
            if state_key not in playback_monitors or playback_monitors[state_key].done():
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
            await self.registry.get_backend(renderer_id).resume(renderer_id)
            if state_key not in playback_monitors or playback_monitors[state_key].done():
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
            await self.registry.get_backend(renderer_id).play_track(renderer_id, track, context)
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
