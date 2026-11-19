"""Plays are recorded at their start time, not at the moment they were logged."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services.player import history as history_mod
from app.services.player.history import log_history, play_started_at


def test_play_started_at_subtracts_position():
    now = datetime(2026, 11, 19, 12, 0, 30, tzinfo=timezone.utc)
    assert play_started_at(30, now) == datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)
    assert play_started_at(None, now) == now
    assert play_started_at(-5, now) == now


async def _track(db, track_id=700):
    await db.execute(
        "INSERT INTO track (id, path, title, artist) VALUES ($1, $2, 'Song', 'Artist')",
        track_id,
        f"/music/{track_id}.flac",
    )
    return track_id


@pytest.mark.asyncio
async def test_log_history_stores_start_time_and_scrobbles_it(db, test_user):
    track_id = await _track(db)
    scrobbled = []

    async def fake_scrobble(_user_id, _track_id, played_at=None):
        scrobbled.append(played_at)

    before = datetime.now(timezone.utc)
    with patch.object(history_mod, "scrobble_to_lastfm", fake_scrobble):
        await log_history(db, track_id, "10.0.0.2", "client-1", test_user["id"], position_seconds=31.5)
    after = datetime.now(timezone.utc)

    stamp = await db.fetchval("SELECT timestamp FROM playback_history WHERE track_id = $1", track_id)
    assert before - timedelta(seconds=31.5) <= stamp <= after - timedelta(seconds=31.5)
    await asyncio.sleep(0)  # let the scrobble task run
    assert scrobbled == [int(stamp.timestamp())]


@pytest.mark.asyncio
async def test_duplicate_report_of_same_play_is_ignored(db, test_user):
    track_id = await _track(db)
    with patch.object(history_mod, "scrobble_to_lastfm", AsyncMock()):
        await log_history(db, track_id, "10.0.0.2", "client-1", test_user["id"], position_seconds=30)
        # Same play reported again a moment later, further into the track.
        await log_history(db, track_id, "10.0.0.2", "client-1", test_user["id"], position_seconds=32)
    assert await db.fetchval("SELECT COUNT(*) FROM playback_history WHERE track_id = $1", track_id) == 1


@pytest.mark.asyncio
async def test_replay_of_same_track_is_a_new_play(db, test_user):
    track_id = await _track(db)
    with patch.object(history_mod, "scrobble_to_lastfm", AsyncMock()):
        # First play started four minutes ago; the replay started 30 s ago.
        await log_history(db, track_id, "10.0.0.2", "client-1", test_user["id"], position_seconds=240)
        await log_history(db, track_id, "10.0.0.2", "client-1", test_user["id"], position_seconds=30)
    assert await db.fetchval("SELECT COUNT(*) FROM playback_history WHERE track_id = $1", track_id) == 2

