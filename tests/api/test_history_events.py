import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.api.history import history_events
from app.history_events import HistoryEvents
from app.services.player.history import log_history


@pytest.fixture
async def track(db):
    await db.execute(
        """
        INSERT INTO track (id, title, artist, album, duration_seconds, path)
        VALUES (300, 'Song', 'Test Artist', 'Test Album', 180, '/music/song.flac')
        """
    )


@pytest.fixture
def published(monkeypatch) -> list:
    """User ids passed to HistoryEvents.publish during the test."""
    calls: list = []
    monkeypatch.setattr(HistoryEvents.get_instance(), "publish", calls.append)
    return calls


@pytest.mark.asyncio
async def test_publish_reaches_every_subscriber_and_unsubscribes_on_close():
    events = HistoryEvents()
    first, second = events.subscribe(), events.subscribe()
    first_next = asyncio.ensure_future(first.__anext__())
    second_next = asyncio.ensure_future(second.__anext__())
    await asyncio.sleep(0)

    events.publish(7)

    assert await first_next == {"user_id": 7}
    assert await second_next == {"user_id": 7}
    await first.aclose()
    await second.aclose()
    assert events._queues == set()


@pytest.mark.asyncio
async def test_stream_tells_each_user_whether_the_change_was_theirs():
    response = await history_events(user={"id": 5})
    frames = response.body_iterator
    assert await frames.__anext__() == ": connected\n\n"

    async def next_payload():
        task = asyncio.ensure_future(frames.__anext__())
        await asyncio.sleep(0)
        return task

    pending = await next_payload()
    HistoryEvents.get_instance().publish(5)
    assert json.loads((await pending).removeprefix("data: ")) == {
        "type": "history_changed",
        "mine": True,
    }

    pending = await next_payload()
    HistoryEvents.get_instance().publish(6)
    assert json.loads((await pending).removeprefix("data: ")) == {
        "type": "history_changed",
        "mine": False,
    }
    await frames.aclose()


@pytest.mark.asyncio
async def test_a_live_play_is_announced_after_it_is_recorded(
    db, track, test_user, published
):
    await log_history(db, 300, "10.0.0.2", "client-1", test_user["id"])

    assert published == [test_user["id"]]
    visible = await db.fetchval(
        "SELECT COUNT(*) FROM combined_playback_history_mat WHERE track_id = 300"
    )
    assert visible == 1


@pytest.mark.asyncio
async def test_an_offline_upload_is_announced_only_when_it_records_plays(
    auth_client: AsyncClient, db, track, published
):
    played_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    batch = {"plays": [{"track_id": 300, "played_at": played_at, "ms_played": 60_000}]}

    await auth_client.post("/api/history/offline", json=batch)
    await auth_client.post("/api/history/offline", json=batch)  # duplicate: no news

    user_id = await db.fetchval('SELECT id FROM "user" WHERE username = $1', "testuser")
    assert published == [user_id]


@pytest.mark.asyncio
async def test_top_lists_break_play_count_ties_by_most_recent_play(
    auth_client: AsyncClient, db
):
    # Two artists, albums and tracks with equal play counts. The fallback
    # keys (mbid, album name, track id) favour the "older" one, so only the
    # recency tie-break puts the "newer" one first.
    older_mbid, newer_mbid = "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"
    await db.execute(
        "INSERT INTO artist (mbid, name) VALUES ($1, 'Older'), ($2, 'Newer')",
        older_mbid,
        newer_mbid,
    )
    await db.execute(
        """
        INSERT INTO track (id, title, artist, album_artist, album, duration_seconds, path) VALUES
            (401, 'Old Song', 'Older', 'Older', 'Alpha', 180, '/music/old.flac'),
            (402, 'New Song', 'Newer', 'Newer', 'Beta', 180, '/music/new.flac')
        """
    )
    await db.execute(
        "INSERT INTO track_artist (track_id, artist_mbid) VALUES (401, $1), (402, $2)",
        older_mbid,
        newer_mbid,
    )
    await db.execute(
        """
        INSERT INTO playback_history (track_id, timestamp, client_ip) VALUES
            (401, NOW() - INTERVAL '3 hours', '127.0.0.1'),
            (402, NOW() - INTERVAL '2 hours', '127.0.0.1'),
            (401, NOW() - INTERVAL '1 hour', '127.0.0.1'),
            (402, NOW() - INTERVAL '5 minutes', '127.0.0.1')
        """
    )
    await db.execute("REFRESH MATERIALIZED VIEW combined_playback_history_mat")

    stats = (await auth_client.get("/api/history/stats")).json()

    assert [a["artist"] for a in stats["artists"]] == ["Newer", "Older"]
    assert [a["album"] for a in stats["albums"]] == ["Beta", "Alpha"]
    assert [t["id"] for t in stats["tracks"]] == [402, 401]
    assert {a["plays"] for a in stats["artists"]} == {2}
