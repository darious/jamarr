from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import threading
import time
from datetime import timedelta
from typing import Any, Awaitable, Callable

from app.auth_tokens import create_stream_token
from app.services.renderer.cast_capability import (
    PROFILE_MIME,
    CastProfile,
    get_capability,
    plan_attempts,
    record_failure,
    record_success,
    track_quality_from_track,
)
from app.services.renderer.contracts import (
    PlaybackContext,
    RendererBackend,
    RendererCapabilities,
    RendererDevice,
    RendererStatus,
    make_renderer_id,
    split_renderer_id,
)

logger = logging.getLogger(__name__)


class _CastStatusListener:
    def __init__(
        self,
        backend: "CastRendererBackend",
        renderer_id: str,
        callback: Callable[[RendererStatus], Awaitable[None]],
    ) -> None:
        self.backend = backend
        self.renderer_id = renderer_id
        self.callback = callback
        self.last_state = "UNKNOWN"
        self.started_at = time.time()

    def new_media_status(self, status: Any) -> None:
        renderer_status = self.backend.status_from_media_status(
            self.renderer_id,
            status,
            receiver_status=self.backend.receiver_status_for_renderer(self.renderer_id),
            previous_state=self.last_state,
            started_at=self.started_at,
        )
        self.last_state = renderer_status.state
        self.backend.dispatch_status_callback(self.callback, renderer_status)


