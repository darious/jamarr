"""Cast renderer playback-capability learning.

Backend-owned cache: per Cast renderer, remember which playback profile
in the FLAC -> FLAC 16/48 -> WAV 16/48 -> MP3 320 hierarchy actually
worked, the highest original FLAC quality the renderer has accepted, and
the highest original FLAC quality it has refused. The cache is consumed
by both the Python Cast backend (server-driven Cast playback) and the
native Android app (which calls the same HTTP endpoints). Capability is
only ever learned from real playback attempts -- no probes, no test
tones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Iterable, Optional

import asyncpg


class CastProfile(str, Enum):
    ORIGINAL_FLAC = "original_flac"
    FLAC_16_48 = "flac_16_48"
    WAV_16_48 = "wav_16_48"
    MP3_320 = "mp3_320"


# Hierarchy order: try left to right.
HIERARCHY: tuple[CastProfile, ...] = (
    CastProfile.ORIGINAL_FLAC,
    CastProfile.FLAC_16_48,
    CastProfile.WAV_16_48,
    CastProfile.MP3_320,
)

LOSSLESS_PROFILES: frozenset[CastProfile] = frozenset(
    {CastProfile.ORIGINAL_FLAC, CastProfile.FLAC_16_48, CastProfile.WAV_16_48}
)

# Higher rank = higher preference. Used when deciding whether a new
# successful profile should replace the cached best_working_profile.
_PROFILE_RANK: dict[CastProfile, int] = {
    CastProfile.MP3_320: 0,
    CastProfile.WAV_16_48: 1,
    CastProfile.FLAC_16_48: 2,
    CastProfile.ORIGINAL_FLAC: 3,
}


@dataclass(frozen=True)
class TrackQuality:
    """Original-file audio quality used for capability comparisons."""

    sample_rate_hz: Optional[int] = None
    bit_depth: Optional[int] = None
    channels: Optional[int] = None

    @property
    def comparable(self) -> tuple[int, int, int]:
        """A defensive triple suitable for ordering comparisons."""

        return (
            int(self.sample_rate_hz or 0),
            int(self.bit_depth or 0),
            int(self.channels or 0),
        )


@dataclass
class CapabilityRecord:
    renderer_id: str
    best_working_profile: Optional[CastProfile] = None
    is_lossless: Optional[bool] = None
    highest_successful_original_sample_rate_hz: Optional[int] = None
    highest_successful_original_bit_depth: Optional[int] = None
    highest_successful_original_channels: Optional[int] = None
    highest_failed_original_sample_rate_hz: Optional[int] = None
    highest_failed_original_bit_depth: Optional[int] = None
    highest_failed_original_channels: Optional[int] = None
    last_failure_reason: Optional[str] = None
    updated_at: Optional[datetime] = None

    @property
    def proven_original(self) -> Optional[TrackQuality]:
        if self.highest_successful_original_sample_rate_hz is None:
            return None
        return TrackQuality(
            sample_rate_hz=self.highest_successful_original_sample_rate_hz,
            bit_depth=self.highest_successful_original_bit_depth,
            channels=self.highest_successful_original_channels,
        )

    @property
    def failed_original(self) -> Optional[TrackQuality]:
        if self.highest_failed_original_sample_rate_hz is None:
            return None
        return TrackQuality(
            sample_rate_hz=self.highest_failed_original_sample_rate_hz,
            bit_depth=self.highest_failed_original_bit_depth,
            channels=self.highest_failed_original_channels,
        )


@dataclass
class AttemptDecision:
    """Output of plan_attempts() -- the ordered list of profiles to try."""

    plan: list[CastProfile] = field(default_factory=list)
    is_emergency_fallback: bool = False


def plan_attempts(
    track: TrackQuality,
    cap: Optional[CapabilityRecord],
    excluded: Iterable[str | CastProfile] = (),
) -> AttemptDecision:
    """Pick the ordered list of profiles to attempt for a single track.

    The decision rules are:

    - With no cache, walk the full hierarchy.
    - If the next track is within the proven original capability, try
      original first (cached proves it works at that quality).
    - If the next track exceeds the proven original capability, still try
      original first (it may now succeed at the higher quality).
    - If original is already known to fail at this quality (track quality
      meets or exceeds the highest-failed original), skip original
      entirely and start at the best cached fallback profile.
    - Once original is dropped, the cached ``best_working_profile`` (when
      it is a fallback profile) is tried before walking the rest of the
      fallback hierarchy.
    - Profiles already attempted-and-failed in this session, supplied via
      ``excluded``, are removed from the plan.
    """

    excluded_values = {
        item.value if isinstance(item, CastProfile) else str(item) for item in excluded
    }

    skip_original = False
    if cap is not None and cap.failed_original is not None:
        if track.comparable >= cap.failed_original.comparable:
            skip_original = True

    plan: list[CastProfile] = []
    if not skip_original:
        plan.append(CastProfile.ORIGINAL_FLAC)

    fallbacks = [CastProfile.FLAC_16_48, CastProfile.WAV_16_48, CastProfile.MP3_320]
    if cap is not None and cap.best_working_profile in fallbacks:
        idx = fallbacks.index(cap.best_working_profile)
        fallbacks = fallbacks[idx:] + fallbacks[:idx]
    plan.extend(fallbacks)

    plan = [p for p in plan if p.value not in excluded_values]

    is_emergency = bool(plan) and plan[0] == CastProfile.MP3_320
    return AttemptDecision(plan=plan, is_emergency_fallback=is_emergency)


def apply_success(
    cap: Optional[CapabilityRecord],
    renderer_id: str,
    profile: CastProfile,
    track: TrackQuality,
) -> CapabilityRecord:
    """Return a new CapabilityRecord that incorporates a successful attempt."""

    base = cap or CapabilityRecord(renderer_id=renderer_id)
    new = CapabilityRecord(
        renderer_id=renderer_id,
        best_working_profile=base.best_working_profile,
        is_lossless=base.is_lossless,
        highest_successful_original_sample_rate_hz=base.highest_successful_original_sample_rate_hz,
        highest_successful_original_bit_depth=base.highest_successful_original_bit_depth,
        highest_successful_original_channels=base.highest_successful_original_channels,
        highest_failed_original_sample_rate_hz=base.highest_failed_original_sample_rate_hz,
        highest_failed_original_bit_depth=base.highest_failed_original_bit_depth,
        highest_failed_original_channels=base.highest_failed_original_channels,
        last_failure_reason=base.last_failure_reason,
        updated_at=base.updated_at,
    )

    if (
        new.best_working_profile is None
        or _PROFILE_RANK[profile] > _PROFILE_RANK[new.best_working_profile]
    ):
        new.best_working_profile = profile

    if profile in LOSSLESS_PROFILES:
        new.is_lossless = True
    elif new.is_lossless is None:
        new.is_lossless = False

    if profile == CastProfile.ORIGINAL_FLAC:
        cur_high = (
            new.highest_successful_original_sample_rate_hz or 0,
            new.highest_successful_original_bit_depth or 0,
            new.highest_successful_original_channels or 0,
        )
        if track.comparable > cur_high:
            new.highest_successful_original_sample_rate_hz = track.sample_rate_hz
            new.highest_successful_original_bit_depth = track.bit_depth
            new.highest_successful_original_channels = track.channels

    return new


def apply_failure(
    cap: Optional[CapabilityRecord],
    renderer_id: str,
    profile: CastProfile,
    track: TrackQuality,
    reason: Optional[str],
) -> CapabilityRecord:
    """Return a new CapabilityRecord that records a failed attempt."""

    base = cap or CapabilityRecord(renderer_id=renderer_id)
    new = CapabilityRecord(
        renderer_id=renderer_id,
        best_working_profile=base.best_working_profile,
        is_lossless=base.is_lossless,
        highest_successful_original_sample_rate_hz=base.highest_successful_original_sample_rate_hz,
        highest_successful_original_bit_depth=base.highest_successful_original_bit_depth,
        highest_successful_original_channels=base.highest_successful_original_channels,
        highest_failed_original_sample_rate_hz=base.highest_failed_original_sample_rate_hz,
        highest_failed_original_bit_depth=base.highest_failed_original_bit_depth,
        highest_failed_original_channels=base.highest_failed_original_channels,
        last_failure_reason=reason,
        updated_at=base.updated_at,
    )

    if profile == CastProfile.ORIGINAL_FLAC:
        cur_fail = (
            new.highest_failed_original_sample_rate_hz or 0,
            new.highest_failed_original_bit_depth or 0,
            new.highest_failed_original_channels or 0,
        )
        if track.comparable > cur_fail:
            new.highest_failed_original_sample_rate_hz = track.sample_rate_hz
            new.highest_failed_original_bit_depth = track.bit_depth
            new.highest_failed_original_channels = track.channels

    return new


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------


_FETCH_SQL = """
    SELECT
        renderer_id,
        best_working_profile,
        is_lossless,
        highest_successful_original_sample_rate_hz,
        highest_successful_original_bit_depth,
        highest_successful_original_channels,
        highest_failed_original_sample_rate_hz,
        highest_failed_original_bit_depth,
        highest_failed_original_channels,
        last_failure_reason,
        updated_at
    FROM cast_renderer_capability
    WHERE renderer_id = $1
