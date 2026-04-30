from __future__ import annotations

import json
from typing import Any

import asyncpg

from app.services.renderer.contracts import RendererDevice


async def register_or_update_renderer(
    db: asyncpg.Connection,
    device: RendererDevice,
) -> None:
    """Persist a normalized renderer device."""
    await db.execute(
        """
        INSERT INTO renderer (
            renderer_id, kind, native_id, udn, friendly_name, ip, manufacturer,
            model_name, cast_type, last_discovered_by, available,
            enabled_by_default, supported_mime_types, last_seen_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW())
        ON CONFLICT (renderer_id) DO UPDATE SET
            kind = EXCLUDED.kind,
            native_id = EXCLUDED.native_id,
            udn = EXCLUDED.udn,
            friendly_name = EXCLUDED.friendly_name,
            ip = EXCLUDED.ip,
            manufacturer = EXCLUDED.manufacturer,
            model_name = EXCLUDED.model_name,
            cast_type = EXCLUDED.cast_type,
            last_discovered_by = EXCLUDED.last_discovered_by,
            available = EXCLUDED.available,
            enabled_by_default = EXCLUDED.enabled_by_default,
            supported_mime_types = EXCLUDED.supported_mime_types,
            last_seen_at = NOW()
        """,
        device.renderer_id,
        device.kind,
        device.native_id,
        device.udn or device.native_id,
        device.name,
        device.ip,
        device.manufacturer,
        device.model_name,
        device.cast_type,
        device.discovered_by,
        device.available,
        device.enabled_by_default,
        ",".join(sorted(device.capabilities.supported_mime_types)),
    )


async def mark_renderer_unavailable(db: asyncpg.Connection, renderer_id: str) -> None:
    await db.execute(
        "UPDATE renderer SET available = FALSE WHERE renderer_id = $1",
        renderer_id,
    )


def _row_get(row: asyncpg.Record | dict[str, Any], key: str, default: Any = None) -> Any:
    try:
        value = row[key]
    except KeyError:
        return default
    return default if value is None else value


def renderer_row_to_api(row: asyncpg.Record | dict[str, Any]) -> dict[str, Any]:
    supported_mime_types = _row_get(row, "supported_mime_types", "")
    capabilities = {
        "can_play": True,
        "can_pause": True,
        "can_stop": True,
        "can_seek": True,
        "can_set_volume": True,
        "can_mute": False,
        "can_next_previous": False,
        "can_enqueue": False,
        "can_group": False,
        "can_power": False,
        "reports_progress": True,
        "supports_events": bool(_row_get(row, "supports_events", False)),
        "requires_flow_mode": False,
        "supported_mime_types": [
            item for item in supported_mime_types.split(",") if item
        ],
    }
    metadata = _row_get(row, "renderer_metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    metadata = metadata or {}
    return {
        "renderer_id": _row_get(row, "renderer_id") or f"upnp:{row['udn']}",
        "kind": _row_get(row, "kind", "upnp"),
        "native_id": _row_get(row, "native_id") or row["udn"],
        "udn": row["udn"],
        "name": _row_get(row, "friendly_name") or _row_get(row, "name") or "Renderer",
        "type": _row_get(row, "kind", "upnp"),
        "ip": _row_get(row, "ip"),
        "manufacturer": _row_get(row, "manufacturer"),
        "model_name": _row_get(row, "model_name"),
        "cast_type": _row_get(row, "cast_type"),
        "discovered_by": _row_get(row, "last_discovered_by", "server"),
        "available": _row_get(row, "available", True),
        "enabled_by_default": _row_get(row, "enabled_by_default", True),
        "is_group": bool(metadata.get("is_group", False)),
        "group_members": metadata.get("group_members", []),
        "capabilities": capabilities,
    }
