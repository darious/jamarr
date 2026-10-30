"""Queue entry identity and revisions over the API (#325, #332)."""

import pytest
from httpx import AsyncClient

from app.db import db_conn
from app.services.player.state import get_renderer_state_db

H = {"X-Jamarr-Client-Id": "rev-client"}
UDN = "local:rev-client"

A = {"id": 10, "title": "Song A", "artist": "Artist A", "path": "/music/t1.flac", "duration_seconds": 200, "album": "Album A"}
B = {"id": 11, "title": "Song B", "artist": "Artist A", "path": "/music/t2.flac", "duration_seconds": 200, "album": "Album A"}
C = {"id": 12, "title": "Song C", "artist": "Artist B", "path": "/music/t3.flac", "duration_seconds": 300, "album": "Album B"}


@pytest.fixture
async def tracks(db):
    await db.execute(
        """
        INSERT INTO track (id, path, title, artist, album, duration_seconds)
        VALUES
            (10, '/music/t1.flac', 'Song A', 'Artist A', 'Album A', 200),
            (11, '/music/t2.flac', 'Song B', 'Artist A', 'Album A', 200),
            (12, '/music/t3.flac', 'Song C', 'Artist B', 'Album B', 300)
        """
    )


async def state_of(client: AsyncClient) -> dict:
    resp = await client.get("/api/player/state", headers=H)
    assert resp.status_code == 200, resp.text
    return resp.json()


def ids(queue):
    return [t["id"] for t in queue]


def entries(queue):
    return [t["entry_id"] for t in queue]


# ---- #325 identity -------------------------------------------------------


@pytest.mark.asyncio
async def test_every_queued_item_gets_a_distinct_entry_id(auth_client, tracks):
    resp = await auth_client.post(
        "/api/player/queue", json={"queue": [A, B, A], "start_index": 2}, headers=H
    )
    assert resp.status_code == 200, resp.text
    queue = resp.json()["state"]["queue"]
    assert ids(queue) == [10, 11, 10]
    assert len(set(entries(queue))) == 3
    assert all(e for e in entries(queue))

    # The same ids come back from /state and survive an append.
    assert entries((await state_of(auth_client))["queue"]) == entries(queue)
    resp = await auth_client.post("/api/player/queue/append", json={"tracks": [C]}, headers=H)
    assert resp.status_code == 200
    after = resp.json()["state"]["queue"]
    assert entries(after)[:3] == entries(queue)
    assert after[3]["entry_id"] not in entries(queue)


@pytest.mark.asyncio
async def test_client_supplied_entry_ids_are_not_trusted_on_set(auth_client, tracks):
    forged = [dict(A, entry_id="x"), dict(B, entry_id="x")]
    resp = await auth_client.post("/api/player/queue", json={"queue": forged, "start_index": 0}, headers=H)
    queue = resp.json()["state"]["queue"]
    assert "x" not in entries(queue)
    assert len(set(entries(queue))) == 2


@pytest.mark.asyncio
async def test_reorder_follows_the_playing_duplicate(auth_client, tracks):
    # [A, B, A] with the final A playing; move that A to the front.
    resp = await auth_client.post("/api/player/queue", json={"queue": [A, B, A], "start_index": 2}, headers=H)
    queue = resp.json()["state"]["queue"]
    playing = queue[2]
    new_order = [queue[2], queue[0], queue[1]]

    resp = await auth_client.post("/api/player/queue/reorder", json={"queue": new_order}, headers=H)
    assert resp.status_code == 200, resp.text
    state = resp.json()["state"]
    assert entries(state["queue"]) == entries(new_order)
    assert state["current_index"] == 0
    assert state["queue"][0]["entry_id"] == playing["entry_id"]
    assert state["is_playing"] is True

    persisted = await state_of(auth_client)
    assert persisted["current_index"] == 0
    assert entries(persisted["queue"]) == entries(new_order)


