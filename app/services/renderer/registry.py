from __future__ import annotations

from typing import Any

import asyncpg

from app.services.renderer.contracts import (
    RendererBackend,
    RendererDevice,
    is_local_renderer,
    make_renderer_id,
    split_renderer_id,
)
from app.services.renderer.persistence import register_or_update_renderer
from app.services.renderer.upnp_backend import UpnpRendererBackend
try:
    from app.services.renderer.cast_backend import CastRendererBackend
except Exception:
    CastRendererBackend = None


class RendererRegistry:
    def __init__(self) -> None:
        self.backends: dict[str, RendererBackend] = {}

    def register_backend(self, backend: RendererBackend) -> None:
        self.backends[backend.kind] = backend

    async def start_all(self) -> None:
        for backend in self.backends.values():
            await backend.start()

    async def stop_all(self) -> None:
        for backend in self.backends.values():
            await backend.stop()

    def normalize_renderer_id(self, renderer_id: str) -> str:
        if is_local_renderer(renderer_id):
            return renderer_id
        kind, native_id = split_renderer_id(renderer_id)
        return make_renderer_id(kind, native_id)

    def legacy_or_renderer_id_to_state_key(self, renderer_id: str) -> str:
        if is_local_renderer(renderer_id):
            return renderer_id
        kind, native_id = split_renderer_id(renderer_id)
        if kind == "upnp":
            return native_id
        return make_renderer_id(kind, native_id)

    def state_key_to_renderer_id(self, state_key: str) -> str:
        if is_local_renderer(state_key):
            return state_key
        kind, native_id = split_renderer_id(state_key)
        if state_key.startswith(f"{kind}:") and native_id != state_key:
            return state_key
        return make_renderer_id("upnp", state_key)

    def get_backend(self, renderer_id: str) -> RendererBackend:
        if is_local_renderer(renderer_id):
            raise ValueError("Local renderer has no backend")
        kind, _ = split_renderer_id(renderer_id)
        backend = self.backends.get(kind)
        if not backend:
            raise ValueError(f"No renderer backend registered for {kind}")
        return backend

    async def discover_all(self, refresh: bool = False) -> list[RendererDevice]:
        devices: list[RendererDevice] = []
        for backend in self.backends.values():
            devices.extend(await backend.discover(refresh=refresh))
        return devices

    async def list_all(self) -> list[RendererDevice]:
        devices: list[RendererDevice] = []
        for backend in self.backends.values():
            devices.extend(await backend.list_devices())
        return devices

    async def persist_all(self, db: asyncpg.Connection, devices: list[RendererDevice]) -> None:
        for device in devices:
            await register_or_update_renderer(db, device)

    async def set_active(
        self,
        db: asyncpg.Connection,
        client_id: str,
        renderer_id_or_udn: str,
    ) -> tuple[str, str]:
        renderer_id = self.normalize_renderer_id(renderer_id_or_udn)
        state_key = self.legacy_or_renderer_id_to_state_key(renderer_id)
        await db.execute(
            """
            INSERT INTO client_session (
                client_id, active_renderer_udn, active_renderer_id, last_seen_at
            )
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT(client_id) DO UPDATE SET
                active_renderer_udn = excluded.active_renderer_udn,
                active_renderer_id = excluded.active_renderer_id,
                last_seen_at = NOW()
            """,
            client_id,
            state_key,
            renderer_id,
        )
        return renderer_id, state_key

    async def get_active(
        self,
        db: asyncpg.Connection,
        client_id: str,
    ) -> tuple[str, str]:
        row = await db.fetchrow(
            """
            SELECT active_renderer_id, active_renderer_udn
            FROM client_session
            WHERE client_id = $1
            """,
            client_id,
        )
        if row:
            state_key = row["active_renderer_udn"] or row["active_renderer_id"]
            renderer_id = row["active_renderer_id"] or self.state_key_to_renderer_id(state_key)
            return renderer_id, state_key

        state_key = f"local:{client_id}"
        renderer_id = state_key
        await db.execute(
            """
            INSERT INTO client_session (
                client_id, active_renderer_udn, active_renderer_id, last_seen_at
            )
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (client_id) DO NOTHING
            """,
            client_id,
            state_key,
            renderer_id,
        )
        return renderer_id, state_key

    def local_renderer(self, client_id: str) -> dict[str, Any]:
        renderer_id = f"local:{client_id}"
        return {
            "udn": renderer_id,
            "renderer_id": renderer_id,
            "kind": "local",
            "native_id": client_id,
            "name": "This Device (Web Browser)",
            "type": "local",
            "capabilities": {
                "can_play": True,
                "can_pause": True,
                "can_stop": True,
                "can_seek": True,
                "can_set_volume": True,
                "reports_progress": True,
            },
        }


_registry: RendererRegistry | None = None


def get_renderer_registry() -> RendererRegistry:
    global _registry
    if _registry is None:
        _registry = RendererRegistry()
        _registry.register_backend(UpnpRendererBackend())
        if CastRendererBackend is not None:
            _registry.register_backend(CastRendererBackend())
    return _registry
