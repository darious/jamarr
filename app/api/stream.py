import asyncio
import logging
import mimetypes
import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from app.audio_normalization import (
    TARGET_LOUDNESS_LUFS,
    calculate_track_gain_db,
    env_flag_enabled,
)
from app.db import get_db
from app.api.deps import get_current_user_jwt, get_optional_user_jwt
from app.auth_tokens import verify_stream_token
from app.services.audio_streaming import build_stream_url
import asyncpg

router = APIRouter()
logger = logging.getLogger(__name__)

_calculate_normalization_gain_db = calculate_track_gain_db


def _guess_media_type(path: str) -> str:
    media_type, _ = mimetypes.guess_type(path)
    if media_type is not None:
        return media_type

    ext = os.path.splitext(path)[1].lower()
    if ext == ".flac":
        return "audio/flac"
    if ext == ".mp3":
        return "audio/mpeg"
    if ext == ".m4a":
        return "audio/mp4"
    if ext == ".wav":
        return "audio/wav"
    if ext == ".ogg":
        return "audio/ogg"
    return "application/octet-stream"


async def _normalized_audio_chunks(path: str, gain_db: float):
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        path,
        "-map",
        "0:a:0",
        "-vn",
        "-filter:a",
        f"volume={gain_db:.3f}dB",
        "-f",
        "flac",
        "-compression_level",
        "5",
        "pipe:1",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
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
            stderr = b""
            if proc.stderr is not None:
                stderr = await proc.stderr.read()
            logger.warning(
                "ffmpeg normalized stream failed path=%s returncode=%s stderr=%s",
                path,
                return_code,
                stderr.decode("utf-8", errors="replace")[-1000:],
            )
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()


@router.get("/api/stream-url/{track_id}")
async def get_stream_url(
    track_id: int,
    renderer_kind: Optional[str] = None,
    x_jamarr_client_id: Optional[str] = Header(None),
    user: asyncpg.Record = Depends(get_current_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
):
    row = await db.fetchrow("SELECT duration_seconds FROM track WHERE id = $1", track_id)
    if not row:
        raise HTTPException(status_code=404, detail="Track not found")
    stream = await build_stream_url(
        db,
        track_id=track_id,
        duration_seconds=row["duration_seconds"],
        renderer_kind=renderer_kind,
        user_id=user["id"],
        client_id=x_jamarr_client_id,
    )
    return {
        "url": stream.url,
        **stream.claims,
    }


@router.api_route("/api/stream/{track_id}", methods=["GET", "HEAD"])
async def stream_track(
    track_id: int,
    request: Request,
    token: Optional[str] = None,
    normalize: Optional[str] = None,
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
        SELECT
            t.path,
            a.status AS analysis_status,
            a.loudness_lufs,
            a.true_peak_db
        FROM track t
        LEFT JOIN track_audio_analysis a ON a.track_id = t.id
        WHERE t.id = $1
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

    normalization_requested = env_flag_enabled("JAMARR_LOUDNESS_NORMALIZATION", True)
    if normalize is not None:
        normalization_requested = normalize.strip().lower() not in {"0", "false", "off", "no"}
    can_normalize = (
        normalization_requested
        and row["analysis_status"] == "complete"
        and row["loudness_lufs"] is not None
    )
    if can_normalize:
        if stream_claims.get("loudness_normalized") and stream_claims.get("loudness_gain_db") is not None:
            gain_db = float(stream_claims["loudness_gain_db"])
            gain_mode = stream_claims.get("loudness_gain_mode") or "track"
        else:
            gain_db = _calculate_normalization_gain_db(
                float(row["loudness_lufs"]),
                float(row["true_peak_db"]) if row["true_peak_db"] is not None else None,
            )
            gain_mode = "track"
        headers = {
            "X-Jamarr-Loudness-Normalized": "1",
            "X-Jamarr-Loudness-Target-LUFS": f"{TARGET_LOUDNESS_LUFS:g}",
            "X-Jamarr-Loudness-Gain-DB": f"{gain_db:.3f}",
            "X-Jamarr-Loudness-Gain-Mode": gain_mode,
            "Cache-Control": "no-store",
        }
        if request.method == "HEAD":
            return Response(status_code=200, media_type="audio/flac", headers=headers)
        return StreamingResponse(
            _normalized_audio_chunks(path, gain_db),
            media_type="audio/flac",
            headers=headers,
        )

    media_type = _guess_media_type(path)
    return FileResponse(path, media_type=media_type)
