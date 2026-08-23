import mimetypes
import os
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse

from app.api.deps import get_current_user_jwt, get_optional_user_jwt
from app.audio_normalization import (
    TARGET_LOUDNESS_LUFS,
    calculate_track_gain_db,
    env_flag_enabled,
)
from app.auth_tokens import verify_stream_token
from app.db import db_conn, get_db
from app.services.audio_streaming import build_stream_url
from app.services.stream_profiles import (
    PROFILES,
    ProfileVariant,
    cached_profile_path,
    normalize_quality,
    stream_claims_for_quality,
)

router = APIRouter()

_calculate_normalization_gain_db = calculate_track_gain_db

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


def _original_encode_args(bit_depth: Optional[int]) -> tuple[str, ...]:
    """FLAC encoder args that keep the source's bit depth.

    The volume filter widens the sample format, so without pinning it a 16-bit
    source comes back as 24-bit -- around 60% larger for no audible gain.
    """

    if bit_depth and int(bit_depth) > 16:
        return _ORIGINAL_NORMALIZED_ARGS + ("-sample_fmt", "s32", "-bits_per_raw_sample", "24")
    if bit_depth and int(bit_depth) <= 16:
        return _ORIGINAL_NORMALIZED_ARGS + ("-sample_fmt", "s16")
    # Unknown depth: let ffmpeg choose rather than risk truncating.
    return _ORIGINAL_NORMALIZED_ARGS


def _gain_variant(
    quality: str, gain_db: float, gain_mode: str, bit_depth: Optional[int] = None
) -> ProfileVariant:
    """Cache-distinct normalized rendering of `quality` at this gain.

    Gain is deterministic per track and mode, so the key stays bounded at one
    entry per (track, quality, mode) rather than growing per request.
    """

    variant_key = f"gain-{gain_mode}-{gain_db:.3f}".replace(".", "_").replace("-", "m")
    filters = ("-filter:a", f"volume={gain_db:.3f}dB")
    if quality == "original":
        # "original" is normally served straight from disk, so it has no
        # encoder args of its own; gain forces a re-encode, and FLAC keeps
        # that re-encode lossless.
        return ProfileVariant(
            key=f"{variant_key}-b{bit_depth or 0}",
            filters=filters,
            encode_args=_original_encode_args(bit_depth),
            extension="flac",
            mime_type="audio/flac",
        )
    return ProfileVariant(key=variant_key, filters=filters)


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
    if token:
        stream_claims = verify_stream_token(token, track_id)
    else:
        async with db_conn() as db:
            user = await get_optional_user_jwt(
                request.headers.get("authorization"), request, db
            )
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        stream_claims = {}
    async with db_conn() as db:
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

        # The normalized rendering is cached like any other profile rather than
        # generated per request, so the response stays a plain file and keeps
        # Range support. Streaming ffmpeg live cost seeking entirely, and made
        # every re-request re-encode the whole track. Gain is folded into that
        # single pass off the original file: transcoding first and then applying
        # gain would decode and re-encode a lossy profile twice.
        try:
            cached_path, profile = await cached_profile_path(
                source_path=path,
                track=dict(row),
                quality=selected_quality,
                variant=_gain_variant(selected_quality, gain_db, gain_mode, row["bit_depth"]),
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=f"Transcode failed: {exc}") from exc
        return FileResponse(
            cached_path,
            media_type=profile.mime_type,
            headers={
                "X-Jamarr-Loudness-Normalized": "1",
                "X-Jamarr-Loudness-Target-LUFS": f"{TARGET_LOUDNESS_LUFS:g}",
                "X-Jamarr-Loudness-Gain-DB": f"{gain_db:.3f}",
                "X-Jamarr-Loudness-Gain-Mode": gain_mode,
                "X-Jamarr-Stream-Quality": selected_quality,
                "X-Jamarr-Stream-Quality-Label": profile.label,
            },
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
