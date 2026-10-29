from __future__ import annotations

import logging
from typing import Any

from async_upnp_client.exceptions import UpnpError

from app.services.player.globals import note_seek
from app.services.playback_plan import (
    RendererConstraints,
    apply_plan_to_metadata,
    constraints_for_upnp,
)
from app.services.renderer.contracts import (
    PlaybackContext,
    RendererBackend,
    RendererCapabilities,
    RendererDevice,
    RendererLoadError,
    RendererStatus,
    make_renderer_id,
    split_renderer_id,
)
from app.upnp import UPnPManager

logger = logging.getLogger(__name__)


class UpnpRendererBackend(RendererBackend):
    kind = "upnp"

    def __init__(self, manager: UPnPManager | None = None) -> None:
        self.manager = manager or UPnPManager.get_instance()

    async def start(self) -> None:
        self.manager.start_background_scan()

    async def stop(self) -> None:
        await self.manager.stop_background_scan()

    async def discover(self, refresh: bool = False) -> list[RendererDevice]:
        if refresh:
            # refresh=True re-hydrates cached devices, not just new ones.
            await self.manager.discover(refresh=True)
        return await self.list_devices()

    async def add_manual(self, address: str) -> RendererDevice | None:
        """Add by IP or description URL; returns the device actually registered."""
        found = await self.manager.add_device_by_ip(address)
        return self._device_from_renderer(found[0]) if found else None

    async def list_devices(self) -> list[RendererDevice]:
        renderers = await self.manager.get_renderers()  # available ones only
        return [
            self._device_from_renderer(renderer)
            for renderer in renderers
            if (renderer.get("kind") or self.kind) == self.kind
        ]

    async def is_available(self, renderer_id: str) -> bool | None:
        """Tracked availability (SSDP liveness + probes); None if unknown here."""
        checker = getattr(self.manager, "is_available", None)
        if checker is None:
            return None
        _, udn = split_renderer_id(renderer_id)
        return checker(udn)

    def _note_control_failure(self, renderer_id: str, exc: Exception) -> None:
        # ValueError means "not registered", not "device did not answer".
        if isinstance(exc, ValueError):
            return
        hook = getattr(self.manager, "note_control_failure", None)
        if hook is None:
            return
        try:
            hook(split_renderer_id(renderer_id)[1])
        except Exception:
            logger.debug("note_control_failure failed for %s", renderer_id, exc_info=True)

    def output_constraints(self, renderer_id: str) -> RendererConstraints:
        """Constraints from the renderer's advertised sink protocolInfo."""
        _, udn = split_renderer_id(renderer_id)
        renderers = getattr(self.manager, "renderers", None) or {}
        return constraints_for_upnp(renderers.get(udn), udn, renderer_id)

    async def unload_device(self, renderer_id: str) -> None:
        _, udn = split_renderer_id(renderer_id)
        self.manager.renderers.pop(udn, None)
        self.manager.dmr_devices.pop(udn, None)

    async def play_track(
        self,
        renderer_id: str,
        track: dict[str, Any],
        context: PlaybackContext,
    ) -> RendererStatus:
        _, udn = split_renderer_id(renderer_id)
        await self.manager.set_renderer(udn)
        self.manager.base_url = context.base_url
        metadata = dict(track)
        if context.stream_url:
            metadata["stream_url"] = context.stream_url
        if context.stream_mime_type:
            metadata["mime"] = context.stream_mime_type
        apply_plan_to_metadata(metadata, context.playback_plan)
        try:
            await self.manager.play_track(
                int(track["id"]),
                track.get("path"),
                metadata,
                username=context.username,
            )
        except Exception as exc:
            self._note_control_failure(renderer_id, exc)
            if isinstance(exc, (UpnpError, OSError)):
                # SetAVTransportURI / Play refused or unanswered: the same
                # load failure as a Cast LOAD_FAILED, so the orchestrator
                # rolls back is_playing and reports it. ValueError (device not
                # registered) is left alone: stale-renderer healing needs it.
                raise RendererLoadError(
                    renderer_id, "load_failed", str(exc) or type(exc).__name__
                ) from exc
            raise
        return RendererStatus(renderer_id=renderer_id, state="PLAYING")

    async def pause(self, renderer_id: str) -> RendererStatus:
        await self._set_active(renderer_id)
        await self.manager.pause()
        return RendererStatus(renderer_id=renderer_id, state="PAUSED")

    async def resume(self, renderer_id: str) -> RendererStatus:
        await self._set_active(renderer_id)
        await self.manager.resume()
        return RendererStatus(renderer_id=renderer_id, state="PLAYING")

    async def stop_playback(self, renderer_id: str) -> RendererStatus:
        udn = await self._set_active(renderer_id)
        # Without this a renderer resumed from its own remote would roll from
        # the stopped track into whatever was staged after it.
        clear_next = getattr(self.manager, "clear_next_track", None)
        if clear_next is not None:
            await clear_next(udn)
        control = getattr(self.manager, "control", None)
        if control and hasattr(control, "stop"):
            await control.stop()
        else:
            await self.manager.pause()
        await self.release_events(renderer_id)
        return RendererStatus(renderer_id=renderer_id, state="STOPPED")

    async def release_events(self, renderer_id: str) -> None:
        """Drop udn's event subscriptions now (stopped, or switched away from)."""
        release = getattr(self.manager, "release_events", None)
        if release is None:
            return
        try:
            await release(split_renderer_id(renderer_id)[1])
        except Exception:
            logger.debug("Releasing UPnP events failed for %s", renderer_id, exc_info=True)

    async def seek(self, renderer_id: str, seconds: float) -> RendererStatus:
        udn = await self._set_active(renderer_id)
        # Before and after: the monitor must not extrapolate a pre-seek
        # position while the seek is in flight, nor once it landed.
        note_seek(udn)
        try:
            await self.manager.seek(seconds)
        finally:
            note_seek(udn)
        return RendererStatus(renderer_id=renderer_id, state="PLAYING", position_seconds=seconds)

    async def set_volume(self, renderer_id: str, percent: int) -> RendererStatus:
        await self._set_active(renderer_id)
        await self.manager.set_volume(percent)
        return RendererStatus(renderer_id=renderer_id, state="UNKNOWN", volume_percent=percent)

    async def mute(self, renderer_id: str, muted: bool) -> RendererStatus:
        udn = await self._set_active(renderer_id)
        if not self._can_mute(udn):
            raise NotImplementedError("This UPnP renderer has no RenderingControl SetMute")
        await self.manager.set_mute(bool(muted))
        return RendererStatus(renderer_id=renderer_id, state="UNKNOWN", volume_muted=bool(muted))

    def _can_mute(self, udn: str) -> bool:
        check = getattr(self.manager, "can_mute", None)
        if check is None:
            return False
        try:
            return bool(check(udn))
        except Exception:
            logger.debug("can_mute failed for %s", udn, exc_info=True)
            return False

    async def get_status(self, renderer_id: str) -> RendererStatus:
        _, udn = split_renderer_id(renderer_id)
        position, duration = await self.manager.get_position(udn)
        transport = await self.manager.get_transport_info(udn)
        track_uri = getattr(self.manager, "current_track_uri", None)
        return RendererStatus(
            renderer_id=renderer_id,
            state=self.normalize_transport_state(transport),
            position_seconds=float(position or 0),
            duration_seconds=float(duration) if duration is not None else None,
            current_media_url=track_uri(udn) if track_uri else None,
        )

    async def _set_active(self, renderer_id: str) -> str:
        _, udn = split_renderer_id(renderer_id)
        await self.manager.set_renderer(udn)
        return udn

    def _device_from_renderer(self, renderer: dict[str, Any]) -> RendererDevice:
        udn = renderer.get("udn") or renderer.get("native_id")
        supported_mimes = {
            item
            for item in (renderer.get("supported_mime_types") or "").split(",")
            if item
        }
        return RendererDevice(
            renderer_id=make_renderer_id(self.kind, udn),
            kind=self.kind,
            native_id=udn,
            udn=udn,
            available=bool(renderer.get("available", True)),
            name=renderer.get("name")
            or renderer.get("friendly_name")
            or renderer.get("model_name")
            or "UPnP Renderer",
            ip=renderer.get("ip"),
            manufacturer=renderer.get("manufacturer"),
            model_name=renderer.get("model_name"),
            model_number=renderer.get("model_number"),
            device_type=renderer.get("device_type"),
            icon_url=renderer.get("icon_url"),
            icon_mime=renderer.get("icon_mime"),
            icon_width=renderer.get("icon_width"),
            icon_height=renderer.get("icon_height"),
            capabilities=RendererCapabilities(
                supported_mime_types=supported_mimes,
                protocol_info=list(renderer.get("sink_protocol_info") or []),
                # Discovery's supports_events only says the services exist;
                # report events once a subscription has proven them usable.
                supports_events=self._events_healthy(udn, renderer),
                can_stage_next=self._staging_allowed(udn),
                # Only when RenderingControl actually offers SetMute.
                can_mute=self._can_mute(udn),
            ),
        )

    def _events_healthy(self, udn: str, renderer: dict[str, Any]) -> bool:
        """Whether a subscription has proven events usable on this renderer.

        This run's verdict (app/services/upnp/events.py) or, before one, the
        verdict persisted from an earlier run; discovery never claims it.
        """
        events = getattr(self.manager, "events", None)
        try:
            if events is not None and events.supports_events(udn):
                return True
        except Exception:
            logger.debug("supports_events failed for %s", udn, exc_info=True)
        return bool(renderer.get("supports_events", False))

    def _staging_allowed(self, udn: str) -> bool:
        """Config override, runtime faults and the device advert, as the
        monitor applies them (app.services.upnp.staging.staging_allowed)."""
        check = getattr(self.manager, "next_track_staging_allowed", None)
        if check is None:
            return False
        try:
            return bool(check(udn))
        except Exception:
            logger.debug("next_track_staging_allowed failed for %s", udn, exc_info=True)
            return False

    def next_track_staging_allowed(self, renderer_id: str) -> bool:
        return self._staging_allowed(split_renderer_id(renderer_id)[1])

    async def clear_next_track(self, renderer_id: str) -> None:
        clear_next = getattr(self.manager, "clear_next_track", None)
        if clear_next is not None:
            await clear_next(split_renderer_id(renderer_id)[1])

    @staticmethod
    def normalize_transport_state(transport_state: str | None) -> str:
        if transport_state in {"PLAYING", "TRANSITIONING"}:
            return "PLAYING"
        if transport_state in {"PAUSED_PLAYBACK", "PAUSED_RECORDING", "PAUSED"}:
            return "PAUSED"
        if transport_state in {"STOPPED", "NO_MEDIA_PRESENT", "IDLE"}:
            return "IDLE"
        return "UNKNOWN"