@pytest.mark.asyncio
async def test_removing_one_duplicate_leaves_the_other_playing(auth_client, tracks):
    resp = await auth_client.post("/api/player/queue", json={"queue": [A, B, A], "start_index": 2}, headers=H)
    queue = resp.json()["state"]["queue"]

    # Drop the first A (not playing); the playing A must stay current.
    resp = await auth_client.post("/api/player/queue/reorder", json={"queue": [queue[1], queue[2]]}, headers=H)
    state = resp.json()["state"]
    assert entries(state["queue"]) == [queue[1]["entry_id"], queue[2]["entry_id"]]
    assert state["current_index"] == 1
    assert state["is_playing"] is True

    # Drop the playing A: nothing is current and the transport stops.
    resp = await auth_client.post("/api/player/queue/reorder", json={"queue": [queue[1]]}, headers=H)
    state = resp.json()["state"]
    assert ids(state["queue"]) == [11]
    assert state["current_index"] == -1
    assert state["is_playing"] is False
    assert state["transport_state"] == "STOPPED"


@pytest.mark.asyncio
async def test_legacy_reorder_without_entry_ids_still_works(auth_client, tracks):
    await auth_client.post("/api/player/queue", json={"queue": [A, B, C], "start_index": 1}, headers=H)
    before = entries((await state_of(auth_client))["queue"])

    # An older client sends track ids only, in a new order.
    resp = await auth_client.post("/api/player/queue/reorder", json={"queue": [C, A, B]}, headers=H)
    assert resp.status_code == 200, resp.text
    state = resp.json()["state"]
    assert ids(state["queue"]) == [12, 10, 11]
    assert state["current_index"] == 2
    # Identities travelled with the items rather than being reissued.
    assert set(entries(state["queue"])) == set(before)


@pytest.mark.asyncio
async def test_queue_persisted_before_entry_ids_reads_back_with_stable_ids(auth_client, tracks):
    import json

    # A row written by an older server: no entry ids, a duplicate track.
    async with db_conn() as conn:
        await conn.execute(
            """
            INSERT INTO renderer_state (renderer_udn, queue, current_index, is_playing, transport_state)
            VALUES ($1, $2, 2, TRUE, 'PLAYING')
            """,
            UDN,
            json.dumps([A, B, A]),
        )
    first = await state_of(auth_client)
    second = await state_of(auth_client)
    assert entries(first["queue"]) == entries(second["queue"])
    assert len(set(entries(first["queue"]))) == 3

    # They are addressable: reorder by them and the playing A follows.
    q = first["queue"]
    resp = await auth_client.post("/api/player/queue/reorder", json={"queue": [q[2], q[1], q[0]]}, headers=H)
    state = resp.json()["state"]
    assert state["current_index"] == 0
    assert entries(state["queue"]) == [q[2]["entry_id"], q[1]["entry_id"], q[0]["entry_id"]]


@pytest.mark.asyncio
async def test_history_flag_rides_with_the_entry_through_a_reorder(auth_client, tracks):
    resp = await auth_client.post("/api/player/queue", json={"queue": [A, B, A], "start_index": 2}, headers=H)
    queue = resp.json()["state"]["queue"]
    # Past the threshold: the playing occurrence is logged, the other A is not.
    await auth_client.post("/api/player/progress", json={"position_seconds": 60, "is_playing": True}, headers=H)
    state = await state_of(auth_client)
    assert [t.get("logged") for t in state["queue"]] == [False, False, True]

    await auth_client.post("/api/player/queue/reorder", json={"queue": [queue[2], queue[0], queue[1]]}, headers=H)
    state = await state_of(auth_client)
    assert [t.get("logged") for t in state["queue"]] == [True, False, False]
    async with db_conn() as conn:
        rows = await conn.fetch("SELECT track_id FROM playback_history")
    assert [r["track_id"] for r in rows] == [10]


