import asyncio
import logging
import math
import os
import re
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional, Sequence

import asyncpg

from app.config import get_music_path
from app.db import get_db


logger = logging.getLogger("scanner.audio_analysis")

ANALYSIS_VERSION = 1
DEFAULT_BATCH_SIZE = 25
DEFAULT_CONCURRENCY = 2
DEFAULT_SILENCE_THRESHOLD_DB = -60.0
DEFAULT_SILENCE_MIN_DURATION_SECONDS = 0.2
DEFAULT_TIMEOUT_SECONDS = 600
BPM_SAMPLE_RATE = 11025
BPM_HOP_SAMPLES = 256
BPM_FRAME_SAMPLES = 1024
BPM_MIN = 60.0
BPM_MAX = 200.0
REPLAYGAIN_TARGET_DB = 89.0


@dataclass(frozen=True)
class TrackCandidate:
    id: int
    path: str
    quick_hash: Optional[bytes]
    duration_seconds: Optional[float]


@dataclass(frozen=True)
class Phase1Result:
    loudness_lufs: Optional[float]
    loudness_range_lu: Optional[float]
    sample_peak_db: Optional[float]
    true_peak_db: Optional[float]
    silence_start_seconds: Optional[float]
    silence_end_seconds: Optional[float]
    first_audio_start_seconds: Optional[float]
    last_audio_end_seconds: Optional[float]
    leading_silence_seconds: Optional[float]
    trailing_silence_seconds: Optional[float]


@dataclass(frozen=True)
class Phase2Result:
    replaygain_track_gain_db: Optional[float]
    replaygain_track_peak: Optional[float]


@dataclass(frozen=True)
class Phase3Result:
    bpm: Optional[float]
    bpm_confidence: Optional[float]


@dataclass(frozen=True)
class Phase4Result:
    gapless_hint: Optional[str]
    transition_hint: Optional[str]
    energy_score_local: Optional[float]


def _parse_float(value: str) -> Optional[float]:
    try:
        if value.lower() in {"inf", "+inf", "-inf", "nan"}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_ebur128_summary(stderr: str) -> tuple[Optional[float], Optional[float], Optional[float]]:
    summary_match = re.search(r"Summary:\s*(?P<summary>.*?)(?:\n\[|$)", stderr, re.S)
    if not summary_match:
        return None, None, None

    summary = summary_match.group("summary")
    loudness = None
    loudness_range = None
    true_peak = None

    loudness_match = re.search(r"Integrated loudness:.*?I:\s*([+-]?\d+(?:\.\d+)?)\s+LUFS", summary, re.S)
    if loudness_match:
        loudness = _parse_float(loudness_match.group(1))

    range_match = re.search(r"Loudness range:.*?LRA:\s*([+-]?\d+(?:\.\d+)?)\s+LU", summary, re.S)
    if range_match:
        loudness_range = _parse_float(range_match.group(1))

    true_peak_match = re.search(r"True peak:.*?Peak:\s*([+-]?\d+(?:\.\d+)?)\s+dBFS", summary, re.S)
    if true_peak_match:
        true_peak = _parse_float(true_peak_match.group(1))

    return loudness, loudness_range, true_peak


def _parse_sample_peak(stderr: str) -> Optional[float]:
    overall_match = re.search(
        r"\[Parsed_astats_[^\]]+\]\s+Overall(?P<overall>.*?)(?:\[out#|\Z)",
        stderr,
        re.S,
    )
    search_area = overall_match.group("overall") if overall_match else stderr
    peaks = re.findall(r"Peak level dB:\s*([+-]?\d+(?:\.\d+)?)", search_area)
    if not peaks:
        return None
    return _parse_float(peaks[-1])


def _parse_silence(
    stderr: str,
    duration_seconds: Optional[float],
    tolerance_seconds: float = 0.05,
) -> tuple[Optional[float], Optional[float]]:
    intervals: list[tuple[float, Optional[float], bool]] = []
    active_start: Optional[float] = None

    for line in stderr.splitlines():
        start_match = re.search(r"silence_start:\s*([0-9.]+)", line)
        if start_match:
            active_start = float(start_match.group(1))
            continue

        end_match = re.search(r"silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)", line)
        if end_match:
            silence_end = float(end_match.group(1))
            silence_duration = float(end_match.group(2))
            silence_start = active_start
            if silence_start is None:
                silence_start = max(0.0, silence_end - silence_duration)
            intervals.append((silence_start, silence_end, True))
            active_start = None

    if active_start is not None:
        intervals.append((active_start, duration_seconds, False))

    leading_end = None
    for start, end, _closed in intervals:
        if start <= tolerance_seconds and end is not None:
            leading_end = end

    trailing_start = None
    if intervals:
        start, end, closed = intervals[-1]
        if not closed:
            trailing_start = start
        elif duration_seconds is not None and end is not None:
            # ffmpeg emits a matching silence_end at EOF. Count only that final
            # EOF-closing interval, never an earlier internal silence.
            if end >= duration_seconds - tolerance_seconds:
                trailing_start = start

    return leading_end, trailing_start