class CastRendererBackend(RendererBackend):
    kind = "cast"

    def __init__(
        self,
        known_hosts: list[str] | None = None,
        discovery_timeout: float = 5,
        launch_timeout: float = 10,
        chromecast_getter: Callable[..., Any] | None = None,
    ) -> None:
        self.known_hosts = known_hosts if known_hosts is not None else self._known_hosts_from_env()
        self.discovery_timeout = discovery_timeout
        self.launch_timeout = launch_timeout
        self.chromecast_getter = chromecast_getter
        self.browser: Any | None = None
        self.casts: dict[str, Any] = {}
        self.devices: dict[str, RendererDevice] = {}
        self._listeners: dict[str, list[_CastStatusListener]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._discovery_lock = asyncio.Lock()
        # Per-renderer transient progress message (e.g. "Finding a
        # compatible audio format…"). Surfaced through the orchestrator
        # so UIs can render it without re-deriving it from internal state.
        self._progress_messages: dict[str, str] = {}
        # Per-renderer "load chain settled" event. Set when the current
        # capability-walk has either succeeded or exhausted every
        # profile. Tests await this; production code ignores it.
        self._load_settled: dict[str, asyncio.Event] = {}

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        try:
            await self.discover(refresh=True)
        except Exception as exc:
            logger.warning("Cast startup discovery failed: %s", exc)

    async def stop(self) -> None:
        browser = self.browser
        self.browser = None
        if browser and hasattr(browser, "stop_discovery"):
            await asyncio.to_thread(browser.stop_discovery)
        for cast in list(self.casts.values()):
            if hasattr(cast, "disconnect"):
                try:
                    await asyncio.to_thread(cast.disconnect, 1)
                except Exception:
                    logger.debug("Error disconnecting Cast device", exc_info=True)

    async def discover(self, refresh: bool = False) -> list[RendererDevice]:
        if refresh or not self.devices:
            async with self._discovery_lock:
                casts, browser = await asyncio.to_thread(self._get_chromecasts_blocking)
                if browser:
                    old_browser = self.browser
                    self.browser = browser
                    if old_browser and old_browser is not browser and hasattr(old_browser, "stop_discovery"):
                        await asyncio.to_thread(old_browser.stop_discovery)
                for cast in casts:
                    self._register_cast(cast)
        return await self.list_devices()

    async def add_manual(self, address: str) -> RendererDevice | None:
        casts, browser = await asyncio.to_thread(
            self._get_chromecasts_blocking,
            [address],
            self.discovery_timeout,
        )
        if browser and hasattr(browser, "stop_discovery"):
            await asyncio.to_thread(browser.stop_discovery)
        for cast in casts:
            device = self._register_cast(cast)
            if device.ip == address:
                return device
        return self._device_matching_address(address)

    async def list_devices(self) -> list[RendererDevice]:
        return sorted(self.devices.values(), key=lambda device: device.name.lower())

    async def unload_device(self, renderer_id: str) -> None:
        _, uuid = split_renderer_id(renderer_id)
        cast = self.casts.pop(uuid, None)
        self.devices.pop(uuid, None)
        self._listeners.pop(renderer_id, None)
        if cast and hasattr(cast, "disconnect"):
            await asyncio.to_thread(cast.disconnect, 1)

    async def play_track(
        self,
        renderer_id: str,
        track: dict[str, Any],
        context: PlaybackContext,
    ) -> RendererStatus:
        """Issue a Cast load and return PLAYING immediately.

        The capability-hierarchy walk runs as a background callback chain:
        every ``play_media`` invocation passes a callback that, on
        failure, persists the failed profile and re-issues ``play_media``
        with the next profile in the plan. This keeps the player API
        responsive (no blocking on Cast receiver round-trips) and matches
        pychromecast's natural load-then-callback semantics.
        """

        cast = await self._get_ready_cast(renderer_id)
        await asyncio.to_thread(
            cast.start_app, self._media_receiver_app_id(), True, self.launch_timeout
        )

        self._set_progress_message(renderer_id, "Starting playback…")
        # Reset settled-event for this play call so tests/observers can
        # await chain completion without seeing stale state.
        self._load_settled[renderer_id] = asyncio.Event()

        pool = self._safe_pool()
        if pool is None:
            # No DB available (test environments, transient init); fall
            # back to the legacy single-attempt original-FLAC path.
            status = await self._submit_attempt(
                cast=cast,
                renderer_id=renderer_id,
                track=track,
                context=context,
                profile=CastProfile.ORIGINAL_FLAC,
                remaining=[],
                quality=None,
                pool=None,
            )
            self._load_settled[renderer_id].set()
            return status

        quality = track_quality_from_track(track)
        async with pool.acquire() as db:
            cap = await get_capability(db, renderer_id)
        decision = plan_attempts(quality, cap, [])
        if not decision.plan:
            self._load_settled[renderer_id].set()
            raise RuntimeError(
                f"No Cast playback profiles available for renderer {renderer_id}"
            )

        first_profile = decision.plan[0]
        if first_profile == CastProfile.MP3_320:
            self._set_progress_message(
                renderer_id,
                "Using emergency compatibility mode (MP3 320 kbps)",
            )

        return await self._submit_attempt(
            cast=cast,
            renderer_id=renderer_id,
            track=track,
            context=context,
            profile=first_profile,
            remaining=decision.plan[1:],
            quality=quality,
            pool=pool,
        )

    async def _submit_attempt(
        self,
        cast: Any,
        renderer_id: str,
        track: dict[str, Any],
        context: PlaybackContext,
        profile: CastProfile,
        remaining: list[CastProfile],
        quality: Any,
        pool: Any,
    ) -> RendererStatus:
        media_url = self._stream_url(track, context, profile)
        mime_type = PROFILE_MIME[profile]
        metadata = self._media_metadata(track, context)
        thumb = self._art_url(track, context)
        logger.info(
            "Cast play attempt renderer=%s track_id=%s profile=%s mime=%s url=%s",
            renderer_id,
            track.get("id"),
            profile.value,
            mime_type,
            media_url.split("?", 1)[0],
        )

        loop = asyncio.get_running_loop()
        callback = self._make_load_callback(
            cast=cast,
            renderer_id=renderer_id,
            track=track,
            context=context,
            profile=profile,
            remaining=remaining,
            quality=quality,
            pool=pool,
            loop=loop,
        )

        await asyncio.to_thread(
            cast.media_controller.play_media,
            media_url,
            mime_type,
            title=track.get("title") or "Unknown Track",
            thumb=thumb,
            metadata=metadata,
            stream_type=self._stream_type(),
            callback_function=callback,
        )

        return RendererStatus(
            renderer_id=renderer_id,
            state="PLAYING",
            current_media_url=media_url,
        )

    def _make_load_callback(
        self,
        cast: Any,
        renderer_id: str,
        track: dict[str, Any],
        context: PlaybackContext,
        profile: CastProfile,
        remaining: list[CastProfile],
        quality: Any,
        pool: Any,
        loop: asyncio.AbstractEventLoop,
    ) -> Callable[[bool, Any], None]:
        track_id = int(track["id"])

        def callback(success: bool, response: Any) -> None:
            if success:
                logger.info(
                    "Cast load accepted renderer=%s track_id=%s profile=%s",
                    renderer_id,
                    track_id,
                    profile.value,
                )
            else:
                logger.warning(
                    "Cast load failed renderer=%s track_id=%s profile=%s response=%s",
                    renderer_id,
                    track_id,
                    profile.value,
                    response,
                )
            if pool is None or quality is None:
                # Legacy / DB-less path: nothing to record, no retry.
                self._signal_settled(renderer_id, loop)
                return
            coro = self._handle_load_result(
                cast=cast,
                renderer_id=renderer_id,
                track=track,
                context=context,
                profile=profile,
                remaining=remaining,
                quality=quality,
                pool=pool,
                success=bool(success),
                response=response,
            )
            try:
                loop.call_soon_threadsafe(asyncio.ensure_future, coro)
            except RuntimeError:
                # Event loop already closed; nothing else to do.
                logger.debug(
                    "Cast load callback dropped (loop closed) renderer=%s",
                    renderer_id,
                )

        return callback

    async def _handle_load_result(
        self,
        cast: Any,
        renderer_id: str,
        track: dict[str, Any],
        context: PlaybackContext,
        profile: CastProfile,
        remaining: list[CastProfile],
        quality: Any,
        pool: Any,
        success: bool,
        response: Any,
    ) -> None:
        try:
            async with pool.acquire() as db:
                if success:
                    await record_success(db, renderer_id, profile, quality)
                else:
                    await record_failure(
                        db,
                        renderer_id,
                        profile,
                        quality,
                        self._extract_failure_reason(response),
                    )
        except Exception:
            logger.exception(
                "Cast capability persistence failed renderer=%s profile=%s",
                renderer_id,
                profile.value,
            )

        if success:
            # Spec: "If MP3 is used: make clear it is emergency
            # compatibility mode." Persist the emergency message so the
            # UI can keep it visible while playback runs; otherwise
            # clear the transient "Starting…" / "Finding…" message.
            if profile != CastProfile.MP3_320:
                self._clear_progress_message(renderer_id)
            self._signal_settled(renderer_id, asyncio.get_running_loop())
            return

        if not remaining:
            self._set_progress_message(
                renderer_id, "Could not play this track on Cast"
            )
            self._signal_settled(renderer_id, asyncio.get_running_loop())
            return

        next_profile = remaining[0]
        rest = remaining[1:]
        if next_profile == CastProfile.MP3_320:
            self._set_progress_message(
                renderer_id,
                "Using emergency compatibility mode (MP3 320 kbps)",
            )
        else:
            self._set_progress_message(
                renderer_id, "Finding a compatible audio format…"
            )

        await self._submit_attempt(
            cast=cast,
            renderer_id=renderer_id,
            track=track,
            context=context,
            profile=next_profile,
            remaining=rest,
            quality=quality,
            pool=pool,
        )

    def _signal_settled(
        self, renderer_id: str, loop: asyncio.AbstractEventLoop
    ) -> None:
        event = self._load_settled.get(renderer_id)
        if event is None:
            return
        if loop.is_running():
            loop.call_soon_threadsafe(event.set)
        else:
            event.set()

    async def wait_for_load_settled(
        self, renderer_id: str, timeout: float = 5.0
    ) -> bool:
        """Test/diagnostic helper: wait until the current capability walk
        finishes (success or exhaustion). Returns True when settled."""

        event = self._load_settled.get(renderer_id)
        if event is None:
            return True
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    @staticmethod
    def _extract_failure_reason(response: Any) -> str:
        if response is None:
            return "Cast load failed"
        if isinstance(response, dict):
            for key in ("reason", "error", "type", "detailedErrorCode", "errorReason"):
                value = response.get(key)
                if value:
                    return str(value)
        return str(response)[:200]

    def _set_progress_message(self, renderer_id: str, message: str) -> None:
        self._progress_messages[renderer_id] = message
        logger.info("Cast progress renderer=%s message=%s", renderer_id, message)

    def _clear_progress_message(self, renderer_id: str) -> None:
        self._progress_messages.pop(renderer_id, None)

    def get_progress_message(self, renderer_id: str) -> str | None:
        return self._progress_messages.get(renderer_id)

    @staticmethod
    def _safe_pool():
        try:
            from app.db import get_pool

            return get_pool()
        except Exception:
            return None

    async def pause(self, renderer_id: str) -> RendererStatus:
        cast = await self._get_ready_cast(renderer_id)
        await asyncio.to_thread(cast.media_controller.pause)
        return RendererStatus(renderer_id=renderer_id, state="PAUSED")

    async def resume(self, renderer_id: str) -> RendererStatus:
        cast = await self._get_ready_cast(renderer_id)
        await asyncio.to_thread(cast.media_controller.play)
        return RendererStatus(renderer_id=renderer_id, state="PLAYING")

    async def stop_playback(self, renderer_id: str) -> RendererStatus:
        cast = await self._get_ready_cast(renderer_id)
        try:
            await asyncio.to_thread(cast.media_controller.stop)
        except Exception:
            logger.debug("Cast media stop failed for %s", renderer_id, exc_info=True)
        if hasattr(cast, "quit_app"):
            try:
                await asyncio.to_thread(cast.quit_app, self.launch_timeout)
            except Exception:
                logger.debug("Cast app quit failed for %s", renderer_id, exc_info=True)
        return RendererStatus(renderer_id=renderer_id, state="STOPPED")

    async def seek(self, renderer_id: str, seconds: float) -> RendererStatus:
        cast = await self._get_ready_cast(renderer_id)
        await asyncio.to_thread(cast.media_controller.seek, seconds)
        return RendererStatus(renderer_id=renderer_id, state="PLAYING", position_seconds=seconds)

    async def set_volume(self, renderer_id: str, percent: int) -> RendererStatus:
        cast = await self._get_ready_cast(renderer_id)
        bounded = max(0, min(100, int(percent)))
        await asyncio.to_thread(cast.set_volume, bounded / 100.0)
        return RendererStatus(renderer_id=renderer_id, state="UNKNOWN", volume_percent=bounded)

    async def mute(self, renderer_id: str, muted: bool) -> RendererStatus:
        cast = await self._get_ready_cast(renderer_id)
        await asyncio.to_thread(cast.set_volume_muted, muted)
        return RendererStatus(renderer_id=renderer_id, state="UNKNOWN", volume_muted=muted)

    async def get_status(self, renderer_id: str) -> RendererStatus:
        cast = await self._get_ready_cast(renderer_id)
        controller = cast.media_controller
        await asyncio.to_thread(self._refresh_controller_status, controller, renderer_id)
        status = getattr(controller, "status", None)
        return self.status_from_media_status(
            renderer_id,
            status,
            receiver_status=getattr(cast, "status", None),
            trust_idle=True,
        )

    def register_status_listener(
        self,
        renderer_id: str,
        callback: Callable[[RendererStatus], Awaitable[None]],
    ) -> Callable[[], None]:
        _, uuid = split_renderer_id(renderer_id)
        cast = self.casts[uuid]
        listener = _CastStatusListener(self, renderer_id, callback)
        cast.media_controller.register_status_listener(listener)
        self._listeners.setdefault(renderer_id, []).append(listener)

        def unsubscribe() -> None:
            try:
                cast.media_controller._status_listeners.remove(listener)
            except (ValueError, AttributeError):
                pass
            try:
                self._listeners.get(renderer_id, []).remove(listener)
            except ValueError:
                pass

        return unsubscribe

    def dispatch_status_callback(
        self,
        callback: Callable[[RendererStatus], Awaitable[None]],
        status: RendererStatus,
    ) -> None:
        loop = self._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(lambda: asyncio.create_task(callback(status)))
            return
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        running_loop.create_task(callback(status))

    def status_from_media_status(
        self,
        renderer_id: str,
        status: Any,
        receiver_status: Any | None = None,
        previous_state: str = "UNKNOWN",
        started_at: float | None = None,
        *,
        trust_idle: bool = False,
    ) -> RendererStatus:
        player_state = getattr(status, "player_state", None)
        state = self.normalize_player_state(player_state)
        current_time = getattr(status, "adjusted_current_time", None)
        if current_time is None:
            current_time = getattr(status, "current_time", 0) or 0
        duration = getattr(status, "duration", None)
        volume = self._status_attr(receiver_status, "volume_level")
        if volume is None:
            volume = self._status_attr(status, "volume_level")
        volume_muted = self._status_attr(receiver_status, "volume_muted")
        if volume_muted is None:
            volume_muted = self._status_attr(status, "volume_muted")
        ended = (
            state == "IDLE"
            and previous_state == "PLAYING"
            and (started_at is None or time.time() - started_at > 3)
        )
        if state == "IDLE" and not ended and not trust_idle:
            state = "UNKNOWN"
        return RendererStatus(
            renderer_id=renderer_id,
            state=state,
            position_seconds=float(current_time or 0),
            duration_seconds=float(duration) if duration is not None else None,
            volume_percent=round(float(volume) * 100) if volume is not None else None,
            volume_muted=volume_muted,
            current_media_url=getattr(status, "content_id", None),
            ended=ended,
        )

    def receiver_status_for_renderer(self, renderer_id: str) -> Any | None:
        _, uuid = split_renderer_id(renderer_id)
        return getattr(self.casts.get(uuid), "status", None)

    @staticmethod
    def _status_attr(status: Any, name: str) -> Any | None:
        return getattr(status, name, None) if status is not None else None

    @staticmethod
    def normalize_player_state(player_state: str | None) -> str:
        if player_state in {"PLAYING", "BUFFERING"}:
            return "PLAYING"
        if player_state == "PAUSED":
            return "PAUSED"
        if player_state == "IDLE":
            return "IDLE"
        return "UNKNOWN"

    def _get_chromecasts_blocking(
        self,
        known_hosts: list[str] | None = None,
        discovery_timeout: float | None = None,
    ) -> tuple[list[Any], Any | None]:
        getter = self.chromecast_getter
        if getter is None:
            import pychromecast

            getter = pychromecast.get_chromecasts
        result = getter(
            tries=1,
            timeout=5,
            retry_wait=1,
            blocking=True,
            known_hosts=known_hosts if known_hosts is not None else self.known_hosts,
        )
        if isinstance(result, tuple):
            return result
        return [], result

    def _register_cast(self, cast: Any) -> RendererDevice:
        uuid = str(getattr(cast, "uuid", None) or getattr(getattr(cast, "cast_info", None), "uuid"))
        device = RendererDevice(
            renderer_id=make_renderer_id(self.kind, uuid),
            kind=self.kind,
            native_id=uuid,
            udn=make_renderer_id(self.kind, uuid),
            name=getattr(cast, "name", None)
            or getattr(getattr(cast, "cast_info", None), "friendly_name", None)
            or "Cast Renderer",
            ip=self._cast_ip(cast),
            manufacturer=getattr(getattr(cast, "cast_info", None), "manufacturer", None),
            model_name=getattr(cast, "model_name", None)
            or getattr(getattr(cast, "cast_info", None), "model_name", None),
            cast_type=getattr(cast, "cast_type", None)
            or getattr(getattr(cast, "cast_info", None), "cast_type", None),
            discovered_by="server",
            capabilities=RendererCapabilities(
                can_mute=True,
                supports_events=True,
                supported_mime_types={"audio/flac", "audio/mpeg", "audio/mp4", "audio/wav", "audio/ogg"},
            ),
            is_group=(getattr(cast, "cast_type", None) == "group"),
        )
        self.casts[uuid] = cast
        self.devices[uuid] = device
        return device

    async def _get_ready_cast(self, renderer_id: str) -> Any:
        _, uuid = split_renderer_id(renderer_id)
        cast = self.casts.get(uuid)
        if not cast:
            await self.discover(refresh=True)
            cast = self.casts.get(uuid)
        if not cast:
            raise ValueError(f"Cast renderer {renderer_id} not found")
        await asyncio.to_thread(cast.wait, 10)
        return cast

    def _device_matching_address(self, address: str) -> RendererDevice | None:
        for device in self.devices.values():
            if device.ip == address or device.native_id == address:
                return device
        return None

    @staticmethod
    def _known_hosts_from_env() -> list[str]:
        raw = os.getenv("CAST_KNOWN_HOSTS", "")
        return [item.strip() for item in raw.split(",") if item.strip()]

    @staticmethod
    def _cast_ip(cast: Any) -> str | None:
        cast_info = getattr(cast, "cast_info", None)
        if getattr(cast_info, "host", None):
            return cast_info.host
        uri = getattr(cast, "uri", "")
        return uri.split(":", 1)[0] if uri else None

    @staticmethod
    def _refresh_controller_status(controller: Any, renderer_id: str, timeout: float = 1.0) -> None:
        if not hasattr(controller, "update_status"):
            return
        done = threading.Event()

        def callback(success: bool, response: dict[str, Any] | None) -> None:
            done.set()

        try:
            controller.update_status(callback_function=callback)
            done.wait(timeout)
        except Exception:
            logger.debug("Cast status refresh failed for %s", renderer_id, exc_info=True)

    @staticmethod
    def _media_receiver_app_id() -> str:
        try:
            from pychromecast.controllers.media import APP_MEDIA_RECEIVER

            return APP_MEDIA_RECEIVER
        except Exception:
            return "CC1AD845"

    @staticmethod
    def _stream_type() -> str:
        try:
            from pychromecast.controllers.media import STREAM_TYPE_BUFFERED

            return STREAM_TYPE_BUFFERED
        except Exception:
            return "BUFFERED"

    @staticmethod
    def _mime_type(track: dict[str, Any]) -> str:
        mime_type = track.get("mime")
        if mime_type:
            return mime_type
        guessed, _ = mimetypes.guess_type(track.get("path") or "")
        return guessed or "audio/flac"

    @staticmethod
    def _stream_url(
        track: dict[str, Any],
        context: PlaybackContext,
        profile: CastProfile | None = None,
    ) -> str:
        expires_delta = (
            timedelta(seconds=context.token_ttl_seconds)
            if context.token_ttl_seconds
            else None
        )
        token = create_stream_token(
            int(track["id"]),
            user_id=context.user_id or track.get("user_id"),
            expires_delta=expires_delta,
        )
        url = f"{context.base_url}/api/stream/{track['id']}?token={token}"
        if profile is not None and profile != CastProfile.ORIGINAL_FLAC:
            url = f"{url}&profile={profile.value}"
        return url

    @staticmethod
    def _art_url(track: dict[str, Any], context: PlaybackContext) -> str | None:
        if not track.get("art_sha1"):
            return None
        return f"{context.base_url}/art/file/{track['art_sha1']}?max_size=600"

    def _media_metadata(self, track: dict[str, Any], context: PlaybackContext) -> dict[str, Any]:
        images = []
        art_url = self._art_url(track, context)
        if art_url:
            images.append({"url": art_url})
        return {
            "metadataType": 3,
            "title": track.get("title") or "Unknown Track",
            "artist": track.get("artist") or self._artists_text(track),
            "albumName": track.get("album") or "",
            "images": images,
        }

    @staticmethod
    def _artists_text(track: dict[str, Any]) -> str:
        artists = track.get("artists") or []
        if isinstance(artists, list):
            return ", ".join(item.get("name", "") for item in artists if isinstance(item, dict)) or "Unknown Artist"
        return str(artists or "Unknown Artist")

    @staticmethod
    def _load_callback(renderer_id: str, track_id: int) -> Callable[[bool, dict[str, Any] | None], None]:
        def callback(success: bool, response: dict[str, Any] | None) -> None:
            if success:
                logger.info("Cast load accepted renderer=%s track_id=%s", renderer_id, track_id)
            else:
                logger.warning(
                    "Cast load failed renderer=%s track_id=%s response=%s",
                    renderer_id,
                    track_id,
                    response,
                )

        return callback
