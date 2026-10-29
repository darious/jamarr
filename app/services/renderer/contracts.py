from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable


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


class QueueOwnership(StrEnum):
    """Who decides what plays next on a renderer.

    ``SERVER``: Jamarr holds the queue and loads each track (UPnP AVTransport,
    server Cast). ``RENDERER``: the device holds the playlist and Jamarr edits
    it (no backend does this yet; see ADR-0011). ``CONTINUOUS_STREAM``:
    one long-lived stream carries many tracks, so track changes happen inside
    Jamarr's encoder rather than on the device.
    """

    SERVER = "server"
    RENDERER = "renderer"
    CONTINUOUS_STREAM = "continuous_stream"


class QueueOperation(StrEnum):
    """Edits a renderer-owned queue accepts (meaningless for SERVER queues)."""

    READ = "read"
    INSERT = "insert"
    DELETE = "delete"
    MOVE = "move"
    CLEAR = "clear"
    PLAY_ITEM = "play_item"
    SHUFFLE = "shuffle"
    REPEAT = "repeat"


class PairingRequirement(StrEnum):
    """Whether the device needs credentials before Jamarr may control it."""

    NONE = "none"
    OPTIONAL = "optional"
    REQUIRED = "required"


@dataclass
class OutputConstraints:
    """What audio the device accepts. Empty / ``None`` means *unknown*, not
    *unlimited*: callers must not infer support from a missing value.

    ``source`` says how the values are known: ``"advertised"`` (the device
    told us, e.g. GetProtocolInfo), ``"protocol"`` (fixed by the wire
    protocol), ``"documented"`` (vendor docs, not checked per device) or ``"measured"`` (tested on hardware).
    """

    codecs: set[str] = field(default_factory=set)
    max_sample_rate_hz: int | None = None
    max_bit_depth: int | None = None
    max_channels: int | None = None
    source: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "codecs": sorted(self.codecs),
            "max_sample_rate_hz": self.max_sample_rate_hz,
            "max_bit_depth": self.max_bit_depth,
            "max_channels": self.max_channels,
            "source": self.source,
        }


@dataclass
class RendererCapabilities:
    """What a renderer can do *now*. A flag is only true when the operation
    works through Jamarr, not merely when the device advertises it."""

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
    # UPnP: the complete GetProtocolInfo Sink entries, verbatim (four fields,
    # MIME parameters, DLNA.ORG_* info). Empty for protocols without them.
    protocol_info: list[str] = field(default_factory=list)
    # Who owns the queue, and which edits a renderer-owned queue accepts.
    queue_ownership: QueueOwnership = QueueOwnership.SERVER
    queue_operations: set[QueueOperation] = field(default_factory=set)
    # The next track can be handed to the device ahead of time (UPnP
    # SetNextAVTransportURI) and the backend implements SupportsNextTrackStaging.
    can_stage_next: bool = False
    # Credentials the device demands; ``has_credentials`` is None when the
    # device needs none, else whether Jamarr holds them.
    pairing: PairingRequirement = PairingRequirement.NONE
    has_credentials: bool | None = None
    # How a pairing-capable device takes its credentials: True when it wants a
    # password, False when it pairs by PIN instead,
    # None when unknown or not applicable (``pairing == NONE``).
    requires_password: bool | None = None
    output: OutputConstraints = field(default_factory=OutputConstraints)

    def as_dict(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        data["supported_mime_types"] = sorted(self.supported_mime_types)
        data["protocol_info"] = list(self.protocol_info)
        data["queue_ownership"] = str(self.queue_ownership)
        data["queue_operations"] = sorted(str(op) for op in self.queue_operations)
        data["pairing"] = str(self.pairing)
        data["output"] = self.output.as_dict()
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
    # The backend reports completion itself (``ended``), so position-based
    # end-of-track heuristics must not second-guess it: a renderer that went
    # idle because it was cancelled near the end has not finished the track.
    completion_reported: bool = False
    # Why playback halted without the listener asking (``last_stop_reason``),
    # e.g. "renderer_error" or "renderer_stopped".
    stop_reason: str | None = None
    # The renderer moved on to an item queued on it (receiver queue / staged
    # next) by itself; ``current_track_id`` names it. The queue advances
    # without a reload, or reloads the real next track if that item is stale.
    advanced_by_renderer: bool = False
    # The backend just re-adopted its own media after a server restart
    # (Cast customData). The renderer may have moved on by itself while the
    # server was down, so a report one queue item further on is followed.
    adopted: bool = False


class RendererLoadError(RuntimeError):
    """The renderer rejected, or never confirmed, loading a track."""

    def __init__(self, renderer_id: str, reason: str, detail: str | None = None) -> None:
        self.renderer_id = renderer_id
        self.reason = reason
        self.detail = detail
        message = f"Renderer {renderer_id} did not load the track: {reason}"
        super().__init__(f"{message} ({detail})" if detail else message)


@dataclass
class PlaybackContext:
    base_url: str
    user_id: int | None
    username: str | None = None
    token_ttl_seconds: int | None = None
    stream_url: str | None = None
    stream_mime_type: str | None = None
    stream_claims: dict[str, Any] = field(default_factory=dict)
    # app.services.playback_plan.PlaybackPlan the stream URL was minted for;
    # its MIME is what the renderer must be told (DIDL / Cast LOAD).
    playback_plan: Any = None


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


@runtime_checkable
class SupportsStatusEvents(Protocol):
    def register_status_listener(
        self,
        renderer_id: str,
        callback: Callable[[RendererStatus], Awaitable[None]],
    ) -> Callable[[], None]: ...


class SupportsOutputConstraints(Protocol):
    """Optional: what audio a renderer accepts, for output planning.

    Returns an ``app.services.playback_plan.RendererConstraints``. Backends
    without it get ``constraints_for_device`` from their device record.
    """

    def output_constraints(self, renderer_id: str) -> Any: ...


@runtime_checkable
class SupportsNextTrackStaging(Protocol):
    """Next-track handover to the device (gapless where the device honours it)."""

    def next_track_staging_allowed(self, renderer_id: str) -> bool: ...
    async def clear_next_track(self, renderer_id: str) -> None: ...


@dataclass
class PairingStart:
    """Result of starting a pairing: whether the user must read a PIN off the
    device (``device_provides_pin``) or invent one and type it on the device."""

    renderer_id: str
    protocol: str
    device_provides_pin: bool


@runtime_checkable
class SupportsPairing(Protocol):
    """Devices that need pairing/passwords; credentials persist across restarts."""

    async def begin_pairing(self, renderer_id: str) -> PairingStart: ...
    async def finish_pairing(self, renderer_id: str, pin: str | None) -> bool: ...
    async def set_password(self, renderer_id: str, password: str | None) -> None: ...
    async def forget_credentials(self, renderer_id: str) -> None: ...


def backend_supports(backend: Any) -> list[str]:
    """Names of the optional contracts a backend implements (diagnostics)."""
    optional = {
        "status_events": SupportsStatusEvents,
        "next_track_staging": SupportsNextTrackStaging,
        "pairing": SupportsPairing,
    }
    return sorted(name for name, proto in optional.items() if isinstance(backend, proto))


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