# ---- #332 revisions ------------------------------------------------------


@pytest.mark.asyncio
async def test_revision_moves_on_content_changes_only(auth_client, tracks):
    assert (await state_of(auth_client))["queue_revision"] == 0

    r1 = (await auth_client.post("/api/player/queue", json={"queue": [A, B], "start_index": 0}, headers=H)).json()["state"]["queue_revision"]
    assert r1 >= 1
    r2 = (await auth_client.post("/api/player/queue/append", json={"tracks": [C]}, headers=H)).json()["state"]["queue_revision"]
    assert r2 == r1 + 1

    # Progress and skipping change nothing about the queue.
    await auth_client.post("/api/player/progress", json={"position_seconds": 5, "is_playing": True}, headers=H)
    await auth_client.post("/api/player/index", json={"index": 1}, headers=H)
    assert (await state_of(auth_client))["queue_revision"] == r2

    q = (await state_of(auth_client))["queue"]
    r3 = (await auth_client.post("/api/player/queue/reorder", json={"queue": [q[2], q[0], q[1]]}, headers=H)).json()["state"]["queue_revision"]
    assert r3 == r2 + 1
    # Same order again: no change, no new revision.
    q = (await state_of(auth_client))["queue"]
    r3b = (await auth_client.post("/api/player/queue/reorder", json={"queue": q}, headers=H)).json()["state"]["queue_revision"]
    assert r3b == r3

    r4 = (await auth_client.post("/api/player/queue/clear", headers=H)).json()["state"]["queue_revision"]
    assert r4 == r3 + 1


