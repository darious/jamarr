from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StreamProfile:
    key: str
    label: str
    extension: str
    mime_type: str
    ffmpeg_args: tuple[str, ...] = ()
    cached: bool = False


PROFILES: dict[str, StreamProfile] = {
    "original": StreamProfile(
        key="original",
        label="Original",
        extension="",
        mime_type="",
    ),
    "flac_24_48": StreamProfile(
        key="flac_24_48",
        label="FLAC 24/48",
        extension="flac",
        mime_type="audio/flac",
        ffmpeg_args=(
            "-map",
            "0:a:0",
            "-vn",
            "-ar",
            "48000",
            "-sample_fmt",
            "s32",
            "-bits_per_raw_sample",
            "24",
            "-c:a",
            "flac",
            "-compression_level",
            "5",
        ),
        cached=True,
    ),
    "flac_16_48": StreamProfile(
        key="flac_16_48",
        label="FLAC 16/48",
        extension="flac",
        mime_type="audio/flac",
        ffmpeg_args=(
            "-map",
            "0:a:0",
            "-vn",
            "-ar",
            "48000",
            "-sample_fmt",
            "s16",
            "-c:a",
            "flac",
            "-compression_level",
            "5",
        ),
        cached=True,
    ),
    "mp3_320": StreamProfile(
        key="mp3_320",
        label="MP3 320",
        extension="mp3",
        mime_type="audio/mpeg",
        ffmpeg_args=(
            "-map",
            "0:a:0",
            "-vn",
            "-ar",
            "48000",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "320k",
        ),
        cached=True,
    ),
    "opus_128": StreamProfile(
        key="opus_128",
        label="Opus 128",
        extension="opus",
        mime_type="audio/ogg",
        ffmpeg_args=(
            "-map",
            "0:a:0",
            "-vn",
            "-ar",
            "48000",
            "-c:a",
            "libopus",
            "-b:a",
            "128k",
            "-vbr",
            "on",
        ),
        cached=True,
    ),
}

QUALITY_LADDER = ["original", "flac_24_48", "flac_16_48", "mp3_320", "opus_128"]
PROFILE_ALIASES = {
    "auto": "original",
    "high": "flac_24_48",
    "normal": "flac_16_48",
    "mobile": "opus_128",
}

_cleanup_last_run = 0.0
_transcode_locks: dict[str, asyncio.Lock] = {}


def normalize_quality(value: str | None) -> str:
    key = (value or "original").strip().lower()
    key = PROFILE_ALIASES.get(key, key)
    if key not in PROFILES:
        key = "original"
    return key


def next_lower_quality(current: str | None) -> str:
    key = normalize_quality(current)
    try:
        idx = QUALITY_LADDER.index(key)
    except ValueError:
        return "original"
    return QUALITY_LADDER[min(idx + 1, len(QUALITY_LADDER) - 1)]


def original_quality_label(track: dict[str, Any]) -> str:
    codec = str(track.get("codec") or Path(str(track.get("path") or "")).suffix.lstrip(".") or "audio")
    codec = codec.upper()
    if codec == "MPEG AUDIO":
        codec = "MP3"
    bit_depth = track.get("bit_depth")
    sample_rate = track.get("sample_rate_hz")
    parts = [codec]
    if bit_depth:
        parts.append(f"{int(bit_depth)} bit")
    if sample_rate:
        parts.append(_sample_rate_label(int(sample_rate)))
    return " ".join(parts)


def stream_claims_for_quality(quality: str, track: dict[str, Any]) -> dict[str, Any]:
    key = normalize_quality(quality)
    profile = PROFILES[key]
    return {
        "stream_quality": key,
        "stream_quality_label": profile.label,
        "stream_mime_type": profile.mime_type or None,
        "original_quality_label": original_quality_label(track),
    }


