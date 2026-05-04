"""Unit tests for the Cast playback capability hierarchy + cache rules.

These tests cover the pure decision logic in
``app.services.renderer.cast_capability``. They do not touch the database
-- the persistence layer is exercised by the API integration tests --
because every behavioural rule from the product spec is expressible in
terms of ``plan_attempts`` / ``apply_success`` / ``apply_failure``.
"""

from __future__ import annotations

import pytest

from app.services.renderer.cast_capability import (
    CapabilityRecord,
    CastProfile,
    HIERARCHY,
    LOSSLESS_PROFILES,
    TrackQuality,
    apply_failure,
    apply_success,
    plan_attempts,
    track_quality_from_track,
)


RENDERER_ID = "cast:11111111-1111-1111-1111-111111111111"


def _q(sample_rate: int, bit_depth: int, channels: int = 2) -> TrackQuality:
    return TrackQuality(sample_rate_hz=sample_rate, bit_depth=bit_depth, channels=channels)


# ---------------------------------------------------------------------------
# plan_attempts
# ---------------------------------------------------------------------------


def test_no_cache_walks_full_hierarchy_starting_at_original():
    decision = plan_attempts(_q(44100, 16), cap=None)

    assert decision.plan == list(HIERARCHY)
    assert decision.is_emergency_fallback is False


def test_within_proven_capability_still_starts_at_original():
    cap = CapabilityRecord(
        renderer_id=RENDERER_ID,
        best_working_profile=CastProfile.ORIGINAL_FLAC,
        is_lossless=True,
        highest_successful_original_sample_rate_hz=96000,
        highest_successful_original_bit_depth=24,
        highest_successful_original_channels=2,
    )

    decision = plan_attempts(_q(48000, 24), cap)

    assert decision.plan[0] == CastProfile.ORIGINAL_FLAC


def test_exceeds_proven_capability_still_attempts_original():
    cap = CapabilityRecord(
        renderer_id=RENDERER_ID,
        best_working_profile=CastProfile.ORIGINAL_FLAC,
        highest_successful_original_sample_rate_hz=48000,
        highest_successful_original_bit_depth=16,
        highest_successful_original_channels=2,
    )

    decision = plan_attempts(_q(96000, 24), cap)

    # Track exceeds known-good quality; we must still try original first
    # so we can learn whether the renderer accepts the higher quality.
    assert decision.plan[0] == CastProfile.ORIGINAL_FLAC


def test_known_failed_quality_skips_original_and_uses_cached_fallback():
    cap = CapabilityRecord(
        renderer_id=RENDERER_ID,
        best_working_profile=CastProfile.WAV_16_48,
        highest_failed_original_sample_rate_hz=96000,
        highest_failed_original_bit_depth=24,
        highest_failed_original_channels=2,
    )

    decision = plan_attempts(_q(192000, 24), cap)

    assert CastProfile.ORIGINAL_FLAC not in decision.plan
    assert decision.plan[0] == CastProfile.WAV_16_48
    # Best cached fallback is consumed first; remaining hierarchy follows.
    assert CastProfile.MP3_320 in decision.plan
    assert CastProfile.FLAC_16_48 in decision.plan


def test_known_failed_quality_falls_back_below_threshold_still_tries_original():
    cap = CapabilityRecord(
        renderer_id=RENDERER_ID,
        highest_failed_original_sample_rate_hz=96000,
        highest_failed_original_bit_depth=24,
        highest_failed_original_channels=2,
    )

    decision = plan_attempts(_q(44100, 16), cap)

    # Track quality is below the failure threshold, so original is fair game.
    assert decision.plan[0] == CastProfile.ORIGINAL_FLAC


def test_excluded_profiles_are_filtered_out():
    decision = plan_attempts(
        _q(44100, 16),
        cap=None,
        excluded=[CastProfile.ORIGINAL_FLAC, "flac_16_48"],
    )

    assert CastProfile.ORIGINAL_FLAC not in decision.plan
    assert CastProfile.FLAC_16_48 not in decision.plan
    assert decision.plan[0] == CastProfile.WAV_16_48


def test_cached_fallback_profile_is_tried_before_other_fallbacks():
    cap = CapabilityRecord(
        renderer_id=RENDERER_ID,
        best_working_profile=CastProfile.WAV_16_48,
    )

    decision = plan_attempts(_q(44100, 16), cap)

    assert decision.plan[0] == CastProfile.ORIGINAL_FLAC
    fallback_order = decision.plan[1:]
    assert fallback_order[0] == CastProfile.WAV_16_48