@pytest.mark.asyncio
async def test_stale_reorder_is_refused_with_the_live_state(auth_client, tracks):
    await auth_client.post("/api/player/queue", json={"queue": [A, B, C], "start_index": 0}, headers=H)
    stale = await state_of(auth_client)

    # Another client appends after our read.
    await auth_client.post("/api/player/queue/append", json={"tracks": [A]}, headers=H)

    q = stale["queue"]
    resp = await auth_client.post(
        "/api/player/queue/reorder",
        json={"queue": [q[2], q[1], q[0]], "expected_revision": stale["queue_revision"]},
        headers=H,
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "queue_conflict"
    assert detail["queue_revision"] == stale["queue_revision"] + 1
    assert ids(detail["state"]["queue"]) == [10, 11, 12, 10]
    assert detail["state"]["queue_revision"] == detail["queue_revision"]

    # Nothing was lost: the newer append is intact and the order untouched.
    live = await state_of(auth_client)
    assert ids(live["queue"]) == [10, 11, 12, 10]

    # Reapplied against the live revision, by entry id, it lands.
    lq = live["queue"]
    resp = await auth_client.post(
        "/api/player/queue/reorder",
        json={"queue": [lq[2], lq[1], lq[0], lq[3]], "expected_revision": live["queue_revision"]},
        headers=H,
    )
    assert resp.status_code == 200, resp.text
    assert ids(resp.json()["state"]["queue"]) == [12, 11, 10, 10]


@pytest.mark.asyncio
async def test_two_edits_from_one_read_only_the_first_wins(auth_client, tracks):
    await auth_client.post("/api/player/queue", json={"queue": [A, B, C], "start_index": 0}, headers=H)
    read = await state_of(auth_client)
    q, rev = read["queue"], read["queue_revision"]

    first = await auth_client.post("/api/player/queue/reorder", json={"queue": [q[1], q[0], q[2]], "expected_revision": rev}, headers=H)
    second = await auth_client.post("/api/player/queue/reorder", json={"queue": [q[2], q[1], q[0]], "expected_revision": rev}, headers=H)
    assert first.status_code == 200
    assert second.status_code == 409
    assert ids((await state_of(auth_client))["queue"]) == [11, 10, 12]


@pytest.mark.asyncio
async def test_append_set_and_clear_honour_expected_revision(auth_client, tracks):
    await auth_client.post("/api/player/queue", json={"queue": [A], "start_index": 0}, headers=H)
    rev = (await state_of(auth_client))["queue_revision"]

    ok = await auth_client.post("/api/player/queue/append", json={"tracks": [B], "expected_revision": rev}, headers=H)
    assert ok.status_code == 200
    stale = await auth_client.post("/api/player/queue/append", json={"tracks": [C], "expected_revision": rev}, headers=H)
    assert stale.status_code == 409
    assert ids((await state_of(auth_client))["queue"]) == [10, 11]

    stale = await auth_client.post("/api/player/queue/clear", json={"expected_revision": rev}, headers=H)
    assert stale.status_code == 409
    stale = await auth_client.post("/api/player/queue", json={"queue": [C], "start_index": 0, "expected_revision": rev}, headers=H)
    assert stale.status_code == 409
    assert ids((await state_of(auth_client))["queue"]) == [10, 11]

    live = (await state_of(auth_client))["queue_revision"]
    assert (await auth_client.post("/api/player/queue/clear", json={"expected_revision": live}, headers=H)).status_code == 200
    assert (await state_of(auth_client))["queue"] == []


@pytest.mark.asyncio
async def test_edits_without_a_revision_still_apply(auth_client, tracks):
    # Older clients send no expected_revision: last writer wins, as before.
    await auth_client.post("/api/player/queue", json={"queue": [A, B], "start_index": 0}, headers=H)
    await auth_client.post("/api/player/queue/append", json={"tracks": [C]}, headers=H)
    resp = await auth_client.post("/api/player/queue/reorder", json={"queue": [C, B, A]}, headers=H)
    assert resp.status_code == 200
    assert ids(resp.json()["state"]["queue"]) == [12, 11, 10]


@pytest.mark.asyncio
async def test_progress_does_not_put_back_a_stale_queue(auth_client, tracks, monkeypatch):
    """A progress report that logs history used to write the whole row back
    from its own read; an edit landing between the read and the write was
    undone. The logged flag now goes to the one entry, conditionally."""
    import app.api.player as player_api

    await auth_client.post("/api/player/queue", json={"queue": [A, B], "start_index": 0}, headers=H)
    before = await state_of(auth_client)

    real_log = player_api.log_history

    async def log_and_race(db, track_id, **kw):
        # While this request is logging, another client appends a track.
        async with db_conn() as other:
            st = await get_renderer_state_db(other, UDN)
            st["queue"] = st["queue"] + [dict(C, entry_id="late")]
            from app.services.player.state import update_renderer_state_db
            await update_renderer_state_db(other, UDN, st)
        return await real_log(db, track_id, **kw)

    monkeypatch.setattr(player_api, "log_history", log_and_race)
    resp = await auth_client.post("/api/player/progress", json={"position_seconds": 90, "is_playing": True}, headers=H)
    assert resp.status_code == 200

    after = await state_of(auth_client)
    assert ids(after["queue"]) == [10, 11, 12], "the concurrent append was lost"
    assert after["queue"][0]["logged"] is True
    assert after["queue_revision"] == before["queue_revision"] + 1
    assert after["position_seconds"] == 90


@pytest.mark.asyncio
async def test_revision_is_persisted(auth_client, tracks):
    await auth_client.post("/api/player/queue", json={"queue": [A, B], "start_index": 0}, headers=H)
    await auth_client.post("/api/player/queue/append", json={"tracks": [C]}, headers=H)
    shown = (await state_of(auth_client))["queue_revision"]
    async with db_conn() as conn:
        stored = await conn.fetchval("SELECT queue_revision FROM renderer_state WHERE renderer_udn = $1", UDN)
        state = await get_renderer_state_db(conn, UDN)
    assert stored == shown == state["queue_revision"]
    assert all(t.get("entry_id") for t in state["queue"])