"""


_UPSERT_SQL = """
    INSERT INTO cast_renderer_capability (
        renderer_id,
        best_working_profile,
        is_lossless,
        highest_successful_original_sample_rate_hz,
        highest_successful_original_bit_depth,
        highest_successful_original_channels,
        highest_failed_original_sample_rate_hz,
        highest_failed_original_bit_depth,
        highest_failed_original_channels,
        last_failure_reason,
        updated_at
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
    ON CONFLICT (renderer_id) DO UPDATE SET
        best_working_profile = EXCLUDED.best_working_profile,
        is_lossless = EXCLUDED.is_lossless,
        highest_successful_original_sample_rate_hz =
            EXCLUDED.highest_successful_original_sample_rate_hz,
        highest_successful_original_bit_depth =
            EXCLUDED.highest_successful_original_bit_depth,
        highest_successful_original_channels =
            EXCLUDED.highest_successful_original_channels,
        highest_failed_original_sample_rate_hz =
            EXCLUDED.highest_failed_original_sample_rate_hz,
        highest_failed_original_bit_depth =
            EXCLUDED.highest_failed_original_bit_depth,
        highest_failed_original_channels =
            EXCLUDED.highest_failed_original_channels,
        last_failure_reason = EXCLUDED.last_failure_reason,
        updated_at = NOW()
"""


def _row_to_record(row: asyncpg.Record) -> CapabilityRecord:
    profile_raw = row["best_working_profile"]
    profile = CastProfile(profile_raw) if profile_raw else None
    return CapabilityRecord(
        renderer_id=row["renderer_id"],
        best_working_profile=profile,
        is_lossless=row["is_lossless"],
        highest_successful_original_sample_rate_hz=row[
            "highest_successful_original_sample_rate_hz"
        ],
        highest_successful_original_bit_depth=row["highest_successful_original_bit_depth"],
        highest_successful_original_channels=row["highest_successful_original_channels"],
        highest_failed_original_sample_rate_hz=row[
            "highest_failed_original_sample_rate_hz"
        ],
        highest_failed_original_bit_depth=row["highest_failed_original_bit_depth"],
        highest_failed_original_channels=row["highest_failed_original_channels"],
        last_failure_reason=row["last_failure_reason"],
        updated_at=row["updated_at"],
    )


async def get_capability(
    db: asyncpg.Connection, renderer_id: str
) -> Optional[CapabilityRecord]:
    row = await db.fetchrow(_FETCH_SQL, renderer_id)
    if not row:
        return None
    return _row_to_record(row)


async def save_capability(
    db: asyncpg.Connection, record: CapabilityRecord
) -> None:
    await db.execute(
        _UPSERT_SQL,
        record.renderer_id,
        record.best_working_profile.value if record.best_working_profile else None,
        record.is_lossless,
        record.highest_successful_original_sample_rate_hz,
        record.highest_successful_original_bit_depth,
        record.highest_successful_original_channels,
        record.highest_failed_original_sample_rate_hz,
        record.highest_failed_original_bit_depth,
        record.highest_failed_original_channels,
        record.last_failure_reason,
    )


async def record_success(
    db: asyncpg.Connection,
    renderer_id: str,
    profile: CastProfile,
    track: TrackQuality,
) -> CapabilityRecord:
    cap = await get_capability(db, renderer_id)
    updated = apply_success(cap, renderer_id, profile, track)
    await save_capability(db, updated)
    return updated


async def record_failure(
    db: asyncpg.Connection,
    renderer_id: str,
    profile: CastProfile,
    track: TrackQuality,
    reason: Optional[str],
) -> CapabilityRecord:
    cap = await get_capability(db, renderer_id)
    updated = apply_failure(cap, renderer_id, profile, track, reason)
    await save_capability(db, updated)
    return updated


# ---------------------------------------------------------------------------
# Profile -> wire-format helpers
# ---------------------------------------------------------------------------

PROFILE_MIME: dict[CastProfile, str] = {
    CastProfile.ORIGINAL_FLAC: "audio/flac",
    CastProfile.FLAC_16_48: "audio/flac",
    CastProfile.WAV_16_48: "audio/wav",
    CastProfile.MP3_320: "audio/mpeg",
}


def track_quality_from_track(track: dict) -> TrackQuality:
    """Best-effort extraction of original quality from a track dict."""

    return TrackQuality(
        sample_rate_hz=_int_or_none(track.get("sample_rate_hz")),
        bit_depth=_int_or_none(track.get("bit_depth")),
        channels=_int_or_none(track.get("channels")),
    )


def _int_or_none(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
