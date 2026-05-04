from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from app.db import get_db
from app.api.deps import get_current_user_jwt, get_optional_user_jwt
from app.auth_tokens import create_stream_token, verify_stream_token
from app.services.renderer.token_policy import stream_token_ttl_seconds
from app.services.renderer.cast_capability import CastProfile, PROFILE_MIME
import asyncio
import asyncpg
import logging
import os
from typing import AsyncIterator, Optional

router = APIRouter()
logger = logging.getLogger(__name__)

import mimetypes  # noqa: E402


@router.get("/api/stream-url/{track_id}")
async def get_stream_url(
    track_id: int,
    renderer_kind: Optional[str] = None,
    user: asyncpg.Record = Depends(get_current_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
):
    row = await db.fetchrow("SELECT duration_seconds FROM track WHERE id = $1", track_id)
    if not row:
        raise HTTPException(status_code=404, detail="Track not found")
    ttl_seconds = stream_token_ttl_seconds(renderer_kind, row["duration_seconds"])
    expires_delta = timedelta(seconds=ttl_seconds) if ttl_seconds is not None else None
    token = create_stream_token(
        track_id=track_id,
        user_id=user["id"],
        expires_delta=expires_delta,
    )
    return {"url": f"/api/stream/{track_id}?token={token}"}


@router.api_route("/api/stream/{track_id}", methods=["GET", "HEAD"])
async def stream_track(
    track_id: int,
    token: Optional[str] = None,
    profile: Optional[str] = None,
    user: Optional[asyncpg.Record] = Depends(get_optional_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
):
    if token:
        verify_stream_token(token, track_id)
    elif not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    row = await db.fetchrow("SELECT path FROM track WHERE id = $1", track_id)
    if not row:
        raise HTTPException(status_code=404, detail="Track not found")

    from app.config import get_music_path

    path = row["path"]
    if not os.path.isabs(path):
        path = os.path.join(get_music_path(), path)

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    selected_profile = _coerce_profile(profile)
    if selected_profile is None or selected_profile == CastProfile.ORIGINAL_FLAC:
        media_type = _detect_media_type(path)
        return FileResponse(path, media_type=media_type)

    return _transcoded_response(path, selected_profile)


def _coerce_profile(profile: Optional[str]) -> Optional[CastProfile]:
    if not profile:
        return None
    try:
        return CastProfile(profile)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown stream profile: {profile}")


def _detect_media_type(path: str) -> str:
    media_type, _ = mimetypes.guess_type(path)
    if media_type:
        return media_type
    ext = os.path.splitext(path)[1].lower()
    return {
        ".flac": "audio/flac",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
    }.get(ext, "application/octet-stream")


def _ffmpeg_args(path: str, profile: CastProfile) -> list[str]:
    """ffmpeg argv for the requested transcode profile.

    All profiles fold to stereo; Cast receivers expect 2-channel output.
    """

    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path, "-map", "0:a", "-vn"]
    if profile == CastProfile.FLAC_16_48:
        return base + [
            "-ac", "2",
            "-ar", "48000",
            "-sample_fmt", "s16",
            "-compression_level", "5",
            "-f", "flac",
            "pipe:1",
        ]
    if profile == CastProfile.WAV_16_48:
        return base + [
            "-ac", "2",
            "-ar", "48000",
            "-sample_fmt", "s16",
            "-f", "wav",
            "pipe:1",
        ]
    if profile == CastProfile.MP3_320:
        return base + [
            "-ac", "2",
            "-ar", "44100",
            "-b:a", "320k",
            "-codec:a", "libmp3lame",
            "-f", "mp3",
            "pipe:1",
        ]
    raise HTTPException(status_code=400, detail=f"Profile not transcodable: {profile.value}")


def _transcoded_response(path: str, profile: CastProfile) -> StreamingResponse:
    media_type = PROFILE_MIME[profile]
    args = _ffmpeg_args(path, profile)
    return StreamingResponse(
        _ffmpeg_iterator(args),
        media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )


async def _ffmpeg_iterator(args: list[str]) -> AsyncIterator[bytes]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None
    try:
        while True:
            chunk = await proc.stdout.read(64 * 1024)
            if not chunk:
                break
            yield chunk
        return_code = await proc.wait()
        if return_code != 0:
            stderr = (await proc.stderr.read()).decode(errors="replace") if proc.stderr else ""
            logger.warning("ffmpeg exit=%s args=%s err=%s", return_code, args, stderr)
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
