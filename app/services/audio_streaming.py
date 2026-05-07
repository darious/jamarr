from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

import asyncpg

from app.audio_normalization import (
    TARGET_LOUDNESS_LUFS,
    album_sequence_track_ids,
    calculate_album_gain_db,
    calculate_track_gain_db,
    env_flag_enabled,
    is_album_sequence_item,
)
from app.auth_tokens import create_stream_token
from app.services.renderer.token_policy import stream_token_ttl_seconds


@dataclass(frozen=True)
class StreamUrl:
    url: str
    claims: dict[str, Any]
    mime_type: str | None


def raw_normalization_claims() -> dict[str, Any]:
    return {
        "loudness_normalized": False,
        "loudness_gain_mode": "raw",
        "loudness_gain_db": None,
        "loudness_target_lufs": TARGET_LOUDNESS_LUFS,
    }


async def build_stream_url(
    db: asyncpg.Connection,
    *,
    track_id: int,
    base_url: str = "",
    user_id: int | None = None,
    duration_seconds: float | None = None,
    renderer_kind: str | None = None,
    queue: list[dict[str, Any]] | None = None,
    queue_index: int | None = None,
    client_id: str | None = None,
) -> StreamUrl:
    if duration_seconds is None:
        duration_seconds = await db.fetchval(
            "SELECT duration_seconds FROM track WHERE id = $1",
            track_id,
        )
    ttl_seconds = stream_token_ttl_seconds(renderer_kind, duration_seconds)
    expires_delta = timedelta(seconds=ttl_seconds) if ttl_seconds is not None else None
    claims = await stream_normalization_claims(
        db,
        track_id,
        queue=queue,
        queue_index=queue_index,
        client_id=client_id,
    )
    token = create_stream_token(
        track_id=track_id,
        user_id=user_id,
        expires_delta=expires_delta,
        stream_claims=claims,
    )
    return StreamUrl(
        url=f"{base_url}/api/stream/{track_id}?token={token}",
        claims=claims,
        mime_type=stream_mime_type(claims),
    )


async def stream_normalization_claims(
    db: asyncpg.Connection,
    track_id: int,
    *,
    queue: list[dict[str, Any]] | None = None,
    queue_index: int | None = None,
    client_id: str | None = None,
) -> dict[str, Any]:
    if not env_flag_enabled("JAMARR_LOUDNESS_NORMALIZATION", True):
        return raw_normalization_claims()

    row = await db.fetchrow(
        """
        SELECT loudness_lufs, true_peak_db, replaygain_album_gain_db
        FROM track_audio_analysis
        WHERE track_id = $1 AND status = 'complete'
        """,
        track_id,
    )
    if not row or row["loudness_lufs"] is None:
        return raw_normalization_claims()

    gain_mode = "track"
    gain_db = calculate_track_gain_db(
        float(row["loudness_lufs"]),
        float(row["true_peak_db"]) if row["true_peak_db"] is not None else None,
    )

    if queue is None or queue_index is None:
        queue, queue_index = await queue_context_for_track(db, track_id, client_id)

    if (
        queue
        and queue_index is not None
        and row["replaygain_album_gain_db"] is not None
        and is_album_sequence_item(queue, queue_index)
    ):
        album_true_peak_db = await album_sequence_true_peak_db(
            db,
            album_sequence_track_ids(queue, queue_index),
        )
        gain_mode = "album"
        gain_db = calculate_album_gain_db(
            float(row["replaygain_album_gain_db"]),
            album_true_peak_db,
        )

    return {
        "loudness_normalized": True,
        "loudness_gain_mode": gain_mode,
        "loudness_gain_db": round(gain_db, 6),
        "loudness_target_lufs": TARGET_LOUDNESS_LUFS,
    }


def stream_mime_type(claims: dict[str, Any]) -> str | None:
    if claims.get("loudness_normalized") and claims.get("loudness_gain_db") is not None:
        return "audio/flac"
    return None


async def album_sequence_true_peak_db(
    db: asyncpg.Connection,
    track_ids: list[int],
) -> Optional[float]:
    if not track_ids:
        return None
    return await db.fetchval(
        """
        SELECT MAX(true_peak_db)
        FROM track_audio_analysis
        WHERE track_id = ANY($1::bigint[])
            AND status = 'complete'
            AND true_peak_db IS NOT NULL
        """,
        track_ids,
    )


async def queue_context_for_track(
    db: asyncpg.Connection,
    track_id: int,
    client_id: str | None,
) -> tuple[list[dict[str, Any]], Optional[int]]:
    if not client_id:
        return [], None
    state_row = await db.fetchrow(
        """
        SELECT rs.queue, rs.current_index
        FROM client_session cs
        JOIN renderer_state rs ON rs.renderer_udn = cs.active_renderer_udn
        WHERE cs.client_id = $1
        """,
        client_id,
    )
    if not state_row:
        return [], None

    queue = state_row["queue"]
    if isinstance(queue, str):
        try:
            queue = json.loads(queue)
        except json.JSONDecodeError:
            return [], None
    if not isinstance(queue, list):
        return [], None

    current_index = state_row["current_index"]
    preferred_indices = []
    if isinstance(current_index, int):
        preferred_indices.extend([current_index, current_index + 1, current_index - 1])
    preferred_indices.extend(range(len(queue)))
    seen = set()
    for index in preferred_indices:
        if index in seen or index < 0 or index >= len(queue):
            continue
        seen.add(index)
        item = queue[index]
        if isinstance(item, dict) and item.get("id") == track_id:
            return queue, index
    return queue, None
