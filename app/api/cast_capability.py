"""HTTP surface for Cast playback capability learning.

Exposed to the native Android Cast client (and any other Cast-capable
client). The client pulls a profile-specific stream URL via
``GET /api/cast/playback/url`` and reports the outcome of each Cast load
back through ``POST /api/cast/playback/feedback``. This keeps the
capability cache backend-owned: the same logic services the Python Cast
backend internally and the Android app over HTTP.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user_jwt
from app.auth_tokens import create_stream_token
from app.db import get_db
from app.services.renderer.cast_capability import (
    PROFILE_MIME,
    CapabilityRecord,
    CastProfile,
    TrackQuality,
    apply_failure,
    apply_success,
    get_capability,
    plan_attempts,
    save_capability,
    track_quality_from_track,
)
from app.services.renderer.token_policy import stream_token_ttl_seconds


router = APIRouter()


def _capability_to_dict(cap: CapabilityRecord) -> dict[str, Any]:
    return {
        "renderer_id": cap.renderer_id,
        "best_working_profile": cap.best_working_profile.value
        if cap.best_working_profile
        else None,
        "is_lossless": cap.is_lossless,
        "highest_successful_original_sample_rate_hz": cap.highest_successful_original_sample_rate_hz,
        "highest_successful_original_bit_depth": cap.highest_successful_original_bit_depth,
        "highest_successful_original_channels": cap.highest_successful_original_channels,
        "highest_failed_original_sample_rate_hz": cap.highest_failed_original_sample_rate_hz,
        "highest_failed_original_bit_depth": cap.highest_failed_original_bit_depth,
        "highest_failed_original_channels": cap.highest_failed_original_channels,
        "last_failure_reason": cap.last_failure_reason,
        "updated_at": cap.updated_at.isoformat() if cap.updated_at else None,
    }


def _parse_excluded(excluded: Optional[str]) -> list[str]:
    if not excluded:
        return []
    return [item.strip() for item in excluded.split(",") if item.strip()]


@router.get("/api/cast/playback/url")
async def cast_playback_url(
    track_id: int = Query(...),
    renderer_id: str = Query(...),
    excluded: Optional[str] = Query(
        None,
        description=(
            "Comma-separated list of profiles already attempted-and-failed in"
            " this playback session (e.g. 'original_flac,flac_16_48')."
        ),
    ),
    user: asyncpg.Record = Depends(get_current_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
) -> dict[str, Any]:
    if not renderer_id.startswith("cast:"):
        raise HTTPException(status_code=400, detail="renderer_id must be a Cast renderer")

    track = await db.fetchrow(
        "SELECT id, duration_seconds, sample_rate_hz, bit_depth, channels"
        " FROM track WHERE id = $1",
        track_id,
    )
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    quality = track_quality_from_track(dict(track))
    cap = await get_capability(db, renderer_id)
    decision = plan_attempts(quality, cap, _parse_excluded(excluded))

    if not decision.plan:
        raise HTTPException(
            status_code=409,
            detail=(
                "All playback profiles have been exhausted for this Cast"
                " renderer/track combination."
            ),
        )

    profile = decision.plan[0]

    ttl_seconds = stream_token_ttl_seconds("cast", track["duration_seconds"])
    expires_delta = timedelta(seconds=ttl_seconds) if ttl_seconds is not None else None
    token = create_stream_token(
        track_id=track_id,
        user_id=user["id"],
        expires_delta=expires_delta,
    )

    return {
        "profile": profile.value,
        "mime": PROFILE_MIME[profile],
        "url": f"/api/stream/{track_id}?token={token}&profile={profile.value}",
        "is_emergency_fallback": decision.is_emergency_fallback,
        "remaining_profiles": [p.value for p in decision.plan[1:]],
    }


class CastFeedback(BaseModel):
    renderer_id: str
    track_id: int
    profile: str
    success: bool
    reason: Optional[str] = None


@router.post("/api/cast/playback/feedback")
async def cast_playback_feedback(
    payload: CastFeedback,
    user: asyncpg.Record = Depends(get_current_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
) -> dict[str, Any]:
    if not payload.renderer_id.startswith("cast:"):
        raise HTTPException(status_code=400, detail="renderer_id must be a Cast renderer")
    try:
        profile = CastProfile(payload.profile)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown profile: {payload.profile}")

    track = await db.fetchrow(
        "SELECT id, sample_rate_hz, bit_depth, channels FROM track WHERE id = $1",
        payload.track_id,
    )
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    quality = track_quality_from_track(dict(track))
    cap = await get_capability(db, payload.renderer_id)
    if payload.success:
        updated = apply_success(cap, payload.renderer_id, profile, quality)
    else:
        updated = apply_failure(cap, payload.renderer_id, profile, quality, payload.reason)
    await save_capability(db, updated)
    return {"capability": _capability_to_dict(updated)}


@router.get("/api/cast/playback/capability/{renderer_id:path}")
async def cast_playback_capability(
    renderer_id: str,
    user: asyncpg.Record = Depends(get_current_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
) -> dict[str, Any]:
    if not renderer_id.startswith("cast:"):
        raise HTTPException(status_code=400, detail="renderer_id must be a Cast renderer")
    cap = await get_capability(db, renderer_id)
    if cap is None:
        return {"capability": None}
    return {"capability": _capability_to_dict(cap)}
