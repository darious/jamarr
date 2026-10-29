from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Awaitable, Callable

from app.auth_tokens import create_stream_token
from app.services.playback_plan import (
    CAST_DEFAULT_MIME_TYPES,
    RendererConstraints,
    constraints_for_cast,
)
from app.services.renderer.contracts import (
    PlaybackContext,
    RendererBackend,
    OutputConstraints,
    QueueOwnership,
    RendererCapabilities,
    RendererDevice,
    RendererLoadError,
    RendererStatus,
    make_renderer_id,
    split_renderer_id,
)

logger = logging.getLogger(__name__)

# MediaStatus.idleReason values (Cast media protocol). Only FINISHED means the
# track played to its end; the others are a stop, a replacement or a failure.
IDLE_REASON_FINISHED = "FINISHED"
IDLE_REASON_ERROR = "ERROR"

# MediaInformation.customData keys marking media as Jamarr's. The Android app
# uses the same keys, so either controller can recognise the other's items.
CUSTOM_TRACK_ID = "jamarrTrackId"
CUSTOM_SOURCE = "jamarrSource"
CUSTOM_CONTENT_PATH = "jamarrContentPath"
CUSTOM_SOURCE_SERVER = "server"

# A FINISHED for the current item while a next item is queued on the receiver
# normally turns into that item playing by itself; if it has not after this
# long, the queue advances the per-track way (a fresh LOAD).
STAGED_FINISH_GRACE_S = 5.0


@dataclass
class _CastLoad:
    """A LOAD this backend issued, and what has become of it.

    Statuses are only attributed to Jamarr's playback when they refer to this
    media, so another controller's session (or our own explicit stop) never
    advances the queue or reports a device-side halt.
    """

    url: str
    track_id: int
    confirmed: bool = False
    # Set once the media went idle, so repeated IDLE statuses for the same
    # media (listener + polling, receiver re-broadcasts) act only once.
    idle_reason: str | None = None
    # Re-adopted from the receiver's status (customData) rather than loaded by
    # this process, e.g. after a server restart.
    adopted: bool = False
    # When FINISHED was seen while a queued next item was expected to take
    # over, and whether the fallback end of track has been reported.
    finished_at: float | None = None
    ended_reported: bool = False


@dataclass
class _CastStaged:
    """The next track queued on the receiver (QUEUE_INSERT) behind the load."""

    url: str
    track_id: int
    item_id: int | None = None


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
        self.backend.schedule_finish_recheck(self.renderer_id, self)

    def load_media_failed(self, queue_item_id: int, error_code: int) -> None:
        # The LOAD reply (or the IDLE/ERROR status that follows) carries this.
        logger.debug(
            "Cast load_media_failed renderer=%s item=%s code=%s",
            self.renderer_id,
            queue_item_id,
            error_code,
        )


class _CastReceiverListener:
    """Receiver (platform) status listener.

    Volume and mute set on the device itself, by its remote or by another
    controller, arrive here without any media status, so they reach player
    state without polling.
    """

    def __init__(
        self,
        backend: "CastRendererBackend",
        renderer_id: str,
        callback: Callable[[RendererStatus], Awaitable[None]],
    ) -> None:
        self.backend = backend
        self.renderer_id = renderer_id
        self.callback = callback
        self.last_volume: tuple[int | None, bool | None] | None = None

    def new_cast_status(self, status: Any) -> None:
        renderer_status = self.backend.status_from_receiver_status(self.renderer_id, status)
        if renderer_status is None:
            return
        key = (renderer_status.volume_percent, renderer_status.volume_muted)
        if key == self.last_volume:
            # App launches, idle-screen changes etc. re-send the same volume.
            return
        self.last_volume = key
        self.backend.dispatch_status_callback(self.callback, renderer_status)


