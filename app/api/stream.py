import asyncio
import logging
import mimetypes
import os
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse

from app.api.deps import get_current_user_jwt, get_optional_user_jwt
from app.audio_normalization import (
    TARGET_LOUDNESS_LUFS,
    calculate_track_gain_db,
    env_flag_enabled,
)
from app.auth_tokens import verify_stream_token
from app.db import get_db, get_pool
from app.services.audio_streaming import build_stream_url
from app.services.stream_profiles import (
    PROFILES,
    cached_profile_path,
    normalize_quality,
    stream_claims_for_quality,
)

router = APIRouter()
logger = logging.getLogger(__name__)

_calculate_normalization_gain_db = calculate_track_gain_db

# ffmpeg needs an explicit muxer when writing to a pipe; it cannot infer one
# from a filename. Keyed by the profile's container extension.
_PIPE_FORMATS = {"flac": "flac", "mp3": "mp3", "opus": "ogg", "wav": "wav"}

# Encoder args for a normalized stream at "original" quality. Applying gain
# forces a re-encode regardless, so FLAC keeps that re-encode lossless.
_ORIGINAL_NORMALIZED_ARGS = (
    "-map",
    "0:a:0",
    "-vn",
    "-c:a",
    "flac",
    "-compression_level",
    "5",
)


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


def _normalized_encode(quality: str) -> tuple[tuple[str, ...], str, str, str]:
    """Encoder args, pipe muxer, mime type and label for a normalized stream."""

    if quality == "original":
        return (
            _ORIGINAL_NORMALIZED_ARGS,
            "flac",
            "audio/flac",
            PROFILES["original"].label,
        )
    profile = PROFILES[quality]
    return (
        profile.ffmpeg_args,
        _PIPE_FORMATS.get(profile.extension, profile.extension),
        profile.mime_type,
        profile.label,
    )


async def _normalized_audio_chunks(
    path: str,
    gain_db: float,
    encode_args: tuple[str, ...] = _ORIGINAL_NORMALIZED_ARGS,
    pipe_format: str = "flac",
):
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        path,
        *encode_args,
        "-filter:a",
        f"volume={gain_db:.3f}dB",
        "-f",
        pipe_format,
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
    quality: Optional[str] = None,
    x_jamarr_client_id: Optional[str] = Header(None),
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
    # The token carries both sets of claims, because /api/stream resolves the
    # output format and the gain from the token alone.
    quality_claims = stream_claims_for_quality(selected_quality, dict(row))
    stream = await build_stream_url(
        db,
        track_id=track_id,
        duration_seconds=row["duration_seconds"],
        renderer_kind=renderer_kind,
        user_id=user["id"],
        client_id=x_jamarr_client_id,
        extra_claims=quality_claims,
    )
    return {
        "url": stream.url,
        **stream.claims,
    }


@router.api_route("/api/stream/{track_id}", methods=["GET", "HEAD"])
async def stream_track(
    request: Request,
    track_id: int,
    token: Optional[str] = None,
    quality: Optional[str] = None,
    normalize: Optional[str] = None,
):
    # Deliberately no Depends(get_db): dependencies with yield are only torn
    # down after the response finishes, which would pin a pool connection for
    # the whole file transfer. Acquire briefly instead.
    pool = get_pool()
    if token:
        stream_claims = verify_stream_token(token, track_id)
    else:
        async with pool.acquire() as db:
            user = await get_optional_user_jwt(
                request.headers.get("authorization"), request, db
            )
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        stream_claims = {}
    async with pool.acquire() as db:
        row = await db.fetchrow(
            """
            SELECT
                t.id, t.path, t.codec, t.sample_rate_hz, t.bit_depth, t.bitrate, t.quick_hash,
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

    selected_quality = normalize_quality(
        quality or stream_claims.get("stream_quality")
    )

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

        # Gain is folded into the same ffmpeg pass that produces the requested
        # profile, reading the original file. Serving the cached transcode and
        # then applying gain would decode and re-encode a lossy profile twice.
        # The cost is that normalized streams bypass the transcode cache; a
        # gain-aware cache key would recover it.
        encode_args, pipe_format, media_type, quality_label = _normalized_encode(
            selected_quality
        )
        headers = {
            "X-Jamarr-Loudness-Normalized": "1",
            "X-Jamarr-Loudness-Target-LUFS": f"{TARGET_LOUDNESS_LUFS:g}",
            "X-Jamarr-Loudness-Gain-DB": f"{gain_db:.3f}",
            "X-Jamarr-Loudness-Gain-Mode": gain_mode,
            "X-Jamarr-Stream-Quality": selected_quality,
            "X-Jamarr-Stream-Quality-Label": quality_label,
            "Cache-Control": "no-store",
        }
        if request.method == "HEAD":
            return Response(status_code=200, media_type=media_type, headers=headers)
        return StreamingResponse(
            _normalized_audio_chunks(path, gain_db, encode_args, pipe_format),
            media_type=media_type,
            headers=headers,
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

    return FileResponse(
        path,
        media_type=_guess_media_type(path),
        headers={
            "X-Jamarr-Stream-Quality": "original",
            "X-Jamarr-Stream-Quality-Label": PROFILES["original"].label,
        },
    )
