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
        browser_factory: Callable[["CastRendererBackend"], Any] | None = None,
        cast_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        self.known_hosts = known_hosts if known_hosts is not None else self._known_hosts_from_env()
        self.discovery_timeout = discovery_timeout
        self.launch_timeout = launch_timeout
        self.browser_factory = browser_factory
        self.cast_factory = cast_factory
        self.browser: Any | None = None
        self._zconf: Any | None = None
        self.casts: dict[str, Any] = {}
        self.devices: dict[str, RendererDevice] = {}
        self._listeners: dict[str, list[_CastStatusListener]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._discovery_lock = asyncio.Lock()

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        try:
            async with self._discovery_lock:
                await self._ensure_browser()
                self._sweep_browser_devices()
        except Exception as exc:
            logger.warning("Cast startup discovery failed: %s", exc)

    async def stop(self) -> None:
        browser = self.browser
        self.browser = None
        zconf = self._zconf
        self._zconf = None
        if browser and hasattr(browser, "stop_discovery"):
            try:
                # Also closes the zeroconf instance when the mDNS browser ran.
                await asyncio.to_thread(browser.stop_discovery)
            except Exception:
                logger.debug("Cast browser stop failed", exc_info=True)
        if zconf is not None and hasattr(zconf, "close"):
            try:
                # Idempotent; covers the case where mDNS never started.
                await asyncio.to_thread(zconf.close)
            except Exception:
                logger.debug("Zeroconf close failed", exc_info=True)
        for cast in list(self.casts.values()):
            if hasattr(cast, "disconnect"):
                try:
                    await asyncio.to_thread(cast.disconnect, 1)
                except Exception:
                    logger.debug("Error disconnecting Cast device", exc_info=True)

    async def discover(self, refresh: bool = False) -> list[RendererDevice]:
        async with self._discovery_lock:
            started = await self._ensure_browser()
            if started and not self.devices and self.discovery_timeout > 0:
                # The browser has only just begun listening; give the initial
                # mDNS burst a moment so the first listing isn't empty.
                await asyncio.sleep(min(self.discovery_timeout, 5))
            self._sweep_browser_devices()
        return await self.list_devices()

    async def add_manual(self, address: str) -> RendererDevice | None:
        if address not in self.known_hosts:
            self.known_hosts.append(address)
        async with self._discovery_lock:
            await self._ensure_browser()
            host_browser = getattr(self.browser, "host_browser", None)
            if host_browser is not None and hasattr(host_browser, "add_hosts"):
                # Persist the host in the running browser (polled every cycle).
                host_browser.add_hosts([address])
            self._sweep_browser_devices()
        device = self._device_matching_address(address)
        if device:
            return device
        # The host browser only polls every ~30s; probe directly so the manual
        # add gives immediate feedback.
        cast_info = await asyncio.to_thread(self._probe_host, address)
        if cast_info is not None:
            self._register_cast_info(cast_info.uuid, cast_info)
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
        cast = await self._get_ready_cast(renderer_id)
        await asyncio.to_thread(cast.start_app, self._media_receiver_app_id(), True, self.launch_timeout)
        media_url = self._stream_url(track, context)
        mime_type = self._mime_type(track)
        metadata = self._media_metadata(track, context)
        thumb = self._art_url(track, context)
        logger.info(
            "Cast play requested renderer=%s track_id=%s mime=%s url=%s",
            renderer_id,
            track.get("id"),
            mime_type,
            media_url.split("?", 1)[0],
        )
        await asyncio.to_thread(
            cast.media_controller.play_media,
            media_url,
            mime_type,
            title=track.get("title") or "Unknown Track",
            thumb=thumb,
            metadata=metadata,
            stream_type=self._stream_type(),
            callback_function=self._load_callback(renderer_id, int(track["id"])),
        )
        return RendererStatus(renderer_id=renderer_id, state="PLAYING", current_media_url=media_url)

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
        cast = self.casts.get(uuid)
        if cast is None:
            raise ValueError(f"Cast renderer {renderer_id} has no connected client yet")
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

    async def _ensure_browser(self) -> bool:
        """Start the persistent CastBrowser once; returns True if started now.

        The browser listens for mDNS announcements continuously, so devices
        register themselves whenever they come online — unlike the previous
        one-shot get_chromecasts() scan, which missed devices (Google TVs in
        standby) that take longer than the scan window to answer.
        """
        if self.browser is not None:
            return False
        if self.browser_factory is not None:
            browser = self.browser_factory(self)
        else:
            import pychromecast
            import zeroconf

            self._zconf = zeroconf.Zeroconf()
            listener = pychromecast.discovery.SimpleCastListener(
                add_callback=self._on_cast_added,
                remove_callback=self._on_cast_removed,
                update_callback=self._on_cast_updated,
            )
            browser = pychromecast.discovery.CastBrowser(
                listener, self._zconf, self.known_hosts or None
            )
        await asyncio.to_thread(browser.start_discovery)
        self.browser = browser
        return True

    # Listener callbacks run on zeroconf worker threads.
    def _on_cast_added(self, uuid: Any, _service: str | None = None) -> None:
        self._register_from_browser(uuid)

    def _on_cast_updated(self, uuid: Any, _service: str | None = None) -> None:
        self._register_from_browser(uuid)

    def _on_cast_removed(self, uuid: Any, _service: str | None = None, _cast_info: Any = None) -> None:
        key = str(uuid)
        device = self.devices.pop(key, None)
        cast = self.casts.pop(key, None)
        if device:
            logger.info("Cast device removed: %s", device.name)
        if cast and hasattr(cast, "disconnect"):
            loop = self._loop
            if loop and loop.is_running():
                loop.call_soon_threadsafe(
                    lambda: loop.run_in_executor(None, self._safe_disconnect, cast)
                )
            else:
                self._safe_disconnect(cast)

    @staticmethod
    def _safe_disconnect(cast: Any) -> None:
        try:
            cast.disconnect(1)
        except Exception:
            logger.debug("Error disconnecting Cast device", exc_info=True)

    def _register_from_browser(self, uuid: Any) -> None:
        browser = self.browser
        if browser is None:
            return
        cast_info = (getattr(browser, "devices", None) or {}).get(uuid)
        if cast_info is None:
            return
        self._register_cast_info(uuid, cast_info)

    def _sweep_browser_devices(self) -> None:
        """Register anything the browser knows that we have not seen yet."""
        browser = self.browser
        if browser is None:
            return
        for uuid, cast_info in dict(getattr(browser, "devices", None) or {}).items():
            if str(uuid) not in self.devices:
                self._register_cast_info(uuid, cast_info)

    def _register_cast_info(self, uuid: Any, cast_info: Any) -> RendererDevice | None:
        """Record the device (pure data, safe from any thread) and arrange for
        its Cast client to exist.

        Client creation must NOT happen inline here: zeroconf runs its own
        asyncio loop and fires our listener callbacks inside it, while
        pychromecast's Chromecast constructor can do a blocking service lookup
        (when the announcement's cast type is not resolved yet), which raises
        "Use AsyncServiceInfo.async_request from the event loop". Defer it to
        a worker thread via our loop instead.
        """
        key = str(uuid)
        first_seen = key not in self.devices
        device = self._device_from_info(key, cast_info, self.casts.get(key))
        self.devices[key] = device
        if first_seen:
            logger.info(
                "Cast device discovered: %s (%s)",
                device.name,
                device.ip or "?",
            )
        if key not in self.casts:
            if self.cast_factory is not None:
                # Injected factories (tests) are cheap and non-blocking.
                self.casts[key] = self.cast_factory(cast_info)
            else:
                loop = self._loop
                if loop and loop.is_running():
                    loop.call_soon_threadsafe(
                        lambda: loop.create_task(self._connect_cast_client(key, cast_info))
                    )
                # No loop yet: _get_ready_cast creates the client lazily.
        return device

    async def _connect_cast_client(self, key: str, cast_info: Any) -> None:
        if key in self.casts:
            return
        try:
            cast = await asyncio.to_thread(self._create_cast, cast_info)
        except Exception:
            logger.warning(
                "Failed to create Cast client for %s",
                getattr(cast_info, "friendly_name", key),
                exc_info=True,
            )
            return
        self.casts.setdefault(key, cast)

    def _create_cast(self, cast_info: Any) -> Any:
        if self.cast_factory is not None:
            return self.cast_factory(cast_info)
        import pychromecast

        # Cheap until .wait() connects it (done lazily in _get_ready_cast),
        # except when the cast type needs a blocking lookup — hence worker
        # threads only, never the event loop or zeroconf callbacks.
        return pychromecast.get_chromecast_from_cast_info(cast_info, self._zconf)

    def _probe_host(self, address: str) -> Any | None:
        if self.browser_factory is not None:
            # Injected browsers (tests) surface everything via .devices.
            return None
        try:
            from pychromecast import dial
            from pychromecast.models import CastInfo, HostServiceInfo

            status = dial.get_device_info(address, timeout=self.discovery_timeout or 5)
            if status is None or status.uuid is None:
                return None
            return CastInfo(
                services={HostServiceInfo(address, 8009)},
                uuid=status.uuid,
                model_name=status.model_name,
                friendly_name=status.friendly_name,
                host=address,
                port=8009,
                cast_type=status.cast_type,
                manufacturer=status.manufacturer,
            )
        except Exception:
            logger.warning("Cast manual probe failed for %s", address, exc_info=True)
            return None

    def _device_from_info(
        self, uuid_str: str, cast_info: Any, cast: Any | None = None
    ) -> RendererDevice:
        def info_attr(name: str) -> Any | None:
            return getattr(cast_info, name, None) if cast_info is not None else None

        cast_type = info_attr("cast_type") or getattr(cast, "cast_type", None)
        return RendererDevice(
            renderer_id=make_renderer_id(self.kind, uuid_str),
            kind=self.kind,
            native_id=uuid_str,
            udn=make_renderer_id(self.kind, uuid_str),
            name=info_attr("friendly_name") or getattr(cast, "name", None) or "Cast Renderer",
            ip=info_attr("host") or (self._cast_ip(cast) if cast is not None else None),
            manufacturer=info_attr("manufacturer"),
            model_name=info_attr("model_name") or getattr(cast, "model_name", None),
            cast_type=cast_type,
            discovered_by="server",
            capabilities=RendererCapabilities(
                can_mute=True,
                supports_events=True,
                supported_mime_types={"audio/flac", "audio/mpeg", "audio/mp4", "audio/wav", "audio/ogg"},
            ),
            is_group=(cast_type == "group"),
        )

    async def _get_ready_cast(self, renderer_id: str) -> Any:
        _, uuid = split_renderer_id(renderer_id)
        cast = self.casts.get(uuid)
        if not cast:
            await self.discover(refresh=True)
            cast = self.casts.get(uuid)
        if not cast:
            # Device known but client creation still pending (or was deferred
            # before the loop existed): create it now, off the event loop.
            cast_info = None
            browser = self.browser
            if browser is not None:
                for info_uuid, info in dict(getattr(browser, "devices", None) or {}).items():
                    if str(info_uuid) == uuid:
                        cast_info = info
                        break
            if cast_info is not None:
                await self._connect_cast_client(uuid, cast_info)
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
    def _stream_url(track: dict[str, Any], context: PlaybackContext) -> str:
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
        return f"{context.base_url}/api/stream/{track['id']}?token={token}"

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