def test_emergency_flag_set_only_when_mp3_is_first_attempt():
    cap = CapabilityRecord(
        renderer_id=RENDERER_ID,
        best_working_profile=CastProfile.MP3_320,
        highest_failed_original_sample_rate_hz=44100,
        highest_failed_original_bit_depth=16,
        highest_failed_original_channels=2,
    )

    decision = plan_attempts(
        _q(44100, 16),
        cap,
        excluded=[CastProfile.FLAC_16_48, CastProfile.WAV_16_48],
    )

    assert decision.plan[0] == CastProfile.MP3_320
    assert decision.is_emergency_fallback is True


def test_emergency_flag_off_when_higher_options_remain():
    decision = plan_attempts(_q(44100, 16), cap=None)

    assert decision.is_emergency_fallback is False


# ---------------------------------------------------------------------------
# apply_success
# ---------------------------------------------------------------------------


def test_success_on_original_records_quality_and_marks_lossless():
    track = _q(96000, 24)

    cap = apply_success(None, RENDERER_ID, CastProfile.ORIGINAL_FLAC, track)

    assert cap.best_working_profile == CastProfile.ORIGINAL_FLAC
    assert cap.is_lossless is True
    assert cap.highest_successful_original_sample_rate_hz == 96000
    assert cap.highest_successful_original_bit_depth == 24
    assert cap.highest_successful_original_channels == 2


def test_success_upgrades_only_when_higher_quality_proven():
    base = CapabilityRecord(
        renderer_id=RENDERER_ID,
        best_working_profile=CastProfile.ORIGINAL_FLAC,
        highest_successful_original_sample_rate_hz=96000,
        highest_successful_original_bit_depth=24,
        highest_successful_original_channels=2,
    )

    same_or_lower = apply_success(base, RENDERER_ID, CastProfile.ORIGINAL_FLAC, _q(48000, 24))
    assert same_or_lower.highest_successful_original_sample_rate_hz == 96000

    higher = apply_success(base, RENDERER_ID, CastProfile.ORIGINAL_FLAC, _q(192000, 24))
    assert higher.highest_successful_original_sample_rate_hz == 192000


def test_success_on_mp3_marks_renderer_lossy_unless_already_lossless():
    cap = apply_success(None, RENDERER_ID, CastProfile.MP3_320, _q(44100, 16))
    assert cap.is_lossless is False
    assert cap.best_working_profile == CastProfile.MP3_320

    base = CapabilityRecord(renderer_id=RENDERER_ID, is_lossless=True)
    cap = apply_success(base, RENDERER_ID, CastProfile.MP3_320, _q(44100, 16))
    assert cap.is_lossless is True  # do not regress a known-lossless renderer


def test_success_does_not_downgrade_best_working_profile():
    base = CapabilityRecord(
        renderer_id=RENDERER_ID,
        best_working_profile=CastProfile.ORIGINAL_FLAC,
        is_lossless=True,
    )

    cap = apply_success(base, RENDERER_ID, CastProfile.MP3_320, _q(44100, 16))

    assert cap.best_working_profile == CastProfile.ORIGINAL_FLAC


# ---------------------------------------------------------------------------
# apply_failure
# ---------------------------------------------------------------------------


def test_failure_on_original_records_highest_failed_quality():
    cap = apply_failure(None, RENDERER_ID, CastProfile.ORIGINAL_FLAC, _q(192000, 24), reason="LOAD_FAILED")

    assert cap.highest_failed_original_sample_rate_hz == 192000
    assert cap.highest_failed_original_bit_depth == 24
    assert cap.last_failure_reason == "LOAD_FAILED"


def test_failure_only_advances_threshold_for_higher_quality():
    base = CapabilityRecord(
        renderer_id=RENDERER_ID,
        highest_failed_original_sample_rate_hz=96000,
        highest_failed_original_bit_depth=24,
        highest_failed_original_channels=2,
    )

    lower = apply_failure(base, RENDERER_ID, CastProfile.ORIGINAL_FLAC, _q(44100, 16), reason="x")
    assert lower.highest_failed_original_sample_rate_hz == 96000

    higher = apply_failure(base, RENDERER_ID, CastProfile.ORIGINAL_FLAC, _q(192000, 24), reason="x")
    assert higher.highest_failed_original_sample_rate_hz == 192000


