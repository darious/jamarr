from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FakeRendererStatus:
    renderer_id: str
    state: str
    position_seconds: float = 0
    duration_seconds: float | None = None
    volume_percent: int | None = None
    ended: bool = False


@dataclass
class FakeRendererCommand:
    name: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)


class FakeUpnpManager:
    """Small recorder for current UPnP-manager-shaped tests."""

    def __init__(self) -> None:
        self.commands: list[FakeRendererCommand] = []
        self.local_ip = "127.0.0.1"
        self.base_url = "http://127.0.0.1:8111"
        self.renderers: dict[str, dict[str, Any]] = {}
        self.active_renderer: str | None = None
        self.is_scanning_subnet = False
        self.scan_msg = ""
        self.scan_progress = 0
        self.debug_log: list[str] = []

    async def discover(self) -> None:
        self.commands.append(FakeRendererCommand("discover"))

    async def scan_subnet(self) -> None:
        self.commands.append(FakeRendererCommand("scan_subnet"))

    async def get_renderers(self) -> list[dict[str, Any]]:
        self.commands.append(FakeRendererCommand("get_renderers"))
        return list(self.renderers.values())

    async def set_renderer(self, udn: str) -> None:
        self.active_renderer = udn
        self.commands.append(FakeRendererCommand("set_renderer", (udn,)))

    async def play_track(
        self,
        track_id: int,
        track_path: str | None,
        metadata: dict[str, Any],
        username: str | None = None,
    ) -> dict[str, Any]:
        self.commands.append(
            FakeRendererCommand(
                "play_track",
                (track_id, track_path, metadata),
                {"username": username},
            )
        )
        return {"status": "ok"}

    async def pause(self) -> None:
        self.commands.append(FakeRendererCommand("pause"))

    async def resume(self) -> None:
        self.commands.append(FakeRendererCommand("resume"))

    async def seek(self, seconds: float) -> None:
        self.commands.append(FakeRendererCommand("seek", (seconds,)))

    async def set_volume(self, percent: int) -> None:
        self.commands.append(FakeRendererCommand("set_volume", (percent,)))


def status_playing(renderer_id: str, position: float = 0) -> FakeRendererStatus:
    return FakeRendererStatus(renderer_id=renderer_id, state="PLAYING", position_seconds=position)


def status_paused(renderer_id: str, position: float = 0) -> FakeRendererStatus:
    return FakeRendererStatus(renderer_id=renderer_id, state="PAUSED", position_seconds=position)


def status_ended(renderer_id: str) -> FakeRendererStatus:
    return FakeRendererStatus(renderer_id=renderer_id, state="IDLE", ended=True)
