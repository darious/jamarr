from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol


KNOWN_RENDERER_KINDS = {
    "upnp",
    "cast",
    "chromecast",
    "airplay",
    "local",
    "local_audio",
    "universal",
    "sync_group",
}


@dataclass
class RendererCapabilities:
    can_play: bool = True
    can_pause: bool = True
    can_stop: bool = True
    can_seek: bool = True
    can_set_volume: bool = True
    can_mute: bool = False
    can_next_previous: bool = False
    can_enqueue: bool = False
    can_group: bool = False
    can_power: bool = False
    reports_progress: bool = True
    supports_events: bool = False
    requires_flow_mode: bool = False
    supported_mime_types: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        data["supported_mime_types"] = sorted(self.supported_mime_types)
        return data


@dataclass
class RendererDevice:
    renderer_id: str
    kind: str
    native_id: str
    name: str
    udn: str | None = None
    ip: str | None = None
    manufacturer: str | None = None
    model_name: str | None = None
    model_number: str | None = None
    device_type: str | None = None
    cast_type: str | None = None
    icon_url: str | None = None
    icon_mime: str | None = None
    icon_width: int | None = None
    icon_height: int | None = None
    discovered_by: str = "server"
    capabilities: RendererCapabilities = field(default_factory=RendererCapabilities)
    available: bool = True
    enabled_by_default: bool = True
    is_group: bool = False
    group_members: list[str] = field(default_factory=list)

    def as_api_dict(self) -> dict[str, Any]:
        return {
            "renderer_id": self.renderer_id,
            "kind": self.kind,
            "native_id": self.native_id,
            "udn": self.udn or self.native_id,
            "name": self.name,
            "type": self.kind,
            "ip": self.ip,
            "manufacturer": self.manufacturer,
            "model_name": self.model_name,
            "model_number": self.model_number,
            "device_type": self.device_type,
            "cast_type": self.cast_type,
            "icon_url": self.icon_url,
            "icon_mime": self.icon_mime,
            "icon_width": self.icon_width,
            "icon_height": self.icon_height,
            "discovered_by": self.discovered_by,
            "capabilities": self.capabilities.as_dict(),
            "available": self.available,
            "enabled_by_default": self.enabled_by_default,
            "is_group": self.is_group,
            "group_members": self.group_members,
        }


@dataclass
class RendererStatus:
    renderer_id: str
    state: str
    position_seconds: float = 0
    duration_seconds: float | None = None
    volume_percent: int | None = None
    volume_muted: bool | None = None
    current_track_id: int | None = None
    current_media_url: str | None = None
    active_source: str | None = None
    available: bool = True
    ended: bool = False


@dataclass
class PlaybackContext:
    base_url: str
    user_id: int | None
    username: str | None = None
    token_ttl_seconds: int | None = None
    stream_url: str | None = None
    stream_mime_type: str | None = None
    stream_claims: dict[str, Any] = field(default_factory=dict)


class RendererBackend(Protocol):
    kind: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def discover(self, refresh: bool = False) -> list[RendererDevice]: ...
    async def add_manual(self, address: str) -> RendererDevice | None: ...
    async def list_devices(self) -> list[RendererDevice]: ...
    async def unload_device(self, renderer_id: str) -> None: ...
    async def play_track(
        self,
        renderer_id: str,
        track: dict[str, Any],
        context: PlaybackContext,
    ) -> RendererStatus: ...
    async def pause(self, renderer_id: str) -> RendererStatus: ...
    async def resume(self, renderer_id: str) -> RendererStatus: ...
    async def stop_playback(self, renderer_id: str) -> RendererStatus: ...
    async def seek(self, renderer_id: str, seconds: float) -> RendererStatus: ...
    async def set_volume(self, renderer_id: str, percent: int) -> RendererStatus: ...
    async def mute(self, renderer_id: str, muted: bool) -> RendererStatus: ...
    async def get_status(self, renderer_id: str) -> RendererStatus: ...


class SupportsStatusEvents(Protocol):
    def register_status_listener(
        self,
        renderer_id: str,
        callback: Callable[[RendererStatus], Awaitable[None]],
    ) -> Callable[[], None]: ...


def make_renderer_id(kind: str, native_id: str) -> str:
    if native_id.startswith(f"{kind}:"):
        return native_id
    return f"{kind}:{native_id}"


def split_renderer_id(renderer_id: str) -> tuple[str, str]:
    if ":" not in renderer_id:
        return "upnp", renderer_id
    kind, native_id = renderer_id.split(":", 1)
    if not kind or not native_id:
        raise ValueError(f"Invalid renderer_id: {renderer_id}")
    if kind not in KNOWN_RENDERER_KINDS:
        return "upnp", renderer_id
    return kind, native_id


def is_local_renderer(renderer_id: str) -> bool:
    return renderer_id.startswith("local:")
