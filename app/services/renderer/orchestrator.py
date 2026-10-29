from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import os
import time
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

import asyncpg
from async_upnp_client.exceptions import UpnpError
from fastapi import HTTPException, Request

from app.db import db_conn
from app.services.player.globals import (
    last_playing_position,
    last_stop_reason,
    last_track_start_time,
    monitor_start_times,
    note_renderer_muted,
    playback_monitors,
    record_output_plan,
    start_retries,
)
from app.services.player.history import (
    log_history,
    reset_history_tracker,
    should_log_history,
)
from app.services.player.monitor import (
    _clear_monitor_starting,
    _is_monitor_starting,
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
    update_renderer_status_db,
)
from app.services.audio_streaming import build_stream_url
from app.services.playback_plan import RendererConstraints, constraints_for_device
from app.services.renderer.contracts import (
    PlaybackContext,
    RendererDevice,
    RendererLoadError,
    RendererStatus,
    is_local_renderer,
)
from app.services.renderer.registry import RendererRegistry, get_renderer_registry
from app.services.renderer.token_policy import (
    staged_stream_token_ttl_seconds,
    stream_token_ttl_seconds,
)

logger = logging.getLogger(__name__)


def _heals_stale_renderer(func: Callable[..., Any]) -> Callable[..., Any]:
    """Clear a vanished renderer before the failure reaches the client.

    The call still fails (the client is told to re-select a device), but the
    session no longer stays pinned to a device that will never answer again.
    """

    @functools.wraps(func)
    async def wrapper(
        self: RendererOrchestrator,
        db: asyncpg.Connection,
        client_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        try:
            return await func(self, db, client_id, *args, **kwargs)
        except ValueError as exc:
            await self._heal_if_renderer_gone(db, client_id, exc)
            raise

    return wrapper


class RendererOrchestrator:
    def __init__(self, registry: RendererRegistry | None = None) -> None:
        self.registry = registry or get_renderer_registry()
        self._status_unsubscribers: dict[str, Any] = {}
        self._last_ended_at: dict[str, float] = {}
        # Strong refs: the loop only keeps weak ones to running tasks.
        self._background_tasks: set[asyncio.Task] = set()
        # Receiver-queue staging (Cast queue mode): one insert at a time per
        # renderer, and refused inserts are not retried straight away.
        self._staging_in_flight: set[str] = set()
        self._stage_failures: dict[str, tuple[Any, float]] = {}

    async def get_active(self, db: asyncpg.Connection, client_id: str) -> tuple[str, str]:
        return await self.registry.get_active(db, client_id)

    async def _renderer_available(self, renderer_id: str) -> bool:
        """True if the device behind renderer_id is still discoverable.

        Backends that track liveness (UPnP: SSDP alive/byebye + probes) answer
        via ``is_available``; list membership is the fallback, since a list
        can hold a device long after it went away.
        """
        try:
            backend = self.registry.get_backend(renderer_id)
        except ValueError:
            return False
        checker = getattr(backend, "is_available", None)
        if checker is not None:
            try:
                tracked = await checker(renderer_id)
            except Exception:
                logger.debug("Availability check failed for %s", renderer_id, exc_info=True)
                return True
            if tracked is not None:
                return bool(tracked)
        try:
            devices = await backend.list_devices()
        except Exception:
            # Backend is present but unhappy — assume transient, don't clear.
            logger.debug("Availability check failed for %s", renderer_id, exc_info=True)
            return True
        return any(device.renderer_id == renderer_id for device in devices)

    async def clear_stale_renderer(
        self,
        db: asyncpg.Connection,
        renderer_id: str,
        exc: Exception | None = None,
    ) -> int:
        """Reset every session still pointing at a vanished renderer to local.

        A Cast/UPnP device that disappears (powered off, renamed, new DHCP
        lease) otherwise stays selected forever: every later control call fails
        with 409, including index reports from clients that are actually playing
        locally. Nothing else clears it, so the session stays wedged until the
        user happens to re-pick a device.
        """
        if is_local_renderer(renderer_id):
            return 0
        result = await db.execute(
            """
            UPDATE client_session
            SET active_renderer_id = 'local:' || client_id,
                active_renderer_udn = 'local:' || client_id,
                last_seen_at = NOW()
            WHERE active_renderer_id = $1
            """,
            renderer_id,
        )
        cleared = int(result.rsplit(" ", 1)[-1]) if result else 0
        if cleared:
            logger.warning(
                "Renderer %s is gone (%s) — reset %d session(s) to local playback",
                renderer_id,
                exc or "not discoverable",
                cleared,
            )
        return cleared

    async def _heal_if_renderer_gone(
        self,
        db: asyncpg.Connection,
        client_id: str,
        exc: Exception,
    ) -> None:
        """Clear the active renderer if this failure means the device is gone."""
        renderer_id, state_key = await self.get_active(db, client_id)
        if is_local_renderer(renderer_id) or await self._renderer_available(renderer_id):
            return
        await self.clear_stale_renderer(db, renderer_id, exc)
        await self._cancel_monitor(state_key, remove=True)

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
        if previous_renderer_id.startswith("upnp:") and previous_renderer_id != renderer_id:
            monitor = playback_monitors.get(previous_state_key)
            if monitor is None or monitor.done():
                # Nothing is playing there any more: drop its UPnP event
                # subscriptions (a running monitor keeps them until it ends).
                release = getattr(
                    self.registry.backends.get("upnp"), "release_events", None
                )
                if release is not None:
                    await release(previous_renderer_id)
        return renderer_id, state_key

    async def list_renderers(
        self,
        client_id: str,
        refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Discover (no connection held), then persist on a short-lived one."""
        devices = await self.registry.discover_all(refresh=refresh) if refresh else await self.registry.list_all()
        async with db_conn() as db:
            await self.registry.persist_all(db, devices)
        renderers = []
        for device in devices:
            data = device.as_api_dict()
            data["output_constraints"] = (
                await self.output_constraints(device.renderer_id)
            ).as_dict()
            renderers.append(data)
        return [self.registry.local_renderer(client_id), *renderers]

    async def add_manual(self, address: str) -> RendererDevice | None:
        """Add a UPnP renderer by IP or description URL; the device, or None."""
        backend = self.registry.backends.get("upnp")
        if not backend:
            return None
        return await backend.add_manual(address)

    @_heals_stale_renderer
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

    @_heals_stale_renderer
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
        await self._play_remote(renderer_id, state_key, track, user_id, request, db=db)
        return {"status": "streaming_started", "renderer": state_key}

    @_heals_stale_renderer
    async def pause(self, db: asyncpg.Connection, client_id: str) -> None:
        renderer_id, state_key = await self.get_active(db, client_id)
        # Status columns only: a whole-row write here could put back a queue
        # read before a concurrent edit landed.
        await update_renderer_status_db(db, state_key, is_playing=False)
        if not is_local_renderer(renderer_id):
            await self.registry.get_backend(renderer_id).pause(renderer_id)
            # The monitor stops here, so nothing else would replace the
            # PLAYING it last stored.
            await update_renderer_status_db(db, state_key, transport_state="PAUSED_PLAYBACK")
            if state_key in playback_monitors:
                playback_monitors[state_key].cancel()
                del playback_monitors[state_key]

    @_heals_stale_renderer
    async def resume(self, db: asyncpg.Connection, client_id: str) -> None:
        renderer_id, state_key = await self.get_active(db, client_id)
        state = await get_renderer_state_db(db, state_key)
        state["is_playing"] = True
        await update_renderer_status_db(db, state_key, is_playing=True)
        if not is_local_renderer(renderer_id):
            backend = self.registry.get_backend(renderer_id)
            halted = last_stop_reason.get(state_key)
            track = self._current_track(state)
            if halted and track and (
                hasattr(backend, "register_status_listener")
                or halted.get("reason") == "load_failed"
            ):
                # A Cast halt (cancel, error, refused load) ends the media
                # session, so play() has nothing to resume: reload the track
                # and pick up where it stopped. A refused load (any renderer)
                # never got the track onto the device at all.
                await self._play_remote(
                    renderer_id, state_key, track, track.get("user_id"), None, db=db
                )
                position = halted.get("position_seconds") or 0
                if halted.get("reason") != "load_failed" and position > 1:
                    await backend.seek(renderer_id, position)
                return
            await backend.resume(renderer_id)
            if hasattr(backend, "register_status_listener"):
                self._register_status_listener(backend, renderer_id, state_key)
            elif state_key not in playback_monitors or playback_monitors[state_key].done():
                start_monitor_task(state_key)
                monitor_start_times[state_key] = time.time()

    @_heals_stale_renderer
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

    @_heals_stale_renderer
    async def seek(self, db: asyncpg.Connection, client_id: str, seconds: float) -> str:
        renderer_id, state_key = await self.get_active(db, client_id)
        await update_renderer_status_db(db, state_key, position_seconds=seconds)
        if not is_local_renderer(renderer_id):
            await self.registry.get_backend(renderer_id).seek(renderer_id, seconds)
            return "remote"
        return "local"

    @_heals_stale_renderer
    async def set_volume(self, db: asyncpg.Connection, client_id: str, percent: int) -> None:
        renderer_id, state_key = await self.get_active(db, client_id)
        await update_renderer_status_db(db, state_key, volume=percent)
        if not is_local_renderer(renderer_id):
            try:
                await self.registry.get_backend(renderer_id).set_volume(renderer_id, percent)
            except (UpnpError, NotImplementedError) as exc:
                # A device that is slow, busy or briefly unreachable (or one
                # without volume control) is not a server error. The value is already persisted above, so the app
                # stays consistent and the next change will carry it across.
                logger.warning(
                    "Renderer %s rejected volume %d%%: %s", renderer_id, percent, exc
                )

    @_heals_stale_renderer
    async def mute(self, db: asyncpg.Connection, client_id: str, muted: bool) -> bool:
        """Mute/unmute the active remote renderer; returns the new state.

        The local (browser) renderer mutes itself, and a backend without mute
        raises NotImplementedError, which the API turns into a 400.
        """
        renderer_id, state_key = await self.get_active(db, client_id)
        if is_local_renderer(renderer_id):
            raise HTTPException(status_code=409, detail="The browser player mutes itself.")
        status = await self.registry.get_backend(renderer_id).mute(renderer_id, bool(muted))
        result = status.volume_muted if status.volume_muted is not None else bool(muted)
        # Shown by /api/player/state until the renderer reports otherwise.
        note_renderer_muted(state_key, result)
        return result

    @_heals_stale_renderer
    async def skip_to_index(
        self,
        db: asyncpg.Connection,
        client_id: str,
        index: int,
        request: Request | None = None,
    ) -> tuple[dict[str, Any], str]:
        renderer_id, state_key = await self.get_active(db, client_id)
        if is_local_renderer(renderer_id):
            return await self._skip_to_index(db, client_id, renderer_id, state_key, index, request)
        # A load is in flight from the moment current_index moves: statuses
        # of the media still playing must not be followed meanwhile (see
        # _follow_renderer_track).
        _mark_monitor_starting(state_key)
        try:
            return await self._skip_to_index(db, client_id, renderer_id, state_key, index, request)
        finally:
            _clear_monitor_starting(state_key)

    async def _skip_to_index(
        self,
        db: asyncpg.Connection,
        client_id: str,
        renderer_id: str,
        state_key: str,
        index: int,
        request: Request | None,
    ) -> tuple[dict[str, Any], str]:
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
                await self._play_remote(
                    renderer_id, state_key, track, track.get("user_id"), request, db=db
                )
        return state, state_key

    async def _play_remote_background(
        self,
        renderer_id: str,
        state_key: str,
        track: dict[str, Any],
        user_id: int | None,
        request: Request | None,
    ) -> None:
        _mark_monitor_starting(state_key)
        try:
            await self._cancel_monitor(state_key)
            await self._play_remote(renderer_id, state_key, track, user_id, request)
        except RendererLoadError:
            # Already recorded in player state by _play_remote; nobody awaits
            # this task, so don't leave an unobserved exception behind.
            pass
        except ValueError as exc:
            # Nobody is awaiting this task, so a vanished device would otherwise
            # leave the session pinned to it with only an unobserved traceback.
            if not await self._renderer_available(renderer_id):
                async with db_conn() as conn:
                    await self.clear_stale_renderer(conn, renderer_id, exc)
            raise
        finally:
            _clear_monitor_starting(state_key)

    async def _play_remote(
        self,
        renderer_id: str,
        state_key: str,
        track: dict[str, Any],
        user_id: int | None,
        request: Request | None,
        db: asyncpg.Connection | None = None,
    ) -> None:
        """Load a track on a remote renderer.

        Handlers pass their own connection: the load can wait seconds for the
        device, and taking a second pooled connection meanwhile starves the pool.
        """
        _mark_monitor_starting(state_key)
        try:
            renderer_kind = renderer_id.split(":", 1)[0] if ":" in renderer_id else None
            stream = None
            constraints = await self.output_constraints(renderer_id)
            async with self._conn(db) as conn:
                state = await get_renderer_state_db(conn, state_key)
                stream = await build_stream_url(
                    conn,
                    track_id=int(track["id"]),
                    base_url=self._stream_base_url(renderer_kind, request),
                    user_id=user_id or track.get("user_id"),
                    duration_seconds=track.get("duration_seconds"),
                    renderer_kind=renderer_kind,
                    queue=state.get("queue") or [],
                    queue_index=state.get("current_index"),
                    constraints=constraints,
                )
            if stream.plan is not None:
                record_output_plan(state_key, int(track["id"]), stream.plan.as_dict())
                logger.info(
                    "Output plan renderer=%s track_id=%s: %s (%s) -> %s",
                    renderer_id,
                    track.get("id"),
                    stream.plan.action,
                    stream.plan.reason,
                    stream.plan.quality_label,
                )
            context = PlaybackContext(
                base_url=self._base_url(request),
                user_id=user_id or track.get("user_id"),
                token_ttl_seconds=stream_token_ttl_seconds(
                    renderer_kind,
                    track.get("duration_seconds"),
                ),
                stream_url=stream.url,
                stream_mime_type=stream.mime_type,
                stream_claims=stream.claims,
                playback_plan=stream.plan,
            )
            backend = self.registry.get_backend(renderer_id)
            # A new track supersedes whatever halted the last one.
            last_stop_reason.pop(state_key, None)
            try:
                await backend.play_track(renderer_id, track, context)
            except RendererLoadError as exc:
                if exc.reason == "superseded" or not await self._record_load_failure(
                    state_key, track, exc, db=db
                ):
                    # A newer load replaced this one (rapid skips): that load
                    # owns the player state, and this is no failure to report.
                    logger.info(
                        "Load of track %s on %s superseded: %s", track.get("id"), state_key, exc
                    )
                    return
                raise
            if hasattr(backend, "register_status_listener"):
                self._register_status_listener(backend, renderer_id, state_key)
            else:
                start_monitor_task(state_key)
                last_track_start_time[state_key] = time.time()
                # Position/retry bookkeeping is per-track; reset for the new one.
                last_playing_position.pop(state_key, None)
                start_retries.pop(state_key, None)
        finally:
            _clear_monitor_starting(state_key)

    async def output_constraints(self, renderer_id: str) -> RendererConstraints:
        """What this renderer accepts, for planning its audio output.

        Backends may answer themselves (``output_constraints``); otherwise the
        device record's advertised MIME types plus config overrides apply.
        Unknown renderers get no constraints, which plans the original bytes.
        """
        try:
            backend = self.registry.get_backend(renderer_id)
        except ValueError:
            return RendererConstraints()
        hook = getattr(backend, "output_constraints", None)
        if callable(hook):
            try:
                constraints = hook(renderer_id)
                if inspect.iscoroutine(constraints):
                    constraints.close()
                if isinstance(constraints, RendererConstraints):
                    return constraints
            except Exception:
                logger.debug("output_constraints failed for %s", renderer_id, exc_info=True)
        try:
            for device in await backend.list_devices():
                if device.renderer_id == renderer_id:
                    return constraints_for_device(device)
        except Exception:
            logger.debug("Device lookup for constraints failed for %s", renderer_id, exc_info=True)
        return RendererConstraints()

    async def _record_load_failure(
        self,
        state_key: str,
        track: dict[str, Any],
        exc: RendererLoadError,
        db: asyncpg.Connection | None = None,
    ) -> bool:
        """Undo the optimistic is_playing=True for a track the device refused.

        Callers mark the new track as playing before the load is confirmed; a
        rejected or timed-out load must not leave that standing, or the UI
        reports playback that is not happening. Returns False (nothing
        recorded) if a different track has become current since.
        """
        async with self._conn(db) as conn:
            state = await get_renderer_state_db(conn, state_key)
            current = self._current_track(state)
            if current is not None and current.get("id") != track.get("id"):
                # Something else was started meanwhile; leave its state alone.
                return False
            logger.warning(
                "Playback of track %s failed on %s: %s", track.get("id"), state_key, exc
            )
            last_stop_reason[state_key] = {
                "reason": "load_failed",
                "detail": exc.detail or exc.reason,
                "track_id": track.get("id"),
                "position_seconds": 0,
                "at": time.time(),
            }
            state["is_playing"] = False
            state["transport_state"] = "STOPPED"
            state["position_seconds"] = 0
            await update_playback_progress_db(conn, state_key, state)
        return True

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_done)

    def _background_done(self, task: asyncio.Task) -> None:
        self._background_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.warning("Background renderer load failed: %s", task.exception())

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

    @staticmethod
    def _conn(db: asyncpg.Connection | None):
        return nullcontext(db) if db is not None else db_conn()

    def _stream_base_url(self, renderer_kind: str | None, request: Request | None) -> str:
        # UPnP renderers must fetch via the header-recasing proxy (see
        # stream_proxy.py); everything else can use the API port.
        if renderer_kind == "upnp":
            manager = getattr(self.registry.backends.get("upnp"), "manager", None)
            proxy_url = getattr(manager, "renderer_base_url", None)
            if isinstance(proxy_url, str) and proxy_url:
                return proxy_url
        return self._base_url(request)

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
        async with db_conn() as db:
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
        if (
            status.current_track_id is not None
            and hasattr(backend, "register_status_listener")
            and state_key not in self._status_unsubscribers
        ):
            # Our own media, still on the receiver after a server restart:
            # follow it by callbacks again, as if this process had loaded it.
            try:
                self._register_status_listener(backend, renderer_id, state_key)
            except Exception:
                logger.debug("Re-subscribing to %s failed", renderer_id, exc_info=True)
        # Polled from GET /api/player/state: an end-of-track advance must not
        # hold the request (and its connection) for the next track's load.
        return await self._apply_status(
            db, state_key, current_state, status, load_in_background=True
        )

    async def _apply_status(
        self,
        db: asyncpg.Connection,
        state_key: str,
        state: dict[str, Any],
        status: RendererStatus,
        load_in_background: bool = False,
    ) -> dict[str, Any]:
        if status.state == "TRANSITIONING" and status.completion_reported:
            # The backend is mid-load and confirms the outcome itself; statuses
            # from this window describe the media being replaced.
            return state
        has_volume_update = status.volume_percent is not None or status.volume_muted is not None
        if status.state == "UNKNOWN" and not status.current_media_url and not has_volume_update:
            return state
        if status.volume_muted is not None:
            note_renderer_muted(state_key, status.volume_muted)
        if status.current_track_id is not None and (
            status.advanced_by_renderer or status.state in ("PLAYING", "PAUSED")
        ):
            followed = await self._follow_renderer_track(db, state_key, state, status)
            if followed == "loading":
                # Describes media a load in flight is replacing: neither its
                # track, position nor end may move this queue.
                return state
            if followed == "advanced":
                state = await get_renderer_state_db(db, state_key)
            elif followed == "stale":
                # The renderer rolled into a queued item that a queue edit has
                # since replaced: load the real next track (or stop at the end).
                await self._advance_queue_from_status(
                    db, state_key, state, load_in_background=load_in_background
                )
                return await get_renderer_state_db(db, state_key)
        if status.stop_reason:
            last_stop_reason[state_key] = {
                "reason": status.stop_reason,
                "position_seconds": state.get("position_seconds") or 0,
                "at": time.time(),
            }
        elif status.state == "PLAYING" and status.completion_reported:
            last_stop_reason.pop(state_key, None)
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
            await self._advance_queue_from_status(
                db, state_key, state, load_in_background=load_in_background
            )
            state = await get_renderer_state_db(db, state_key)
        else:
            self._maybe_stage_next(status, state_key, state)
        return state

    async def _follow_renderer_track(
        self,
        db: asyncpg.Connection,
        state_key: str,
        state: dict[str, Any],
        status: RendererStatus,
    ) -> str | None:
        """Line the queue up with the track the renderer reports playing.

        "advanced": the renderer moved on to the next queue item by itself
        (it played a staged receiver-queue item, or moved on while the server
        was down and its media was just re-adopted) and current_index moved
        once, without reloading anything. "stale": it rolled into a queued
        item that is no longer next. "loading": a load for this renderer is
        in flight, so the report describes media being replaced. None:
        nothing to do.

        Reporting queue[current + 1] alone is no advance: after Previous the
        old media (now queue[current + 1]) plays on until the new load lands.
        """
        queue = state.get("queue") or []
        idx = state.get("current_index")
        idx = idx if isinstance(idx, int) else -1
        if 0 <= idx < len(queue) and queue[idx].get("id") == status.current_track_id:
            return None
        if self._load_in_flight(state_key):
            logger.debug(
                "Not following track %s on %s: a load is in flight",
                status.current_track_id,
                state_key,
            )
            return "loading"
        if not (status.advanced_by_renderer or status.adopted):
            return None
        next_idx = idx + 1
        if 0 <= next_idx < len(queue) and queue[next_idx].get("id") == status.current_track_id:
            # Conditional on current_index: a skip racing this status wins, and
            # a re-broadcast of the same status cannot advance twice.
            result = await db.execute(
                """
                UPDATE renderer_state
                SET current_index = $1, position_seconds = $2, transport_state = $3,
                    is_playing = $4, updated_at = NOW()
                WHERE renderer_udn = $5 AND current_index = $6
                """,
                next_idx,
                float(status.position_seconds or 0),
                status.state if status.state != "UNKNOWN" else "PLAYING",
                status.state != "PAUSED",
                state_key,
                idx,
            )
            if not result or result.rsplit(" ", 1)[-1] == "0":
                return None
            self._last_ended_at[state_key] = time.time()
            reset_history_tracker(state_key)
            last_stop_reason.pop(state_key, None)
            logger.info(
                "Renderer %s moved on to queued track %s (index %d)",
                state_key,
                status.current_track_id,
                next_idx,
            )
            return "advanced"
        if status.advanced_by_renderer:
            logger.warning(
                "Renderer %s started queued track %s, which is no longer next in the queue",
                state_key,
                status.current_track_id,
            )
            return "stale"
        return None

    # A load marks itself in flight (monitor_starting) and clears the mark
    # when done; a mark older than this is a leak, not a load.
    LOAD_IN_FLIGHT_MAX_S = 120.0

    def _load_in_flight(self, state_key: str) -> bool:
        return _is_monitor_starting(state_key, window_s=self.LOAD_IN_FLIGHT_MAX_S)

    # Let a freshly loaded track settle before queueing the next one behind it.
    STAGE_NEXT_AFTER_S = 10.0
    # Do not retry a refused queue insert for the same track sooner than this.
    STAGE_NEXT_RETRY_S = 60.0

    def _maybe_stage_next(
        self,
        status: RendererStatus,
        state_key: str,
        state: dict[str, Any],
    ) -> None:
        """Keep the renderer's queued next item equal to queue[current + 1].

        Only for backends with a receiver queue (``stage_next``) switched on
        for this renderer. Runs in the background: an insert waits on the
        device.
        """
        if status.state != "PLAYING" or state_key in self._staging_in_flight:
            return
        try:
            backend = self.registry.get_backend(status.renderer_id)
        except ValueError:
            return
        if not hasattr(backend, "stage_next") or not backend.queue_mode_enabled(status.renderer_id):
            return
        if not status.advanced_by_renderer and (status.position_seconds or 0) < self.STAGE_NEXT_AFTER_S:
            return
        queue = state.get("queue") or []
        idx = state.get("current_index")
        if not isinstance(idx, int) or not (0 <= idx < len(queue)):
            return
        if backend.current_load_track_id(status.renderer_id) != queue[idx].get("id"):
            return
        next_idx = idx + 1
        if next_idx >= len(queue):
            # Nothing to queue. An item still staged from before a queue edit
            # must come off the receiver, or it would play it by itself.
            if backend.staged_track_id(status.renderer_id) is None or not hasattr(
                backend, "unstage_next"
            ):
                return
            failed = self._stage_failures.get(state_key)
            if failed and failed[0] is None and time.time() - failed[1] < self.STAGE_NEXT_RETRY_S:
                return
            self._staging_in_flight.add(state_key)
            self._spawn(self._unstage_next_background(backend, status.renderer_id, state_key))
            return
        next_track = queue[next_idx]
        if backend.staged_track_id(status.renderer_id) == next_track.get("id"):
            return
        failed = self._stage_failures.get(state_key)
        if failed and failed[0] == next_track.get("id") and time.time() - failed[1] < self.STAGE_NEXT_RETRY_S:
            return
        current = queue[idx]
        lead = max(
            0.0,
            float(current.get("duration_seconds") or 0) - float(status.position_seconds or 0),
        )
        self._staging_in_flight.add(state_key)
        self._spawn(
            self._stage_next_background(backend, status.renderer_id, state_key, next_idx, lead)
        )

    async def _unstage_next_background(self, backend: Any, renderer_id: str, state_key: str) -> None:
        """Take the staged item off the receiver (QUEUE_REMOVE). A refusal is
        not retried for STAGE_NEXT_RETRY_S (recorded as a failure for None);
        the item is then still caught as stale if the receiver plays it."""
        try:
            if await backend.unstage_next(renderer_id):
                self._stage_failures.pop(state_key, None)
            else:
                self._stage_failures[state_key] = (None, time.time())
        except Exception:
            logger.warning("Removing the queued track on %s failed", state_key, exc_info=True)
            self._stage_failures[state_key] = (None, time.time())
        finally:
            self._staging_in_flight.discard(state_key)

    async def _stage_next_background(
        self,
        backend: Any,
        renderer_id: str,
        state_key: str,
        next_idx: int,
        lead_seconds: float,
    ) -> None:
        track: dict[str, Any] | None = None
        try:
            renderer_kind = renderer_id.split(":", 1)[0]
            # Planned exactly like a load of the same track (_play_remote):
            # the receiver gets the bytes, MIME and plan it would on a LOAD.
            constraints = await self.output_constraints(renderer_id)
            async with db_conn() as conn:
                state = await get_renderer_state_db(conn, state_key)
                queue = state.get("queue") or []
                if not (0 <= next_idx < len(queue)) or state.get("current_index") != next_idx - 1:
                    return
                track = await enrich_track_metadata(queue[next_idx], conn)
                if not track_path_exists(track):
                    logger.info("Not queueing missing track %s on %s", track.get("id"), state_key)
                    self._stage_failures[state_key] = (track.get("id"), time.time())
                    return
                stream = await build_stream_url(
                    conn,
                    track_id=int(track["id"]),
                    base_url=self._stream_base_url(renderer_kind, None),
                    user_id=track.get("user_id"),
                    duration_seconds=track.get("duration_seconds"),
                    renderer_kind=renderer_kind,
                    queue=queue,
                    queue_index=next_idx,
                    ttl_seconds=staged_stream_token_ttl_seconds(
                        lead_seconds, track.get("duration_seconds")
                    ),
                    constraints=constraints,
                )
            if stream.plan is not None:
                # Keyed by track: still there once the staged item is current.
                record_output_plan(state_key, int(track["id"]), stream.plan.as_dict())
            context = PlaybackContext(
                base_url=self._base_url(None),
                user_id=track.get("user_id"),
                stream_url=stream.url,
                stream_mime_type=stream.mime_type,
                stream_claims=stream.claims,
                playback_plan=stream.plan,
            )
            if not await backend.stage_next(renderer_id, track, context):
                self._stage_failures[state_key] = (track.get("id"), time.time())
            else:
                self._stage_failures.pop(state_key, None)
        except Exception:
            logger.warning("Queueing the next track on %s failed", state_key, exc_info=True)
            if track is not None:
                self._stage_failures[state_key] = (track.get("id"), time.time())
        finally:
            self._staging_in_flight.discard(state_key)

    @staticmethod
    def _detect_track_ended(
        state: dict[str, Any],
        status: RendererStatus,
        prev_position: float,
    ) -> bool:
        """Detect track completion from position vs duration.

        Uses the larger of previous and current position because some
        devices reset position to 0 on idle.  Only triggers when the
        device is not actively playing or paused.  Skipped for backends that
        report completion explicitly (Cast's idleReason): there, an idle near
        the end may be a cancel or an error, which must not advance the queue.
        """
        if status.completion_reported:
            return False
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
        load_in_background: bool = False,
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
        if load_in_background:
            # The queue has already moved (and the debounce above is set), so
            # this load happens once; it takes its own connection.
            self._spawn(
                self._play_remote_background(
                    renderer_id, state_key, track, track.get("user_id"), None
                )
            )
            return
        try:
            await self._play_remote(
                renderer_id, state_key, track, track.get("user_id"), None, db=db
            )
        except RendererLoadError:
            # Recorded (stopped + load_failed) by _play_remote; halt here
            # rather than skipping through the queue on a failing device.
            pass

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