def _parse_replaygain(stderr: str) -> Phase2Result:
    gain = None
    peak = None

    gain_match = re.search(r"track_gain\s*=\s*([+-]?\d+(?:\.\d+)?)\s*dB", stderr)
    if gain_match:
        gain = _parse_float(gain_match.group(1))

    peak_match = re.search(r"track_peak\s*=\s*([0-9]+(?:\.\d+)?)", stderr)
    if peak_match:
        peak = _parse_float(peak_match.group(1))

    return Phase2Result(
        replaygain_track_gain_db=gain,
        replaygain_track_peak=peak,
    )


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _estimate_bpm_from_samples(samples: Sequence[float], sample_rate: int) -> Phase3Result:
    if len(samples) < BPM_FRAME_SAMPLES * 4:
        return Phase3Result(bpm=None, bpm_confidence=None)

    energies: list[float] = []
    for start in range(0, len(samples) - BPM_FRAME_SAMPLES, BPM_HOP_SAMPLES):
        frame = samples[start:start + BPM_FRAME_SAMPLES]
        energy = sum(abs(sample) for sample in frame) / BPM_FRAME_SAMPLES
        energies.append(energy)

    if len(energies) < 16:
        return Phase3Result(bpm=None, bpm_confidence=None)

    envelope: list[float] = [0.0]
    for prev, current in zip(energies, energies[1:]):
        envelope.append(max(0.0, current - prev))

    mean = sum(envelope) / len(envelope)
    centered = [max(0.0, value - mean) for value in envelope]
    if not any(centered):
        return Phase3Result(bpm=None, bpm_confidence=0.0)

    frames_per_second = sample_rate / BPM_HOP_SAMPLES
    min_lag = max(1, int(round(frames_per_second * 60.0 / BPM_MAX)))
    max_lag = max(min_lag + 1, int(round(frames_per_second * 60.0 / BPM_MIN)))

    best_lag = None
    best_score = 0.0
    scores: list[float] = []
    for lag in range(min_lag, min(max_lag, len(centered) // 2) + 1):
        score = 0.0
        for idx in range(lag, len(centered)):
            score += centered[idx] * centered[idx - lag]
        normalized = score / max(1, len(centered) - lag)
        scores.append(normalized)
        if normalized > best_score:
            best_score = normalized
            best_lag = lag

    if best_lag is None or best_score <= 0:
        return Phase3Result(bpm=None, bpm_confidence=0.0)

    bpm = 60.0 * frames_per_second / best_lag
    while bpm < BPM_MIN:
        bpm *= 2
    while bpm > BPM_MAX:
        bpm /= 2

    avg_score = sum(scores) / len(scores) if scores else 0.0
    confidence = _clamp((best_score / avg_score - 1.0) / 3.0) if avg_score > 0 else 0.0
    return Phase3Result(bpm=round(bpm, 2), bpm_confidence=round(confidence, 3))


async def analyze_phase1_file(
    path: str,
    *,
    duration_seconds: Optional[float] = None,
    silence_threshold_db: float = DEFAULT_SILENCE_THRESHOLD_DB,
    silence_min_duration_seconds: float = DEFAULT_SILENCE_MIN_DURATION_SECONDS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> Phase1Result:
    filter_spec = (
        "ebur128=peak=true,"
        "astats=metadata=1:reset=0,"
        f"silencedetect=n={silence_threshold_db:g}dB:d={silence_min_duration_seconds:g}"
    )
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-vn",
        "-i",
        path,
        "-af",
        filter_spec,
        "-f",
        "null",
        "-",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"ffmpeg analysis timed out after {timeout_seconds}s")

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(err[-2000:] or f"ffmpeg exited with {proc.returncode}")

    stderr_text = stderr.decode("utf-8", errors="replace")
    loudness, loudness_range, true_peak = _parse_ebur128_summary(stderr_text)
    sample_peak = _parse_sample_peak(stderr_text)
    silence_start, silence_end = _parse_silence(stderr_text, duration_seconds)
    leading_silence = silence_start or 0.0
    if duration_seconds is not None and silence_end is not None:
        trailing_silence = max(0.0, duration_seconds - silence_end)
    else:
        trailing_silence = 0.0

    first_audio_start = leading_silence
    if duration_seconds is not None:
        last_audio_end = silence_end if silence_end is not None else duration_seconds
    else:
        last_audio_end = silence_end

    return Phase1Result(
        loudness_lufs=loudness,
        loudness_range_lu=loudness_range,
        sample_peak_db=sample_peak,
        true_peak_db=true_peak,
        silence_start_seconds=silence_start,
        silence_end_seconds=silence_end,
        first_audio_start_seconds=first_audio_start,
        last_audio_end_seconds=last_audio_end,
        leading_silence_seconds=leading_silence,
        trailing_silence_seconds=trailing_silence,
    )


async def analyze_phase2_file(
    path: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> Phase2Result:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-vn",
        "-i",
        path,
        "-af",
        "replaygain",
        "-f",
        "null",
        "-",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"ffmpeg ReplayGain analysis timed out after {timeout_seconds}s")

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(err[-2000:] or f"ffmpeg exited with {proc.returncode}")

    return _parse_replaygain(stderr.decode("utf-8", errors="replace"))


async def analyze_phase3_file(
    path: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> Phase3Result:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-v",
        "error",
        "-nostats",
        "-vn",
        "-i",
        path,
        "-ac",
        "1",
        "-ar",
        str(BPM_SAMPLE_RATE),
        "-f",
        "f32le",
        "-",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"ffmpeg BPM decode timed out after {timeout_seconds}s")

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(err[-2000:] or f"ffmpeg exited with {proc.returncode}")

    sample_count = len(stdout) // 4
    if sample_count == 0:
        return Phase3Result(bpm=None, bpm_confidence=None)
    samples = struct.unpack(f"<{sample_count}f", stdout[: sample_count * 4])
    return _estimate_bpm_from_samples(samples, BPM_SAMPLE_RATE)


def derive_phase4_result(row: asyncpg.Record) -> Phase4Result:
    leading = float(row["leading_silence_seconds"] or 0.0)
    trailing = float(row["trailing_silence_seconds"] or 0.0)
    lufs = row["loudness_lufs"]
    lra = row["loudness_range_lu"]
    bpm = row["bpm"]

    if trailing > 30:
        gapless_hint = "long_digital_tail"
    elif leading <= 0.05 and trailing <= 0.05:
        gapless_hint = "gapless_candidate"
    elif leading > 1.0 or trailing > 1.0:
        gapless_hint = "trim_silence"
    else:
        gapless_hint = "standard"

    if trailing > 10:
        transition_hint = "skip_or_trim_tail"
    elif trailing > 1.0:
        transition_hint = "trim_tail"
    elif leading > 1.0:
        transition_hint = "trim_head"
    elif bpm and row["next_bpm"] and abs(float(bpm) - float(row["next_bpm"])) <= 6:
        transition_hint = "tempo_compatible"
    else:
        transition_hint = "standard"

    loudness_component = _clamp(((float(lufs) if lufs is not None else -23.0) + 30.0) / 24.0)
    bpm_component = _clamp(((float(bpm) if bpm is not None else 110.0) - 60.0) / 120.0)
    compression_component = 1.0 - _clamp((float(lra) if lra is not None else 12.0) / 20.0)
    silence_penalty = _clamp((leading + trailing) / 10.0)
    energy = (
        0.55 * loudness_component
        + 0.20 * bpm_component
        + 0.20 * compression_component
        + 0.05 * (1.0 - silence_penalty)
    )

    return Phase4Result(
        gapless_hint=gapless_hint,
        transition_hint=transition_hint,
        energy_score_local=round(_clamp(energy), 3),
    )


class AudioAnalysisRunner:
    def __init__(
        self,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        concurrency: int = DEFAULT_CONCURRENCY,
        limit: Optional[int] = None,
        force: bool = False,
        dry_run: bool = False,
        track_id: Optional[int] = None,
        path: Optional[str] = None,
        silence_threshold_db: float = DEFAULT_SILENCE_THRESHOLD_DB,
        silence_min_duration_seconds: float = DEFAULT_SILENCE_MIN_DURATION_SECONDS,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        progress_cb: Optional[Callable[[int, Optional[int], str], None]] = None,
    ) -> None:
        self.batch_size = max(1, batch_size)
        self.concurrency = max(1, concurrency)
        self.limit = limit
        self.force = force
        self.dry_run = dry_run
        self.track_id = track_id
        self.path = path
        self.silence_threshold_db = silence_threshold_db
        self.silence_min_duration_seconds = silence_min_duration_seconds
        self.timeout_seconds = timeout_seconds
        self.progress_cb = progress_cb
        self.music_path = get_music_path()
        self._last_seen_track_id = 0

    async def run_phase1(self) -> dict[str, int]:
        stats = {"selected": 0, "analyzed": 0, "updated": 0, "errors": 0, "skipped": 0}
        processed = 0
        self._last_seen_track_id = 0

        async for db in get_db():
            total = await self._count_candidates(db, phase=1)
            stats["selected"] = total
            if self.progress_cb:
                self.progress_cb(0, total, f"Selected {total} tracks for Phase 1 analysis")
            if total == 0:
                break

            while True:
                remaining = max(0, total - processed)
                if remaining == 0:
                    break

                rows = await self._fetch_candidates(db, remaining, phase=1)
                if not rows:
                    break

                candidates = [
                    TrackCandidate(
                        id=row["id"],
                        path=row["path"],
                        quick_hash=row["quick_hash"],
                        duration_seconds=row["duration_seconds"],
                    )
                    for row in rows
                ]
                self._last_seen_track_id = max(candidate.id for candidate in candidates)
                if self.progress_cb:
                    batch_end = processed + len(candidates)
                    self.progress_cb(
                        processed,
                        total,
                        f"Analyzing batch {processed + 1}-{batch_end} of {total}",
                    )

                if self.dry_run:
                    processed += len(candidates)
                    stats["skipped"] += len(candidates)
                    for candidate in candidates:
                        logger.info("Would analyze track %s: %s", candidate.id, candidate.path)
                    if self.progress_cb:
                        self.progress_cb(
                            processed,
                            total,
                            f"Dry run selected {processed}/{total} tracks",
                        )
                    break

                batch_done = 0

                def batch_progress(candidate: TrackCandidate) -> None:
                    nonlocal batch_done
                    batch_done += 1
                    if self.progress_cb:
                        self.progress_cb(
                            processed + batch_done,
                            total,
                            f"Finished ffmpeg {processed + batch_done}/{total}: {candidate.path}",
                        )

                results = await self._analyze_batch(candidates, progress_cb=batch_progress)
                for candidate, result, error in results:
                    if error:
                        stats["errors"] += 1
                        await self._store_error(db, candidate, error)
                    else:
                        stats["analyzed"] += 1
                        stats["updated"] += 1
                        await self._store_phase1(db, candidate, result)

                    processed += 1
                    if self.progress_cb:
                        status = "Error" if error else "Analyzed"
                        self.progress_cb(
                            processed,
                            total,
                            f"{status} {processed}/{total}: {candidate.path}",
                        )

                if len(candidates) < self.batch_size:
                    break

            break

        return stats

    async def run_phase2(self) -> dict[str, int]:
        stats = {"selected": 0, "analyzed": 0, "updated": 0, "errors": 0, "skipped": 0}
        processed = 0
        touched_albums: set[str] = set()
        self._last_seen_track_id = 0

        async for db in get_db():
            total = await self._count_candidates(db, phase=2)
            stats["selected"] = total
            if self.progress_cb:
                self.progress_cb(0, total, f"Selected {total} tracks for Phase 2 ReplayGain")
            if total == 0:
                if not self.dry_run:
                    await self._update_album_replaygain(db)
                break

            while True:
                remaining = max(0, total - processed)
                if remaining == 0:
                    break

                rows = await self._fetch_candidates(db, remaining, phase=2)
                if not rows:
                    break

                candidates = [self._candidate_from_row(row) for row in rows]
                albums = {self._album_key(row) for row in rows}
                touched_albums.update(album for album in albums if album)
                self._last_seen_track_id = max(candidate.id for candidate in candidates)
                if self.progress_cb:
                    self.progress_cb(
                        processed,
                        total,
                        f"ReplayGain batch {processed + 1}-{processed + len(candidates)} of {total}",
                    )

                if self.dry_run:
                    processed += len(candidates)
                    stats["skipped"] += len(candidates)
                    if self.progress_cb:
                        self.progress_cb(processed, total, f"Dry run selected {processed}/{total} tracks")
                    break

                results = await self._analyze_phase2_batch(candidates)
                for candidate, result, error in results:
                    if error:
                        stats["errors"] += 1
                        await self._store_error(db, candidate, error)
                    else:
                        stats["analyzed"] += 1
                        stats["updated"] += 1
                        await self._store_phase2(db, candidate, result)

                    processed += 1
                    if self.progress_cb:
                        status = "Error" if error else "ReplayGain"
                        self.progress_cb(processed, total, f"{status} {processed}/{total}: {candidate.path}")

                if len(candidates) < self.batch_size:
                    break

            if not self.dry_run:
                await self._update_album_replaygain(db, touched_albums)
            break

        return stats

    async def run_phase3(self) -> dict[str, int]:
        stats = {"selected": 0, "analyzed": 0, "updated": 0, "errors": 0, "skipped": 0}
        processed = 0
        self._last_seen_track_id = 0

        async for db in get_db():
            total = await self._count_candidates(db, phase=3)
            stats["selected"] = total
            if self.progress_cb:
                self.progress_cb(0, total, f"Selected {total} tracks for Phase 3 BPM")
            if total == 0:
                break

            while True:
                remaining = max(0, total - processed)
                if remaining == 0:
                    break

                rows = await self._fetch_candidates(db, remaining, phase=3)
                if not rows:
                    break

                candidates = [self._candidate_from_row(row) for row in rows]
                self._last_seen_track_id = max(candidate.id for candidate in candidates)
                if self.progress_cb:
                    self.progress_cb(processed, total, f"BPM batch {processed + 1}-{processed + len(candidates)} of {total}")

                if self.dry_run:
                    processed += len(candidates)
                    stats["skipped"] += len(candidates)
                    if self.progress_cb:
                        self.progress_cb(processed, total, f"Dry run selected {processed}/{total} tracks")
                    break

                results = await self._analyze_phase3_batch(candidates)
                for candidate, result, error in results:
                    if error:
                        stats["errors"] += 1
                        await self._store_error(db, candidate, error)
                    else:
                        stats["analyzed"] += 1
                        stats["updated"] += 1
                        await self._store_phase3(db, candidate, result)

                    processed += 1
                    if self.progress_cb:
                        status = "Error" if error else "BPM"
                        self.progress_cb(processed, total, f"{status} {processed}/{total}: {candidate.path}")

                if len(candidates) < self.batch_size:
                    break

            break

        return stats

    async def run_phase4(self) -> dict[str, int]:
        stats = {"selected": 0, "analyzed": 0, "updated": 0, "errors": 0, "skipped": 0}
        processed = 0
        self._last_seen_track_id = 0

        async for db in get_db():
            total = await self._count_candidates(db, phase=4)
            stats["selected"] = total
            if self.progress_cb:
                self.progress_cb(0, total, f"Selected {total} tracks for Phase 4 hints")
            if total == 0:
                break

            while True:
                remaining = max(0, total - processed)
                if remaining == 0:
                    break

                rows = await self._fetch_phase4_candidates(db, remaining)
                if not rows:
                    break

                self._last_seen_track_id = max(row["id"] for row in rows)
                if self.progress_cb:
                    self.progress_cb(processed, total, f"Hint batch {processed + 1}-{processed + len(rows)} of {total}")

                if self.dry_run:
                    processed += len(rows)
                    stats["skipped"] += len(rows)
                    if self.progress_cb:
                        self.progress_cb(processed, total, f"Dry run selected {processed}/{total} tracks")
                    break

                for row in rows:
                    candidate = self._candidate_from_row(row)
                    try:
                        result = derive_phase4_result(row)
                        await self._store_phase4(db, candidate, result)
                        stats["analyzed"] += 1
                        stats["updated"] += 1
                    except Exception as exc:
                        stats["errors"] += 1
                        await self._store_error(db, candidate, str(exc))

                    processed += 1
                    if self.progress_cb:
                        self.progress_cb(processed, total, f"Hints {processed}/{total}: {candidate.path}")

                if len(rows) < self.batch_size:
                    break

            break

        return stats

    async def _count_candidates(self, db: asyncpg.Connection, *, phase: int) -> int:
        params: list[Any] = []
        filters = self._candidate_filters(params, include_cursor=False, phase=phase)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        query = f"""
            SELECT count(*)
            FROM track t
            LEFT JOIN track_audio_analysis a ON a.track_id = t.id
            {where_clause}
        """
        count = await db.fetchval(query, *params)
        if self.limit is None:
            return int(count or 0)
        return min(int(count or 0), max(0, self.limit))

    async def _fetch_candidates(
        self, db: asyncpg.Connection, remaining: Optional[int], *, phase: int
    ) -> list[asyncpg.Record]:
        limit = self.batch_size if remaining is None else min(self.batch_size, remaining)
        params: list[Any] = []
        filters = self._candidate_filters(params, include_cursor=True, phase=phase)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.append(limit)
        limit_param = len(params)
        query = f"""
            SELECT
                t.id, t.path, t.quick_hash, t.duration_seconds,
                t.release_mbid, t.release_group_mbid, t.album, t.album_artist
            FROM track t
            LEFT JOIN track_audio_analysis a ON a.track_id = t.id
            {where_clause}
            ORDER BY t.id
            LIMIT ${limit_param}
        """
        return list(await db.fetch(query, *params))

    def _candidate_filters(self, params: list[Any], *, include_cursor: bool, phase: int) -> list[str]:
        filters: list[str] = []
        phase_column = f"phase{phase}_analyzed_at"

        if not self.force:
            params.append(ANALYSIS_VERSION)
            version_param = len(params)
            filters.append(
                f"""
                (
                    a.track_id IS NULL
                    OR a.{phase_column} IS NULL
                    OR a.track_quick_hash IS DISTINCT FROM t.quick_hash
                    OR a.analysis_version < ${version_param}
                )
                """
            )

        if phase in {2, 3, 4}:
            filters.append("a.phase1_analyzed_at IS NOT NULL")

        if self.track_id is not None:
            params.append(self.track_id)
            filters.append(f"t.id = ${len(params)}")

        if include_cursor and self._last_seen_track_id:
            params.append(self._last_seen_track_id)
            filters.append(f"t.id > ${len(params)}")

        path_filter = self._path_filter()
        if path_filter:
            params.append(path_filter[1])
            if path_filter[0] == "exact":
                filters.append(f"t.path = ${len(params)}")
            else:
                filters.append(f"t.path LIKE ${len(params)}")

        return filters

    def _candidate_from_row(self, row: asyncpg.Record) -> TrackCandidate:
        return TrackCandidate(
            id=row["id"],
            path=row["path"],
            quick_hash=row["quick_hash"],
            duration_seconds=row["duration_seconds"],
        )

    def _album_key(self, row: asyncpg.Record) -> Optional[str]:
        return row["release_mbid"] or (
            f"{row['album_artist'] or ''}\x1f{row['album'] or ''}"
            if row["album"]
            else None
        )

    def _path_filter(self) -> Optional[tuple[str, str]]:
        if not self.path:
            return None

        candidate = self.path
        if os.path.isabs(candidate):
            try:
                candidate = os.path.relpath(candidate, self.music_path)
            except ValueError:
                pass

        candidate = candidate.strip("/")
        if not candidate:
            return None
        if os.path.splitext(candidate)[1]:
            return ("exact", candidate)
        return ("prefix", f"{candidate.rstrip('/')}/%")

    async def _analyze_batch(
        self,
        candidates: Iterable[TrackCandidate],
        progress_cb: Optional[Callable[[TrackCandidate], None]] = None,
    ) -> list[tuple[TrackCandidate, Optional[Phase1Result], Optional[str]]]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def run_one(candidate: TrackCandidate):
            async with semaphore:
                full_path = os.path.join(self.music_path, candidate.path)
                if not os.path.exists(full_path):
                    if progress_cb:
                        progress_cb(candidate)
                    return candidate, None, f"File not found: {full_path}"
                try:
                    result = await analyze_phase1_file(
                        full_path,
                        duration_seconds=candidate.duration_seconds,
                        silence_threshold_db=self.silence_threshold_db,
                        silence_min_duration_seconds=self.silence_min_duration_seconds,
                        timeout_seconds=self.timeout_seconds,
                    )
                    if progress_cb:
                        progress_cb(candidate)
                    return candidate, result, None
                except Exception as exc:
                    logger.warning("Audio analysis failed for track %s: %s", candidate.id, exc)
                    if progress_cb:
                        progress_cb(candidate)
                    return candidate, None, str(exc)

        return await asyncio.gather(*(run_one(candidate) for candidate in candidates))

    async def _analyze_phase2_batch(
        self, candidates: Iterable[TrackCandidate]
    ) -> list[tuple[TrackCandidate, Optional[Phase2Result], Optional[str]]]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def run_one(candidate: TrackCandidate):
            async with semaphore:
                full_path = os.path.join(self.music_path, candidate.path)
                if not os.path.exists(full_path):
                    return candidate, None, f"File not found: {full_path}"
                try:
                    result = await analyze_phase2_file(full_path, timeout_seconds=self.timeout_seconds)
                    return candidate, result, None
                except Exception as exc:
                    logger.warning("ReplayGain analysis failed for track %s: %s", candidate.id, exc)
                    return candidate, None, str(exc)

        return await asyncio.gather(*(run_one(candidate) for candidate in candidates))

    async def _analyze_phase3_batch(
        self, candidates: Iterable[TrackCandidate]
    ) -> list[tuple[TrackCandidate, Optional[Phase3Result], Optional[str]]]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def run_one(candidate: TrackCandidate):
            async with semaphore:
                full_path = os.path.join(self.music_path, candidate.path)
                if not os.path.exists(full_path):
                    return candidate, None, f"File not found: {full_path}"
                try:
                    result = await analyze_phase3_file(full_path, timeout_seconds=self.timeout_seconds)
                    return candidate, result, None
                except Exception as exc:
                    logger.warning("BPM analysis failed for track %s: %s", candidate.id, exc)
                    return candidate, None, str(exc)

        return await asyncio.gather(*(run_one(candidate) for candidate in candidates))

    async def _fetch_phase4_candidates(
        self, db: asyncpg.Connection, remaining: Optional[int]
    ) -> list[asyncpg.Record]:
        limit = self.batch_size if remaining is None else min(self.batch_size, remaining)
        params: list[Any] = []
        filters = self._candidate_filters(params, include_cursor=True, phase=4)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.append(limit)
        limit_param = len(params)
        query = f"""
            WITH ordered AS (
                SELECT
                    t.id,
                    LEAD(a.bpm) OVER (
                        PARTITION BY COALESCE(t.release_mbid, COALESCE(t.album_artist, '') || chr(31) || COALESCE(t.album, ''))
                        ORDER BY COALESCE(t.disc_no, 0), COALESCE(t.track_no, 0), t.id
                    ) AS next_bpm
                FROM track t
                LEFT JOIN track_audio_analysis a ON a.track_id = t.id
            )
            SELECT
                t.id, t.path, t.quick_hash, t.duration_seconds,
                t.release_mbid, t.release_group_mbid, t.album, t.album_artist,
                a.loudness_lufs, a.loudness_range_lu,
                a.leading_silence_seconds, a.trailing_silence_seconds,
                a.bpm, o.next_bpm
            FROM track t
            JOIN track_audio_analysis a ON a.track_id = t.id
            LEFT JOIN ordered o ON o.id = t.id
            {where_clause}
            ORDER BY t.id
            LIMIT ${limit_param}
        """
        return list(await db.fetch(query, *params))

    async def _update_album_replaygain(
        self, db: asyncpg.Connection, touched_albums: Optional[set[str]] = None
    ) -> None:
        params: list[Any] = []
        key_expr = "COALESCE(t.release_mbid, COALESCE(t.album_artist, '') || chr(31) || COALESCE(t.album, ''))"
        filter_clause = ""
        if touched_albums:
            params.append(list(touched_albums))
            filter_clause = f"WHERE {key_expr} = ANY($1::text[])"

        rows = await db.fetch(
            f"""
            SELECT
                t.id,
                t.duration_seconds,
                t.quick_hash,
                {key_expr} AS album_key,
                a.track_quick_hash,
                a.phase2_analyzed_at,
                a.replaygain_track_gain_db,
                a.replaygain_track_peak
            FROM track t
            LEFT JOIN track_audio_analysis a ON a.track_id = t.id
            {filter_clause}
            ORDER BY album_key, t.disc_no, t.track_no, t.id
            """,
            *params,
        )

        groups: dict[str, list[asyncpg.Record]] = {}
        for row in rows:
            if row["album_key"]:
                groups.setdefault(row["album_key"], []).append(row)

        for group_rows in groups.values():
            complete = all(
                row["phase2_analyzed_at"] is not None
                and row["track_quick_hash"] == row["quick_hash"]
                and row["replaygain_track_gain_db"] is not None
                for row in group_rows
            )
            if not complete:
                continue

            weighted = 0.0
            total_weight = 0.0
            peaks: list[float] = []
            for row in group_rows:
                duration = float(row["duration_seconds"] or 1.0)
                gain = float(row["replaygain_track_gain_db"])
                weighted += duration * math.pow(10.0, -gain / 10.0)
                total_weight += duration
                if row["replaygain_track_peak"] is not None:
                    peaks.append(float(row["replaygain_track_peak"]))

            if weighted <= 0 or total_weight <= 0:
                continue

            album_gain = -10.0 * math.log10(weighted / total_weight)
            album_peak = max(peaks) if peaks else None
            await db.execute(
                """
                UPDATE track_audio_analysis
                SET replaygain_album_gain_db = $1,
                    replaygain_album_peak = $2,
                    updated_at = $3
                WHERE track_id = ANY($4::bigint[])
                """,
                round(album_gain, 2),
                album_peak,
                datetime.now(timezone.utc),
                [row["id"] for row in group_rows],
            )

    async def _store_phase1(
        self, db: asyncpg.Connection, candidate: TrackCandidate, result: Phase1Result
    ) -> None:
        now = datetime.now(timezone.utc)
        await db.execute(
            """
            INSERT INTO track_audio_analysis (
                track_id, track_quick_hash, analysis_version, status, error,
                analyzed_at, phase1_analyzed_at,
                loudness_lufs, loudness_range_lu, sample_peak_db, true_peak_db,
                silence_start_seconds, silence_end_seconds,
                first_audio_start_seconds, last_audio_end_seconds,
                leading_silence_seconds, trailing_silence_seconds,
                silence_threshold_db, silence_min_duration_seconds,
                updated_at
            )
            VALUES (
                $1, $2, $3, 'complete', NULL,
                $4, $4,
                $5, $6, $7, $8,
                $9, $10,
                $11, $12,
                $13, $14,
                $15, $16,
                $4
            )
            ON CONFLICT (track_id) DO UPDATE SET
                track_quick_hash = excluded.track_quick_hash,
                analysis_version = excluded.analysis_version,
                status = excluded.status,
                error = excluded.error,
                analyzed_at = excluded.analyzed_at,
                phase1_analyzed_at = excluded.phase1_analyzed_at,
                loudness_lufs = excluded.loudness_lufs,
                loudness_range_lu = excluded.loudness_range_lu,
                sample_peak_db = excluded.sample_peak_db,
                true_peak_db = excluded.true_peak_db,
                silence_start_seconds = excluded.silence_start_seconds,
                silence_end_seconds = excluded.silence_end_seconds,
                first_audio_start_seconds = excluded.first_audio_start_seconds,
                last_audio_end_seconds = excluded.last_audio_end_seconds,
                leading_silence_seconds = excluded.leading_silence_seconds,
                trailing_silence_seconds = excluded.trailing_silence_seconds,
                silence_threshold_db = excluded.silence_threshold_db,
                silence_min_duration_seconds = excluded.silence_min_duration_seconds,
                updated_at = excluded.updated_at
            """,
            candidate.id,
            candidate.quick_hash,
            ANALYSIS_VERSION,
            now,
            result.loudness_lufs,
            result.loudness_range_lu,
            result.sample_peak_db,
            result.true_peak_db,
            result.silence_start_seconds,
            result.silence_end_seconds,
            result.first_audio_start_seconds,
            result.last_audio_end_seconds,
            result.leading_silence_seconds,
            result.trailing_silence_seconds,
            self.silence_threshold_db,
            self.silence_min_duration_seconds,
        )

    async def _store_phase2(
        self, db: asyncpg.Connection, candidate: TrackCandidate, result: Phase2Result
    ) -> None:
        now = datetime.now(timezone.utc)
        await db.execute(
            """
            INSERT INTO track_audio_analysis (
                track_id, track_quick_hash, analysis_version, status, error,
                analyzed_at, phase2_analyzed_at,
                replaygain_track_gain_db, replaygain_track_peak,
                updated_at
            )
            VALUES ($1, $2, $3, 'complete', NULL, $4, $4, $5, $6, $4)
            ON CONFLICT (track_id) DO UPDATE SET
                track_quick_hash = excluded.track_quick_hash,
                analysis_version = excluded.analysis_version,
                status = excluded.status,
                error = excluded.error,
                analyzed_at = excluded.analyzed_at,
                phase2_analyzed_at = excluded.phase2_analyzed_at,
                replaygain_track_gain_db = excluded.replaygain_track_gain_db,
                replaygain_track_peak = excluded.replaygain_track_peak,
                updated_at = excluded.updated_at
            """,
            candidate.id,
            candidate.quick_hash,
            ANALYSIS_VERSION,
            now,
            result.replaygain_track_gain_db,
            result.replaygain_track_peak,
        )

    async def _store_phase3(
        self, db: asyncpg.Connection, candidate: TrackCandidate, result: Phase3Result
    ) -> None:
        now = datetime.now(timezone.utc)
        await db.execute(
            """
            INSERT INTO track_audio_analysis (
                track_id, track_quick_hash, analysis_version, status, error,
                analyzed_at, phase3_analyzed_at,
                bpm, bpm_confidence,
                updated_at
            )
            VALUES ($1, $2, $3, 'complete', NULL, $4, $4, $5, $6, $4)
            ON CONFLICT (track_id) DO UPDATE SET
                track_quick_hash = excluded.track_quick_hash,
                analysis_version = excluded.analysis_version,
                status = excluded.status,
                error = excluded.error,
                analyzed_at = excluded.analyzed_at,
                phase3_analyzed_at = excluded.phase3_analyzed_at,
                bpm = excluded.bpm,
                bpm_confidence = excluded.bpm_confidence,
                updated_at = excluded.updated_at
            """,
            candidate.id,
            candidate.quick_hash,
            ANALYSIS_VERSION,
            now,
            result.bpm,
            result.bpm_confidence,
        )

    async def _store_phase4(
        self, db: asyncpg.Connection, candidate: TrackCandidate, result: Phase4Result
    ) -> None:
        now = datetime.now(timezone.utc)
        await db.execute(
            """
            INSERT INTO track_audio_analysis (
                track_id, track_quick_hash, analysis_version, status, error,
                analyzed_at, phase4_analyzed_at,
                gapless_hint, transition_hint, energy_score_local,
                updated_at
            )
            VALUES ($1, $2, $3, 'complete', NULL, $4, $4, $5, $6, $7, $4)
            ON CONFLICT (track_id) DO UPDATE SET
                track_quick_hash = excluded.track_quick_hash,
                analysis_version = excluded.analysis_version,
                status = excluded.status,
                error = excluded.error,
                analyzed_at = excluded.analyzed_at,
                phase4_analyzed_at = excluded.phase4_analyzed_at,
                gapless_hint = excluded.gapless_hint,
                transition_hint = excluded.transition_hint,
                energy_score_local = excluded.energy_score_local,
                updated_at = excluded.updated_at
            """,
            candidate.id,
            candidate.quick_hash,
            ANALYSIS_VERSION,
            now,
            result.gapless_hint,
            result.transition_hint,
            result.energy_score_local,
        )

    async def _store_error(
        self, db: asyncpg.Connection, candidate: TrackCandidate, error: str
    ) -> None:
        now = datetime.now(timezone.utc)
        await db.execute(
            """
            INSERT INTO track_audio_analysis (
                track_id, track_quick_hash, analysis_version, status, error, updated_at
            )
            VALUES ($1, $2, $3, 'error', $4, $5)
            ON CONFLICT (track_id) DO UPDATE SET
                track_quick_hash = excluded.track_quick_hash,
                analysis_version = excluded.analysis_version,
                status = excluded.status,
                error = excluded.error,
                updated_at = excluded.updated_at
            """,
            candidate.id,
            candidate.quick_hash,
            ANALYSIS_VERSION,
            error[-4000:],
            now,
        )