def test_failure_on_fallback_does_not_touch_original_thresholds():
    base = CapabilityRecord(
        renderer_id=RENDERER_ID,
        highest_successful_original_sample_rate_hz=48000,
        highest_successful_original_bit_depth=16,
        highest_successful_original_channels=2,
    )

    cap = apply_failure(base, RENDERER_ID, CastProfile.FLAC_16_48, _q(44100, 16), reason="x")

    assert cap.highest_failed_original_sample_rate_hz is None
    assert cap.highest_successful_original_sample_rate_hz == 48000


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


def test_lossless_profile_set_matches_hierarchy_intent():
    assert CastProfile.MP3_320 not in LOSSLESS_PROFILES
    for profile in (
        CastProfile.ORIGINAL_FLAC,
        CastProfile.FLAC_16_48,
        CastProfile.WAV_16_48,
    ):
        assert profile in LOSSLESS_PROFILES


def test_track_quality_from_track_handles_strings_and_missing_fields():
    quality = track_quality_from_track(
        {"sample_rate_hz": "96000", "bit_depth": 24, "channels": None}
    )

    assert quality.sample_rate_hz == 96000
    assert quality.bit_depth == 24
    assert quality.channels is None


def test_track_quality_comparable_treats_missing_as_zero():
    a = TrackQuality()
    b = TrackQuality(sample_rate_hz=44100, bit_depth=16, channels=2)
    assert a.comparable < b.comparable


def test_quality_comparable_supports_decision_thresholds():
    """The comparable triple is what plan_attempts uses to detect 'meets-or-exceeds'."""

    fail = TrackQuality(sample_rate_hz=96000, bit_depth=24, channels=2)
    same = TrackQuality(sample_rate_hz=96000, bit_depth=24, channels=2)
    higher = TrackQuality(sample_rate_hz=192000, bit_depth=24, channels=2)
    lower = TrackQuality(sample_rate_hz=88200, bit_depth=24, channels=2)

    assert same.comparable >= fail.comparable
    assert higher.comparable >= fail.comparable
    assert not (lower.comparable >= fail.comparable)


# ---------------------------------------------------------------------------
# End-to-end: simulate a session that walks the hierarchy
# ---------------------------------------------------------------------------


def test_full_session_walk_then_subsequent_track_skips_known_failure():
    """High-res FLAC fails on the renderer, FLAC 16/48 works.

    A subsequent same-or-higher-quality track should skip original
    entirely and start at the cached FLAC 16/48 fallback.
    """

    track1 = _q(96000, 24)
    cap = None

    # Attempt 1: original at 96/24 fails.
    decision = plan_attempts(track1, cap)
    assert decision.plan[0] == CastProfile.ORIGINAL_FLAC
    cap = apply_failure(cap, RENDERER_ID, CastProfile.ORIGINAL_FLAC, track1, reason="UNSUPPORTED")

    # Attempt 2: FLAC 16/48 works.
    decision = plan_attempts(track1, cap, excluded=[CastProfile.ORIGINAL_FLAC])
    assert decision.plan[0] == CastProfile.FLAC_16_48
    cap = apply_success(cap, RENDERER_ID, CastProfile.FLAC_16_48, track1)

    # Next track is also high-res. Original is known-bad at >=96/24,
    # so we jump straight to the cached fallback.
    track2 = _q(96000, 24)
    decision = plan_attempts(track2, cap)
    assert decision.plan[0] == CastProfile.FLAC_16_48
    assert CastProfile.ORIGINAL_FLAC not in decision.plan


def test_session_walk_lower_quality_track_still_tries_original():
    cap = apply_failure(
        None, RENDERER_ID, CastProfile.ORIGINAL_FLAC, _q(96000, 24), reason="UNSUPPORTED"
    )
    cap = apply_success(cap, RENDERER_ID, CastProfile.FLAC_16_48, _q(96000, 24))

    decision = plan_attempts(_q(44100, 16), cap)

    assert decision.plan[0] == CastProfile.ORIGINAL_FLAC


@pytest.mark.parametrize(
    "profile,expected_lossless",
    [
        (CastProfile.ORIGINAL_FLAC, True),
        (CastProfile.FLAC_16_48, True),
        (CastProfile.WAV_16_48, True),
        (CastProfile.MP3_320, False),
    ],
)
def test_apply_success_lossless_per_profile(profile: CastProfile, expected_lossless: bool):
    cap = apply_success(None, RENDERER_ID, profile, _q(44100, 16))
    assert cap.is_lossless is expected_lossless