class CastRendererBackend(RendererBackend):
    kind = "cast"

    def __init__(
        self,
        known_hosts: list[str] | None = None,
        discovery_timeout: float = 5,
        launch_timeout: float = 10,
        load_timeout: float = 15,
        browser_factory: Callable[["CastRendererBackend"], Any] | None = None,
        cast_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        self.known_hosts = known_hosts if known_hosts is not None else self._known_hosts_from_env()
        self.discovery_timeout = discovery_timeout
        self.launch_timeout = launch_timeout
        self.load_timeout = load_timeout
        self.browser_factory = browser_factory
        self.cast_factory = cast_factory
        self.browser: Any | None = None
        self._zconf: Any | None = None
        self.casts: dict[str, Any] = {}
        self.devices: dict[str, RendererDevice] = {}
        self._listeners: dict[str, list[_CastStatusListener]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._discovery_lock = asyncio.Lock()
        self._loads: dict[str, _CastLoad] = {}
        self._staged: dict[str, _CastStaged] = {}
        self._receiver_listeners: dict[str, list[_CastReceiverListener]] = {}
        # Jamarr mutes Cast by volume (see mute): the level to restore.
        self._levels_before_mute: dict[str, float] = {}
        self._finish_rechecks: dict[str, Any] = {}
        # Statuses arrive on pychromecast's socket thread as well as the loop.
        self._loads_lock = threading.Lock()

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
        self._receiver_listeners.pop(renderer_id, None)
        self._forget_load(renderer_id)
        if cast and hasattr(cast, "disconnect"):
            await asyncio.to_thread(cast.disconnect, 1)

    async def play_track(
        self,
        renderer_id: str,
        track: dict[str, Any],
        context: PlaybackContext,
    ) -> RendererStatus:
        """Load a track and wait for the receiver to accept it.

        The LOAD response, not the request, is what confirms playback: a
        receiver that cannot fetch or decode the media answers LOAD_FAILED.
        Raises RendererLoadError on rejection, transport failure or timeout.
        Statuses that arrive while the LOAD is pending report TRANSITIONING.
        """
        cast = await self._get_ready_cast(renderer_id)
        await asyncio.to_thread(cast.start_app, self._media_receiver_app_id(), True, self.launch_timeout)
        media_url = self._stream_url(track, context)
        mime_type = self._load_mime_type(track, context)
        metadata = self._media_metadata(track, context)
        thumb = self._art_url(track, context)
        logger.info(
            "Cast play requested renderer=%s track_id=%s mime=%s url=%s",
            renderer_id,
            track.get("id"),
            mime_type,
            media_url.split("?", 1)[0],
        )
        track_id = int(track["id"])
        load = _CastLoad(url=media_url, track_id=track_id)
        with self._loads_lock:
            self._loads[renderer_id] = load
            # A LOAD replaces the receiver's whole queue, staged item included.
            self._staged.pop(renderer_id, None)
        response: asyncio.Future[tuple[bool, dict[str, Any] | None]] = (
            asyncio.get_running_loop().create_future()
        )
        try:
            try:
                await asyncio.to_thread(
                    cast.media_controller.play_media,
                    media_url,
                    mime_type,
                    title=track.get("title") or "Unknown Track",
                    thumb=thumb,
                    metadata=metadata,
                    stream_type=self._stream_type(),
                    media_info={"customData": self.media_custom_data(track_id, media_url)},
                    callback_function=self._load_callback(renderer_id, track_id, response),
                )
            except Exception as exc:
                raise RendererLoadError(
                    renderer_id, "load_failed", str(exc) or type(exc).__name__
                ) from exc
            try:
                success, data = await asyncio.wait_for(response, timeout=self.load_timeout)
            except TimeoutError:
                logger.warning(
                    "Cast load timed out renderer=%s track_id=%s after %ss",
                    renderer_id,
                    track_id,
                    self.load_timeout,
                )
                if not self._is_current_load(renderer_id, load):
                    # A newer LOAD replaced this one; stopping now would stop
                    # that media instead.
                    raise RendererLoadError(
                        renderer_id, "superseded", "replaced by a newer load"
                    ) from None
                # The receiver may still start it later; stop it so the device
                # does not play something the player state says has failed.
                await asyncio.to_thread(self._safe_media_stop, cast, renderer_id)
                raise RendererLoadError(
                    renderer_id, "load_timeout", f"no response within {self.load_timeout:g}s"
                ) from None
            accepted, reason, detail, entry = self._classify_load_response(success, data)
            if not accepted and not self._is_current_load(renderer_id, load):
                # Typically LOAD_CANCELLED by our own next LOAD (rapid skips).
                logger.info(
                    "Cast load superseded renderer=%s track_id=%s detail=%s",
                    renderer_id,
                    track_id,
                    detail,
                )
                raise RendererLoadError(renderer_id, "superseded", detail)
            if not accepted:
                logger.warning(
                    "Cast load rejected renderer=%s track_id=%s reason=%s detail=%s",
                    renderer_id,
                    track_id,
                    reason,
                    detail,
                )
                raise RendererLoadError(renderer_id, reason or "load_rejected", detail)
        except BaseException:
            self._forget_load(renderer_id, load)
            raise
        load.confirmed = True
        logger.info("Cast load accepted renderer=%s track_id=%s", renderer_id, track_id)
        state = self.normalize_player_state(entry.get("playerState"))
        if state not in {"PLAYING", "PAUSED"}:
            # Accepted, but the receiver has not reported playback yet; the
            # status listener confirms it.
            state = "TRANSITIONING"
        return RendererStatus(
            renderer_id=renderer_id,
            state=state,
            current_media_url=media_url,
            current_track_id=track_id,
            completion_reported=True,
        )

    async def pause(self, renderer_id: str) -> RendererStatus:
        cast = await self._get_ready_cast(renderer_id)
        await asyncio.to_thread(cast.media_controller.pause)
        return RendererStatus(renderer_id=renderer_id, state="PAUSED")

    async def resume(self, renderer_id: str) -> RendererStatus:
        cast = await self._get_ready_cast(renderer_id)
        await asyncio.to_thread(cast.media_controller.play)
        return RendererStatus(renderer_id=renderer_id, state="PLAYING")

    async def stop_playback(self, renderer_id: str) -> RendererStatus:
        # An explicit stop ends our load: the CANCELLED status it produces is
        # not a device-side halt and must not be reported as one.
        self._forget_load(renderer_id)
        with self._loads_lock:
            self._staged.pop(renderer_id, None)
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
        """Mute as volume, not the receiver's mute flag.

        A Sony TV unmuted through the flag comes back at its own pre-mute
        level (0 -> 10 at a Jamarr volume of 0) and overrides any volume sent
        while it settles. So mute remembers the level and sets 0, and unmute
        puts that level back. Only a mute made on the device itself (the flag)
        is cleared with the flag.
        """
        cast = await self._get_ready_cast(renderer_id)
        status = getattr(cast, "status", None)
        level = getattr(status, "volume_level", None)
        if muted:
            if level:
                self._levels_before_mute[renderer_id] = float(level)
            await asyncio.to_thread(cast.set_volume, 0.0)
        else:
            if getattr(status, "volume_muted", False):
                await asyncio.to_thread(cast.set_volume_muted, False)
            restore = self._levels_before_mute.pop(renderer_id, None)
            if restore is not None:
                await asyncio.to_thread(cast.set_volume, restore)
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
        receiver_listener = self._register_receiver_listener(cast, renderer_id, callback)

        def unsubscribe() -> None:
            try:
                cast.media_controller._status_listeners.remove(listener)
            except (ValueError, AttributeError):
                pass
            try:
                self._listeners.get(renderer_id, []).remove(listener)
            except ValueError:
                pass
            if receiver_listener is not None:
                # pychromecast has no unregister call for receiver listeners.
                receiver = getattr(getattr(cast, "socket_client", None), "receiver_controller", None)
                try:
                    receiver._status_listeners.remove(receiver_listener)
                except (ValueError, AttributeError):
                    pass
                try:
                    self._receiver_listeners.get(renderer_id, []).remove(receiver_listener)
                except ValueError:
                    pass

        return unsubscribe

    def _register_receiver_listener(
        self,
        cast: Any,
        renderer_id: str,
        callback: Callable[[RendererStatus], Awaitable[None]],
    ) -> _CastReceiverListener | None:
        """Subscribe to receiver status (volume/mute) where the client offers it."""
        if not hasattr(cast, "register_status_listener"):
            return None
        listener = _CastReceiverListener(self, renderer_id, callback)
        # Seed with the current values, so only an actual change is reported.
        current = self.status_from_receiver_status(renderer_id, getattr(cast, "status", None))
        if current is not None:
            listener.last_volume = (current.volume_percent, current.volume_muted)
        try:
            cast.register_status_listener(listener)
        except Exception:
            logger.debug("Cast receiver listener failed for %s", renderer_id, exc_info=True)
            return None
        self._receiver_listeners.setdefault(renderer_id, []).append(listener)
        return listener

    def _muted_by_volume(self, renderer_id: str, volume: Any, muted: Any) -> tuple[Any, Any]:
        """Report a Jamarr mute (volume 0) as muted at the remembered level.

        A level raised on the device itself ends that mute.
        """
        level = self._levels_before_mute.get(renderer_id)
        if level is None:
            return volume, muted
        if volume is not None and float(volume) > 0.005:
            self._levels_before_mute.pop(renderer_id, None)
            return volume, muted
        return level, True

    def status_from_receiver_status(self, renderer_id: str, status: Any) -> RendererStatus | None:
        """A volume-only RendererStatus from a receiver CastStatus, or None.

        ``position_seconds`` is None so progress is left alone, and
        ``completion_reported`` keeps the position end-of-track heuristic out.
        """
        volume = self._status_attr(status, "volume_level")
        muted = self._status_attr(status, "volume_muted")
        if volume is None and muted is None:
            return None
        volume, muted = self._muted_by_volume(renderer_id, volume, muted)
        return RendererStatus(
            renderer_id=renderer_id,
            state="UNKNOWN",
            position_seconds=None,  # type: ignore[arg-type]
            volume_percent=round(float(volume) * 100) if volume is not None else None,
            volume_muted=bool(muted) if muted is not None else None,
            completion_reported=True,
        )

    # --- Receiver queue (next-item preload) ---------------------------------

    def queue_mode_enabled(self, renderer_id: str) -> bool:
        """Whether the next track is staged in the receiver's queue."""
        _, uuid = split_renderer_id(renderer_id)
        try:
            from app.config import cast_queue_enabled

            return cast_queue_enabled(uuid)
        except Exception:
            logger.debug("Could not read cast_queue config", exc_info=True)
            return False

    @staticmethod
    def queue_preload_seconds() -> float:
        try:
            from app.config import get_cast_queue_config

            return float(get_cast_queue_config()["preload_seconds"])
        except Exception:
            return 20.0

    def staged_track_id(self, renderer_id: str) -> int | None:
        with self._loads_lock:
            staged = self._staged.get(renderer_id)
            return staged.track_id if staged is not None else None

    def current_load_track_id(self, renderer_id: str) -> int | None:
        """The track of the confirmed media this backend is following."""
        with self._loads_lock:
            load = self._loads.get(renderer_id)
            return load.track_id if load is not None and load.confirmed else None

    async def stage_next(
        self,
        renderer_id: str,
        track: dict[str, Any],
        context: PlaybackContext,
    ) -> bool:
        """Queue ``track`` on the receiver behind the current item.

        QUEUE_INSERT with a ``preloadTime`` lets the receiver fetch and buffer
        it before the current item ends, then move on without a new LOAD. A
        previously staged item is removed first. True once the receiver
        accepted it.
        """
        cast = await self._get_ready_cast(renderer_id)
        controller = cast.media_controller
        with self._loads_lock:
            load = self._loads.get(renderer_id)
            previous = self._staged.get(renderer_id)
        session_id = getattr(getattr(controller, "status", None), "media_session_id", None)
        if load is None or not load.confirmed or session_id is None:
            return False
        if previous is not None and previous.item_id is not None:
            await self._send_media_request(
                controller,
                renderer_id,
                {"type": "QUEUE_REMOVE", "mediaSessionId": session_id, "itemIds": [previous.item_id]},
            )
        with self._loads_lock:
            if self._staged.get(renderer_id) is previous:
                self._staged.pop(renderer_id, None)
        track_id = int(track["id"])
        media_url = self._stream_url(track, context)
        # The plan's MIME, exactly as a LOAD of this track would send it.
        mime_type = self._load_mime_type(track, context)
        item = {
            "media": {
                "contentId": media_url,
                "streamType": self._stream_type(),
                "contentType": mime_type,
                "metadata": self._media_metadata(track, context),
                "customData": self.media_custom_data(track_id, media_url),
            },
            "autoplay": True,
            "startTime": 0,
            "preloadTime": self.queue_preload_seconds(),
        }
        accepted, data = await self._send_media_request(
            controller,
            renderer_id,
            {"type": "QUEUE_INSERT", "mediaSessionId": session_id, "items": [item]},
        )
        if not accepted:
            logger.warning(
                "Cast queue insert refused renderer=%s track_id=%s: %s",
                renderer_id,
                track_id,
                (data or {}).get("type") or "no reply",
            )
            return False
        staged = _CastStaged(
            url=media_url, track_id=track_id, item_id=self._inserted_item_id(data, media_url)
        )
        with self._loads_lock:
            if self._loads.get(renderer_id) is not load:
                # A new LOAD replaced the receiver's queue meanwhile.
                return False
            self._staged[renderer_id] = staged
        logger.info(
            "Cast queued next renderer=%s track_id=%s item_id=%s",
            renderer_id,
            track_id,
            staged.item_id,
        )
        return True

    async def unstage_next(self, renderer_id: str) -> bool:
        """Remove the item queued on the receiver (QUEUE_REMOVE) and forget it.

        For a queue edit that leaves no next track: without this the receiver
        would roll into the dropped track by itself. True once nothing is
        staged any more. If the receiver can't be told (no item id, no media
        session, refused), the record stays, so the item is still recognised
        as stale should the receiver start it.
        """
        with self._loads_lock:
            staged = self._staged.get(renderer_id)
        if staged is None:
            return True
        if staged.item_id is None:
            return False
        cast = await self._get_ready_cast(renderer_id)
        controller = cast.media_controller
        session_id = getattr(getattr(controller, "status", None), "media_session_id", None)
        if session_id is None:
            return False
        removed, data = await self._send_media_request(
            controller,
            renderer_id,
            {"type": "QUEUE_REMOVE", "mediaSessionId": session_id, "itemIds": [staged.item_id]},
        )
        if not removed:
            logger.warning(
                "Cast queue remove refused renderer=%s track_id=%s: %s",
                renderer_id,
                staged.track_id,
                (data or {}).get("type") or "no reply",
            )
            return False
        with self._loads_lock:
            if self._staged.get(renderer_id) is staged:
                self._staged.pop(renderer_id, None)
        logger.info(
            "Cast removed queued track renderer=%s track_id=%s item_id=%s",
            renderer_id,
            staged.track_id,
            staged.item_id,
        )
        return True

    async def _send_media_request(
        self,
        controller: Any,
        renderer_id: str,
        message: dict[str, Any],
    ) -> tuple[bool, dict[str, Any] | None]:
        """Send a raw media-namespace request; (accepted, reply)."""
        response: asyncio.Future[tuple[bool, dict[str, Any] | None]] = (
            asyncio.get_running_loop().create_future()
        )
        loop = response.get_loop()

        def resolve(success: bool, data: dict[str, Any] | None) -> None:
            if not response.done():
                response.set_result((success, data))

        def callback(success: bool, data: dict[str, Any] | None) -> None:
            try:
                loop.call_soon_threadsafe(resolve, success, data)
            except RuntimeError:
                pass

        try:
            await asyncio.to_thread(
                controller.send_message, message, inc_session_id=True, callback_function=callback
            )
            success, data = await asyncio.wait_for(response, timeout=self.load_timeout)
        except Exception as exc:
            logger.debug("Cast %s failed renderer=%s: %s", message.get("type"), renderer_id, exc)
            return False, None
        return bool(success) and (data or {}).get("type") == "MEDIA_STATUS", data

    @staticmethod
    def _inserted_item_id(data: dict[str, Any] | None, media_url: str) -> int | None:
        for entry in (data or {}).get("status") or []:
            for item in (entry or {}).get("items") or []:
                media = (item or {}).get("media") or {}
                if media.get("contentId") == media_url and item.get("itemId") is not None:
                    return int(item["itemId"])
        return None

    def schedule_finish_recheck(self, renderer_id: str, listener: _CastStatusListener) -> None:
        """Re-evaluate a FINISHED that is waiting for the queued item.

        Statuses only arrive when the receiver sends one; if it never rolls
        into the staged item, nothing else would end the track.
        """
        with self._loads_lock:
            load = self._loads.get(renderer_id)
            waiting = (
                load is not None
                and load.finished_at is not None
                and not load.ended_reported
                and renderer_id in self._staged
            )
        loop = self._loop
        if not waiting or loop is None or not loop.is_running():
            return
        try:
            loop.call_soon_threadsafe(self._arm_finish_recheck, renderer_id, listener)
        except RuntimeError:
            pass

    def _arm_finish_recheck(self, renderer_id: str, listener: _CastStatusListener) -> None:
        if renderer_id in self._finish_rechecks:
            return

        def recheck() -> None:
            self._finish_rechecks.pop(renderer_id, None)
            _, uuid = split_renderer_id(renderer_id)
            cast = self.casts.get(uuid)
            status = getattr(getattr(cast, "media_controller", None), "status", None)
            if status is not None:
                listener.new_media_status(status)

        loop = asyncio.get_running_loop()
        self._finish_rechecks[renderer_id] = loop.call_later(STAGED_FINISH_GRACE_S + 0.1, recheck)

    # --- Media identity ----------------------------------------------------

    @staticmethod
    def media_custom_data(track_id: int, media_url: str) -> dict[str, Any]:
        """customData stamped on every item the server loads or queues."""
        return {
            CUSTOM_TRACK_ID: int(track_id),
            CUSTOM_SOURCE: CUSTOM_SOURCE_SERVER,
            CUSTOM_CONTENT_PATH: media_url.split("?", 1)[0],
        }

    @staticmethod
    def jamarr_track_id(status: Any) -> int | None:
        """The Jamarr track id of the receiver's current media, if the server put it there.

        pychromecast keeps the previous customData when new media arrives
        without any, so the stamped content path must match the media too.
        """
        custom = getattr(status, "media_custom_data", None)
        if not isinstance(custom, dict) or custom.get(CUSTOM_SOURCE) != CUSTOM_SOURCE_SERVER:
            return None
        try:
            track_id = int(custom.get(CUSTOM_TRACK_ID))
        except (TypeError, ValueError):
            return None
        content_id = getattr(status, "content_id", None)
        path = custom.get(CUSTOM_CONTENT_PATH)
        if not content_id or not path or content_id.split("?", 1)[0] != path:
            return None
        return track_id

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
        idle_reason = getattr(status, "idle_reason", None)
        content_id = getattr(status, "content_id", None)
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
        volume, volume_muted = self._muted_by_volume(renderer_id, volume, volume_muted)
        ended = False
        stop_reason = None
        completion_reported = True
        advanced_by_renderer = False
        adopted = False
        current_track_id = None
        custom_track_id = self.jamarr_track_id(status)
        with self._loads_lock:
            load = self._loads.get(renderer_id)
            staged = self._staged.get(renderer_id)
            if (
                load is not None
                and load.confirmed
                and staged is not None
                and content_id
                and self._is_load_media(staged, content_id)
                and not self._is_load_media(load, content_id)
            ):
                # The receiver moved on to the queued item by itself: that is
                # now the media being followed (exactly once: staged is gone).
                load = _CastLoad(url=staged.url, track_id=staged.track_id, confirmed=True)
                self._loads[renderer_id] = load
                del self._staged[renderer_id]
                staged = None
                advanced_by_renderer = True
                logger.info(
                    "Cast receiver advanced to queued track renderer=%s track_id=%s",
                    renderer_id,
                    load.track_id,
                )
            elif (
                load is None
                and custom_track_id is not None
                and state in {"PLAYING", "PAUSED"}
            ):
                # Media the server loaded before a restart: stamped with our
                # customData, so it is ours to follow, not a foreign session.
                load = _CastLoad(
                    url=content_id, track_id=custom_track_id, confirmed=True, adopted=True
                )
                self._loads[renderer_id] = load
                adopted = True
                logger.info(
                    "Cast re-adopted server media renderer=%s track_id=%s",
                    renderer_id,
                    custom_track_id,
                )
            if load is not None and load.confirmed and self._is_load_media(load, content_id):
                current_track_id = load.track_id
            if (
                load is not None
                and load.confirmed
                and load.idle_reason == IDLE_REASON_FINISHED
                and load.finished_at is not None
                and not load.ended_reported
                and state == "IDLE"
                and self._is_load_media(load, content_id)
                and (staged is None or time.time() - load.finished_at >= STAGED_FINISH_GRACE_S)
            ):
                # FINISHED held back for a queued item that never started (or
                # was dropped since): end the track the per-track way.
                load.ended_reported = True
                self._staged.pop(renderer_id, None)
                ended = True
            elif load is not None and not load.confirmed:
                # LOAD still pending: whatever this says is about the previous
                # media (often IDLE/INTERRUPTED as it is replaced) or the new
                # one buffering. Neither may move player state.
                state = "TRANSITIONING"
            elif load is not None and self._is_load_media(load, content_id):
                if state == "IDLE" and idle_reason and load.idle_reason is None:
                    load.idle_reason = idle_reason
                    if idle_reason == IDLE_REASON_FINISHED and staged is not None:
                        # The receiver plays the queued item next by itself;
                        # its media status, not this, moves the queue.
                        load.finished_at = time.time()
                    elif idle_reason == IDLE_REASON_FINISHED:
                        load.ended_reported = True
                        ended = True
                    elif idle_reason == IDLE_REASON_ERROR:
                        stop_reason = "renderer_error"
                    else:
                        # CANCELLED / INTERRUPTED: stopped on the device or
                        # taken over by another controller. Halt, don't advance.
                        stop_reason = "renderer_stopped"
            elif load is None:
                # Media this process did not load (e.g. after a restart): only
                # a FINISHED seen to follow PLAYING counts as completion.
                ended = (
                    state == "IDLE"
                    and idle_reason == IDLE_REASON_FINISHED
                    and previous_state == "PLAYING"
                    and (started_at is None or time.time() - started_at > 3)
                )
                if state == "IDLE" and not ended and (
                    not idle_reason or idle_reason == IDLE_REASON_FINISHED
                ):
                    # No reason, or a FINISHED without the PLAYING before it
                    # (first status seen): not conclusive either way, so the
                    # orchestrator's position-vs-duration check decides.
                    # CANCELLED / INTERRUPTED / ERROR stay non-advancing.
                    completion_reported = False
        if state == "IDLE" and not ended and not stop_reason and not trust_idle:
            state = "UNKNOWN"
        return RendererStatus(
            renderer_id=renderer_id,
            state=state,
            position_seconds=float(current_time or 0),
            duration_seconds=float(duration) if duration is not None else None,
            volume_percent=round(float(volume) * 100) if volume is not None else None,
            volume_muted=volume_muted,
            current_media_url=content_id,
            current_track_id=current_track_id,
            ended=ended,
            completion_reported=completion_reported,
            stop_reason=stop_reason,
            advanced_by_renderer=advanced_by_renderer,
            adopted=adopted,
        )

    def _is_current_load(self, renderer_id: str, load: _CastLoad) -> bool:
        with self._loads_lock:
            return self._loads.get(renderer_id) is load

    def _forget_load(self, renderer_id: str, load: _CastLoad | None = None) -> None:
        """Drop the tracked load (only ``load`` itself, when given)."""
        with self._loads_lock:
            current = self._loads.get(renderer_id)
            if current is not None and (load is None or current is load):
                del self._loads[renderer_id]

    @staticmethod
    def _is_load_media(load: _CastLoad, content_id: str | None) -> bool:
        if not content_id:
            return True
        return content_id == load.url or content_id.split("?", 1)[0] == load.url.split("?", 1)[0]

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
    def _safe_media_stop(cast: Any, renderer_id: str) -> None:
        try:
            cast.media_controller.stop()
        except Exception:
            logger.debug("Cast media stop failed for %s", renderer_id, exc_info=True)

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
                # pychromecast pushes media status over the open socket.
                supports_events=True,
                supported_mime_types=set(CAST_DEFAULT_MIME_TYPES),
                # Server Cast loads one track at a time (no receiver queue yet).
                queue_ownership=QueueOwnership.SERVER,
                # Google's Cast supported-media list; not checked per device.
                output=OutputConstraints(
                    codecs={"aac", "flac", "mp3", "opus", "pcm", "vorbis"},
                    max_sample_rate_hz=96000,
                    max_bit_depth=24,
                    source="documented",
                ),
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

    def output_constraints(self, renderer_id: str) -> RendererConstraints:
        """Default Media Receiver formats plus per-device config overrides.

        Receiver quirks (FLAC block size, sample-rate ceilings) are opt-in via
        ``renderer.audio_constraints``: they differ between Cast generations.
        """
        _, uuid = split_renderer_id(renderer_id)
        return constraints_for_cast(renderer_id, uuid)

    @classmethod
    def _load_mime_type(cls, track: dict[str, Any], context: PlaybackContext) -> str:
        """contentType for the LOAD: the plan's output MIME when there is one.

        It must match the Content-Type /api/stream serves for that URL; the
        plan is what decided the bytes.
        """
        plan = context.playback_plan
        if plan is not None and getattr(plan, "mime_type", None):
            return plan.mime_type
        return context.stream_mime_type or cls._mime_type(track)

    @staticmethod
    def _mime_type(track: dict[str, Any]) -> str:
        mime_type = track.get("mime")
        if mime_type:
            return mime_type
        guessed, _ = mimetypes.guess_type(track.get("path") or "")
        return guessed or "audio/flac"

    @staticmethod
    def _stream_url(track: dict[str, Any], context: PlaybackContext) -> str:
        if context.stream_url:
            return context.stream_url
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
    def _load_callback(
        renderer_id: str,
        track_id: int,
        response: asyncio.Future[tuple[bool, dict[str, Any] | None]],
    ) -> Callable[[bool, dict[str, Any] | None], None]:
        """Hand the LOAD response (from pychromecast's socket thread) to play_track."""
        loop = response.get_loop()

        def resolve(success: bool, data: dict[str, Any] | None) -> None:
            if not response.done():
                response.set_result((success, data))

        def callback(success: bool, data: dict[str, Any] | None) -> None:
            logger.debug(
                "Cast load response renderer=%s track_id=%s success=%s type=%s",
                renderer_id,
                track_id,
                success,
                (data or {}).get("type"),
            )
            try:
                loop.call_soon_threadsafe(resolve, success, data)
            except RuntimeError:
                # Loop closed: nobody is waiting any more.
                pass

        return callback

    @staticmethod
    def _classify_load_response(
        success: bool,
        data: dict[str, Any] | None,
    ) -> tuple[bool, str | None, str | None, dict[str, Any]]:
        """(accepted, reason, detail, media status entry) for a LOAD response.

        pychromecast calls back with success=True for *any* reply carrying the
        request id, so the reply type decides: MEDIA_STATUS is acceptance,
        LOAD_FAILED / LOAD_CANCELLED / INVALID_REQUEST etc. are rejections.
        success=False means the request never got an answer (socket error,
        disconnect).
        """
        if not success:
            return False, "load_failed", "receiver connection failed", {}
        if not data:
            return True, None, None, {}
        msg_type = data.get("type")
        if msg_type == "MEDIA_STATUS":
            entries = data.get("status") or []
            entry = entries[0] if entries and isinstance(entries[0], dict) else {}
            if entry.get("playerState") == "IDLE" and entry.get("idleReason") == IDLE_REASON_ERROR:
                return False, "load_rejected", "receiver reported a media error", entry
            return True, None, None, entry
        details = [str(msg_type or "unknown response")]
        if data.get("reason"):
            details.append(str(data["reason"]))
        error_code = data.get("detailedErrorCode")
        if error_code is not None:
            name = CastRendererBackend._media_error_name(error_code)
            details.append(f"{error_code} {name}".strip())
        return False, "load_rejected", ": ".join(details), {}

    @staticmethod
    def _media_error_name(error_code: Any) -> str:
        try:
            from pychromecast.controllers.media import MEDIA_PLAYER_ERROR_CODES

            return MEDIA_PLAYER_ERROR_CODES.get(error_code, "")
        except Exception:
            return ""
