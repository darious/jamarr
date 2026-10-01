from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient


@pytest.fixture
async def tracks(db):
    await db.execute(
        """
        INSERT INTO track (id, title, artist, album, duration_seconds, path) VALUES
            (200, 'Long Song', 'Test Artist', 'Test Album', 180, '/music/long.flac'),
            (201, 'Short Song', 'Test Artist', 'Test Album', 60, '/music/short.flac')
        """
    )


def _play(track_id: int, played_at: datetime, ms_played: int) -> dict:
    return {"track_id": track_id, "played_at": played_at.isoformat(), "ms_played": ms_played}


@pytest.mark.asyncio
async def test_plays_are_recorded_at_the_time_they_happened(auth_client: AsyncClient, db, tracks):
    played_at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=2)

    response = await auth_client.post(
        "/api/history/offline",
        json={"client_id": "phone-1", "plays": [_play(200, played_at, 45_000)]},
    )

    assert response.status_code == 200
    assert response.json()["recorded"] == 1
    row = await db.fetchrow(
        """
        SELECT h.timestamp, h.client_id, u.username
        FROM playback_history h JOIN "user" u ON u.id = h.user_id
        WHERE h.track_id = 200
        """
    )
    assert row["timestamp"] == played_at
    assert row["client_id"] == "phone-1"
    assert row["username"] == "testuser"


@pytest.mark.asyncio
async def test_the_live_threshold_applies(auth_client: AsyncClient, tracks):
    now = datetime.now(timezone.utc)

    response = await auth_client.post(
        "/api/history/offline",
        json={
            "plays": [
                # 180s track: needs 30s.
                _play(200, now - timedelta(hours=2), 29_000),
                _play(200, now - timedelta(hours=1), 30_000),
                # 60s track: 20% is 12s, below the 30s cap.
                _play(201, now - timedelta(minutes=30), 12_000),
            ]
        },
    )

    body = response.json()
    assert body["recorded"] == 2
    assert body["too_short"] == 1


@pytest.mark.asyncio
async def test_resending_a_batch_records_nothing_twice(auth_client: AsyncClient, db, tracks):
    batch = {"plays": [_play(200, datetime.now(timezone.utc) - timedelta(hours=1), 60_000)]}

    first = await auth_client.post("/api/history/offline", json=batch)
    second = await auth_client.post("/api/history/offline", json=batch)

    assert first.json()["recorded"] == 1
    assert second.json() == {
        "recorded": 0,
        "duplicates": 1,
        "too_short": 0,
        "unknown_tracks": 0,
        "invalid": 0,
    }
    assert await db.fetchval("SELECT COUNT(*) FROM playback_history WHERE track_id = 200") == 1


@pytest.mark.asyncio
async def test_unknown_tracks_and_future_plays_are_skipped(auth_client: AsyncClient, tracks):
    now = datetime.now(timezone.utc)

    response = await auth_client.post(
        "/api/history/offline",
        json={
            "plays": [
                _play(999_999, now - timedelta(hours=1), 60_000),
                _play(200, now + timedelta(days=1), 60_000),
            ]
        },
    )

    body = response.json()
    assert body["unknown_tracks"] == 1
    assert body["invalid"] == 1
    assert body["recorded"] == 0


@pytest.mark.asyncio
async def test_requires_authentication(client: AsyncClient, tracks):
    response = await client.post("/api/history/offline", json={"plays": []})

    assert response.status_code == 401
