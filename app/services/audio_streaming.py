from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

import asyncpg

from app.audio_normalization import (
    TARGET_LOUDNESS_LUFS,
    album_sequence_track_ids,
    calculate_album_gain_db,
    calculate_track_gain_db,
    is_album_sequence_item,
)
from app.auth_tokens import create_stream_token
from app.services.playback_plan import (
    PlaybackPlan,
    RendererConstraints,
    audio_properties_from_track,
    needs_probe,
    plan_playback,
    probe_audio_file,
)
from app.services.renderer.token_policy import stream_token_ttl_seconds


@dataclass(frozen=True)
class StreamUrl:
    url: str
    claims: dict[str, Any]
    mime_type: str | None
    # Set when the URL was planned for a renderer's constraints: what is
    # served, and why. mime_type is then always the plan's output MIME.
    plan: PlaybackPlan | None = None


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
    extra_claims: dict[str, Any] | None = None,
    ttl_seconds: int | None = None,
    constraints: RendererConstraints | None = None,
) -> StreamUrl:
    """Mint a tokenised stream URL.

    With ``constraints`` (renderer playback) the output is planned against
    them and the plan rides in the token, so ``/api/stream`` serves exactly
    the format -- and Content-Type -- that the renderer was told about.
    """
    if duration_seconds is None:
        duration_seconds = await db.fetchval(
            "SELECT duration_seconds FROM track WHERE id = $1",
            track_id,
        )
    if ttl_seconds is None:
        ttl_seconds = stream_token_ttl_seconds(renderer_kind, duration_seconds)
    expires_delta = timedelta(seconds=ttl_seconds) if ttl_seconds is not None else None
    claims = await stream_normalization_claims(
        db,
        track_id,
        queue=queue,
        queue_index=queue_index,
        client_id=client_id,
    )
    # Stream-quality claims ride in the same token: /api/stream resolves both
    # the output format and the gain from the token alone.
    if extra_claims:
        claims = {**claims, **extra_claims}
    plan = None
    if constraints is not None:
        plan = await plan_for_track(db, track_id, claims, constraints)
        if plan is not None:
            claims = {**claims, **plan.output.token_claims()}
    token = create_stream_token(
        track_id=track_id,
        user_id=user_id,
        expires_delta=expires_delta,
        stream_claims=claims,
    )
    return StreamUrl(
        url=f"{base_url}/api/stream/{track_id}?token={token}",
        claims=claims,
        mime_type=plan.mime_type if plan is not None else stream_mime_type(claims),
        plan=plan,
    )


async def plan_for_track(
    db: asyncpg.Connection,
    track_id: int,
    claims: dict[str, Any],
    constraints: RendererConstraints,
) -> PlaybackPlan | None:
    row = await db.fetchrow(
        """
        SELECT id, path, codec, sample_rate_hz, bit_depth, channels
        FROM track WHERE id = $1
        """,
        track_id,
    )
    if not row:
        return None
    track = dict(row)
    probe = None
    if needs_probe(track, constraints):
        from app.config import get_music_path

        path = track["path"] or ""
        if not os.path.isabs(path):
            path = os.path.join(get_music_path(), path)
        if os.path.exists(path):
            probe = await asyncio.to_thread(probe_audio_file, path)
    gain_db = None
    if claims.get("loudness_normalized") and claims.get("loudness_gain_db") is not None:
        gain_db = float(claims["loudness_gain_db"])
    return plan_playback(
        audio_properties_from_track(track, probe),
        constraints,
        gain_db=gain_db,
        gain_mode=claims.get("loudness_gain_mode") if gain_db is not None else None,
        requested_quality=claims.get("stream_quality") if claims.get("stream_quality") != "original" else None,
    )


async def stream_normalization_claims(
    db: asyncpg.Connection,
    track_id: int,
    *,
    queue: list[dict[str, Any]] | None = None,
    queue_index: int | None = None,
    client_id: str | None = None,
) -> dict[str, Any]:
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
