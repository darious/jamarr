from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from app.db import get_db
from app.api.deps import get_current_user_jwt, get_optional_user_jwt
from app.auth_tokens import create_stream_token, verify_stream_token
from app.services.renderer.token_policy import stream_token_ttl_seconds
from app.services.stream_profiles import (
    PROFILES,
    cached_profile_path,
    normalize_quality,
    stream_claims_for_quality,
)
import asyncpg
import os
from typing import Optional

router = APIRouter()

import mimetypes  # noqa: E402


@router.get("/api/stream-url/{track_id}")
async def get_stream_url(
    track_id: int,
    renderer_kind: Optional[str] = None,
    quality: Optional[str] = None,
    user: asyncpg.Record = Depends(get_current_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
):
    row = await db.fetchrow(
        """
        SELECT id, path, duration_seconds, codec, sample_rate_hz, bit_depth, bitrate, quick_hash
        FROM track
        WHERE id = $1
        """,
        track_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Track not found")
    selected_quality = normalize_quality(quality)
    claims = stream_claims_for_quality(selected_quality, dict(row))
    ttl_seconds = stream_token_ttl_seconds(renderer_kind, row["duration_seconds"])
    expires_delta = timedelta(seconds=ttl_seconds) if ttl_seconds is not None else None
    token = create_stream_token(
        track_id=track_id,
        user_id=user["id"],
        expires_delta=expires_delta,
        stream_claims=claims,
    )
    return {
        "url": f"/api/stream/{track_id}?token={token}",
        **claims,
    }


@router.api_route("/api/stream/{track_id}", methods=["GET", "HEAD"])
async def stream_track(
    track_id: int,
    token: Optional[str] = None,
    quality: Optional[str] = None,
    user: Optional[asyncpg.Record] = Depends(get_optional_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
):
    if token:
        stream_claims = verify_stream_token(token, track_id)
    elif not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    else:
        stream_claims = {}
    row = await db.fetchrow(
        """
        SELECT id, path, codec, sample_rate_hz, bit_depth, bitrate, quick_hash
        FROM track
        WHERE id = $1
        """,
        track_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Track not found")

    from app.config import get_music_path

    path = row["path"]
    if not os.path.isabs(path):
        path = os.path.join(get_music_path(), path)

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    selected_quality = normalize_quality(
        quality or stream_claims.get("stream_quality")
    )
    if selected_quality != "original":
        try:
            cached_path, profile = await cached_profile_path(
                source_path=path,
                track=dict(row),
                quality=selected_quality,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=f"Transcode failed: {exc}") from exc
        return FileResponse(
            cached_path,
            media_type=profile.mime_type,
            headers={
                "X-Jamarr-Stream-Quality": selected_quality,
                "X-Jamarr-Stream-Quality-Label": profile.label,
            },
        )

    # Guess mime type or default to octet-stream
    media_type, _ = mimetypes.guess_type(path)
    if media_type is None:
        # Fallbacks for common types if system mime.types is missing
        ext = os.path.splitext(path)[1].lower()
        if ext == ".flac":
            media_type = "audio/flac"
        elif ext == ".mp3":
            media_type = "audio/mpeg"
        elif ext == ".m4a":
            media_type = "audio/mp4"
        elif ext == ".wav":
            media_type = "audio/wav"
        elif ext == ".ogg":
            media_type = "audio/ogg"
        else:
            media_type = "application/octet-stream"

    # print(f"[Stream] Serving {track_id}: {path} as {media_type}")
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "X-Jamarr-Stream-Quality": "original",
            "X-Jamarr-Stream-Quality-Label": PROFILES["original"].label,
        },
    )
