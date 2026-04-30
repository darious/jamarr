from __future__ import annotations

from typing import Any

from app.services.renderer.contracts import (
    PlaybackContext,
    RendererBackend,
    RendererCapabilities,
    RendererDevice,
    RendererStatus,
    make_renderer_id,
    split_renderer_id,
)
from app.upnp import UPnPManager


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
            await self.manager.discover()
        return await self.list_devices()

    async def add_manual(self, address: str) -> RendererDevice | None:
        found = await self.manager.add_device_by_ip(address)
        if not found:
            return None
        for device in await self.list_devices():
            if device.ip == address:
                return device
        return None

    async def list_devices(self) -> list[RendererDevice]:
        renderers = await self.manager.get_renderers()
        return [self._device_from_renderer(renderer) for renderer in renderers]

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
        await self.manager.play_track(
            int(track["id"]),
            track.get("path"),
            track,
            username=context.username,
        )
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
        await self._set_active(renderer_id)
        control = getattr(self.manager, "control", None)
        if control and hasattr(control, "stop"):
            await control.stop()
        else:
            await self.manager.pause()
        return RendererStatus(renderer_id=renderer_id, state="STOPPED")

    async def seek(self, renderer_id: str, seconds: float) -> RendererStatus:
        await self._set_active(renderer_id)
        await self.manager.seek(seconds)
        return RendererStatus(renderer_id=renderer_id, state="PLAYING", position_seconds=seconds)

    async def set_volume(self, renderer_id: str, percent: int) -> RendererStatus:
        await self._set_active(renderer_id)
        await self.manager.set_volume(percent)
        return RendererStatus(renderer_id=renderer_id, state="UNKNOWN", volume_percent=percent)

    async def mute(self, renderer_id: str, muted: bool) -> RendererStatus:
        raise NotImplementedError("UPnP mute is not implemented")

    async def get_status(self, renderer_id: str) -> RendererStatus:
        _, udn = split_renderer_id(renderer_id)
        position, duration = await self.manager.get_position(udn)
        transport = await self.manager.get_transport_info(udn)
        return RendererStatus(
            renderer_id=renderer_id,
            state=self.normalize_transport_state(transport),
            position_seconds=float(position or 0),
            duration_seconds=float(duration) if duration is not None else None,
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
            name=renderer.get("name")
            or renderer.get("friendly_name")
            or renderer.get("model_name")
            or "UPnP Renderer",
            ip=renderer.get("ip"),
            manufacturer=renderer.get("manufacturer"),
            model_name=renderer.get("model_name"),
            capabilities=RendererCapabilities(
                supported_mime_types=supported_mimes,
                supports_events=bool(renderer.get("supports_events", False)),
            ),
        )

    @staticmethod
    def normalize_transport_state(transport_state: str | None) -> str:
        if transport_state in {"PLAYING", "TRANSITIONING"}:
            return "PLAYING"
        if transport_state in {"PAUSED_PLAYBACK", "PAUSED_RECORDING", "PAUSED"}:
            return "PAUSED"
        if transport_state in {"STOPPED", "NO_MEDIA_PRESENT", "IDLE"}:
            return "IDLE"
        return "UNKNOWN"