async def cached_profile_path(
    *,
    source_path: str,
    track: dict[str, Any],
    quality: str,
) -> tuple[Path, StreamProfile]:
    key = normalize_quality(quality)
    profile = PROFILES[key]
    if not profile.cached:
        return Path(source_path), profile

    cache_dir = _cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = _cache_fingerprint(track, source_path)
    out_path = cache_dir / f"track-{track['id']}-{fingerprint}-{key}.{profile.extension}"

    if out_path.exists() and out_path.stat().st_size > 0:
        _touch(out_path)
        return out_path, profile

    lock = _transcode_locks.setdefault(str(out_path), asyncio.Lock())
    async with lock:
        if out_path.exists() and out_path.stat().st_size > 0:
            _touch(out_path)
            return out_path, profile
        await _transcode(source_path, out_path, profile)
        await cleanup_stream_cache()
    return out_path, profile


async def cleanup_stream_cache(force: bool = False) -> None:
    global _cleanup_last_run
    now = time.time()
    if not force and now - _cleanup_last_run < int(os.getenv("JAMARR_STREAM_CACHE_CLEANUP_INTERVAL_SECONDS", "3600")):
        return
    _cleanup_last_run = now

    cache_dir = _cache_dir()
    if not cache_dir.exists():
        return
    max_age_seconds = int(os.getenv("JAMARR_STREAM_CACHE_MAX_AGE_SECONDS", str(14 * 24 * 60 * 60)))
    max_bytes = int(os.getenv("JAMARR_STREAM_CACHE_MAX_BYTES", str(100 * 1024 * 1024 * 1024)))
    cutoff = now - max_age_seconds

    files = []
    for path in cache_dir.glob("track-*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime < cutoff:
            _unlink_quietly(path)
            continue
        files.append((path, stat.st_size, stat.st_mtime))

    total = sum(size for _, size, _ in files)
    if total <= max_bytes:
        return
    for path, size, _ in sorted(files, key=lambda item: item[2]):
        _unlink_quietly(path)
        total -= size
        if total <= max_bytes:
            break


async def _transcode(source_path: str, out_path: Path, profile: StreamProfile) -> None:
    temp_fd, temp_name = tempfile.mkstemp(
        prefix=f".{out_path.name}.",
        suffix=f".tmp.{profile.extension}",
        dir=str(out_path.parent),
    )
    os.close(temp_fd)
    temp_path = Path(temp_name)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        source_path,
        *profile.ffmpeg_args,
        str(temp_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        _unlink_quietly(temp_path)
        raise RuntimeError(
            stderr.decode("utf-8", errors="replace")[-2000:]
            or f"ffmpeg exited with {proc.returncode}"
        )
    if not temp_path.exists() or temp_path.stat().st_size <= 0:
        _unlink_quietly(temp_path)
        raise RuntimeError("ffmpeg produced an empty stream cache file")
    shutil.move(str(temp_path), str(out_path))
    _touch(out_path)


def _cache_dir() -> Path:
    return Path(os.getenv("JAMARR_STREAM_CACHE_DIR", "/app/cache/stream"))


def _cache_fingerprint(track: dict[str, Any], source_path: str) -> str:
    quick_hash = track.get("quick_hash")
    if isinstance(quick_hash, memoryview):
        quick_hash = quick_hash.tobytes()
    if isinstance(quick_hash, bytes):
        return quick_hash.hex()
    if isinstance(quick_hash, bytearray):
        return bytes(quick_hash).hex()
    if quick_hash:
        return str(quick_hash)
    stat = os.stat(source_path)
    return f"{int(stat.st_mtime)}-{stat.st_size}"


def _sample_rate_label(sample_rate_hz: int) -> str:
    if sample_rate_hz % 1000 == 0:
        return f"{sample_rate_hz // 1000} kHz"
    return f"{sample_rate_hz / 1000:.1f} kHz"


def _touch(path: Path) -> None:
    now = time.time()
    os.utime(path, (now, now))


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
