"""Reading listens back from ListenBrainz, and the history view's cutover."""

from datetime import datetime, timedelta, timezone

import pytest

from app import listenbrainz as lb
from app.listenbrainz_sync import fetch_listens_since, parse_listen, sync_user

RECORDING = "8f3471b5-7e6a-48da-86a9-c1c07a0f47ae"
OTHER_RECORDING = "11111111-2222-4333-8444-555555555555"
ARTIST = "a74b1b7f-71a5-4011-9441-d0b5e4122711"
CUTOVER = datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)
CUT = int(CUTOVER.timestamp())


def listen(ts, *, title="Song", artist="Artist", client="Pano Scrobbler", recording=None, mapping=None):
    info = {"submission_client": client}
    if recording:
        info["recording_mbid"] = recording
    md = {"artist_name": artist, "track_name": title, "release_name": "Album", "additional_info": info}
    if mapping:
        md["mbid_mapping"] = mapping
    return {"listened_at": ts, "recording_msid": f"msid-{ts}", "track_metadata": md}


class FakeReader:
    """Serves listens newest-first with ListenBrainz's exclusive max_ts paging."""

    def __init__(self, listens):
        self.listens = sorted(listens, key=lambda item: -item["listened_at"])
        self.calls = []

    async def get_listens(self, username, *, max_ts=None, count=1000, token=None):
        self.calls.append(max_ts)
        rows = [item for item in self.listens if max_ts is None or item["listened_at"] < max_ts]
        return rows[:count]


# --------------------------------------------------------------------------
# Parsing and paging
# --------------------------------------------------------------------------


def test_parse_matches_on_submitted_mbids_only():
    item = listen(1, recording=RECORDING, mapping={"recording_mbid": OTHER_RECORDING, "release_mbid": OTHER_RECORDING})
    item["track_metadata"]["additional_info"]["artist_mbids"] = [ARTIST, "junk"]
    parsed = parse_listen(item)
    assert parsed["recording_mbid"] == RECORDING
    assert parsed["artist_mbids"] == [ARTIST]
    # ListenBrainz's mapping is kept for reference but never matched on: its
    # release is the canonical one, not the edition played (#366).
    mapped_only = parse_listen(listen(1, mapping={"recording_mbid": OTHER_RECORDING, "release_mbid": OTHER_RECORDING}))
    assert mapped_only["recording_mbid"] is None
    assert mapped_only["release_mbid"] is None
    assert mapped_only["mapped_recording_mbid"] == OTHER_RECORDING
    as_string = listen(1)
    as_string["track_metadata"]["additional_info"]["artist_mbids"] = f"{ARTIST}; junk"
    assert parse_listen(as_string)["artist_mbids"] == [ARTIST]
    assert parse_listen(listen(1, title=" ")) is None
    assert parse_listen({"track_metadata": {"artist_name": "A", "track_name": "T"}}) is None


@pytest.mark.asyncio
async def test_paging_stops_at_lower_bound_and_keeps_boundary_second(monkeypatch):
    monkeypatch.setattr("app.listenbrainz_sync.PAGE_SIZE", 3)
    # Two listens share second 105 across a page boundary.
    stamps = [110, 108, 105, 105, 103, 101, 99, 90]
    reader = FakeReader([listen(ts, title=f"T{i}") for i, ts in enumerate(stamps)])
    got = await fetch_listens_since(reader, "someone", lower_uts=100)
    titles = {item["track_metadata"]["track_name"] for item in got}
    assert titles == {"T0", "T1", "T2", "T3", "T4", "T5"}
    assert all(item["listened_at"] >= 100 for item in got)
    assert reader.calls == [None, 106, 104]


@pytest.mark.asyncio
async def test_short_page_is_not_taken_as_the_end():
    class ShortPages(FakeReader):
        async def get_listens(self, username, *, max_ts=None, count=1000, token=None):
            return (await super().get_listens(username, max_ts=max_ts, count=count))[:2]

    reader = ShortPages([listen(ts, title=f"T{ts}") for ts in (130, 120, 110, 100, 90)])
    got = await fetch_listens_since(reader, "someone", lower_uts=95)
    assert sorted(item["listened_at"] for item in got) == [100, 110, 120, 130]


# --------------------------------------------------------------------------
# Sync against the DB
# --------------------------------------------------------------------------


async def _setup(db, *, since=CUTOVER):
    user_id = await db.fetchval(
        """
        INSERT INTO "user" (username, email, password_hash, lastfm_username,
                            listenbrainz_username, listenbrainz_token, listenbrainz_since,
                            listenbrainz_cutover)
        VALUES ('syncer', 'syncer@example.com', 'x', 'lfm', 'lbname', 'tok', $1, $1) RETURNING id
        """,
        since,
    )
    track_id = await db.fetchval(
        """
        INSERT INTO track (path, title, artist, album, duration_seconds, track_mbid, artist_mbid)
        VALUES ('/m/s.flac', 'Song', 'Artist', 'Album', 240, $1, $2) RETURNING id
        """,
        RECORDING,
        ARTIST,
    )
    return user_id, track_id


async def _history(db, user_id):
    rows = await db.fetch(
        "SELECT source, track_id, played_at FROM combined_playback_history WHERE user_id = $1 ORDER BY played_at",
        user_id,
    )
    return [(r["source"], int(r["played_at"].timestamp())) for r in rows]


@pytest.mark.asyncio
async def test_sync_stores_matches_and_skips_own_and_pre_cutover(db):
    user_id, track_id = await _setup(db)
    reader = FakeReader(
        [
            listen(CUT + 600, recording=RECORDING),                      # Pano, after cutover
            listen(CUT + 300, client=lb.SUBMISSION_CLIENT, recording=RECORDING),  # Jamarr's own
            listen(CUT + 100, title="Not In Library", artist="Nobody"),  # unmatched
            listen(CUT - 100, recording=RECORDING),                      # imported history
        ]
    )
    stats = await sync_user(user_id, client=reader)
    assert stats == {"fetched": 3, "new": 2, "own_skipped": 1, "matched": 1, "unmatched": 1}

    match = await db.fetchrow(
        "SELECT m.track_id, m.match_method FROM listenbrainz_listen_match m"
        " JOIN listenbrainz_listen l ON l.id = m.listen_id WHERE l.listened_at_uts = $1",
        CUT + 600,
    )
    assert match["track_id"] == track_id
    assert match["match_method"] == "mbid_track"
    assert await db.fetchval('SELECT listenbrainz_synced_at FROM "user" WHERE id = $1', user_id) is not None
    assert await _history(db, user_id) == [("listenbrainz", CUT + 600)]

    # A second sync stores nothing twice.
    again = await sync_user(user_id, client=reader)
    assert again["new"] == 0
    assert await db.fetchval("SELECT COUNT(*) FROM listenbrainz_listen") == 2


@pytest.mark.asyncio
async def test_high_water_mark_advances_on_own_listens_too(db):
    user_id, _ = await _setup(db)
    reader = FakeReader([listen(CUT + 86400 * 30, client=lb.SUBMISSION_CLIENT)])
    stats = await sync_user(user_id, client=reader)
    assert (stats["new"], stats["own_skipped"]) == (0, 1)
    through = await db.fetchval('SELECT listenbrainz_synced_through FROM "user" WHERE id = $1', user_id)
    assert through == CUT + 86400 * 30


@pytest.mark.asyncio
async def test_disconnect_keeps_listenbrainz_history(auth_client, db):
    await db.execute(
        """UPDATE "user" SET listenbrainz_username = 'lbname', listenbrainz_token = 'tok',
           listenbrainz_since = $1, listenbrainz_cutover = $1 WHERE username = 'testuser'""",
        CUTOVER,
    )
    assert (await auth_client.post("/api/listenbrainz/disconnect")).status_code == 200
    cutover = await db.fetchval("SELECT listenbrainz_cutover FROM \"user\" WHERE username = 'testuser'")
    assert cutover == CUTOVER


@pytest.mark.asyncio
async def test_sync_skips_unconnected_user(db):
    user_id, _ = await _setup(db, since=None)
    reader = FakeReader([listen(CUT + 1)])
    assert "skipped" in await sync_user(user_id, client=reader)
    assert reader.calls == []


@pytest.mark.asyncio
async def test_late_upload_within_lookback_is_still_picked_up(db):
    user_id, _ = await _setup(db)
    reader = FakeReader([listen(CUT + 86400 * 5, recording=RECORDING)])
    await sync_user(user_id, client=reader)
    # A phone uploads a listen from two days before the newest one.
    reader.listens.append(listen(CUT + 86400 * 3, title="Late", recording=RECORDING))
    reader.listens.sort(key=lambda item: -item["listened_at"])
    assert (await sync_user(user_id, client=reader))["new"] == 1


# --------------------------------------------------------------------------
# History view
# --------------------------------------------------------------------------


async def _scrobble(db, track_id, played_at):
    sid = await db.fetchval(
        """
        INSERT INTO lastfm_scrobble (lastfm_username, played_at, played_at_uts, track_name, artist_name)
        VALUES ('lfm', $1, $2, 'Song', 'Artist') RETURNING id
        """,
        played_at,
        int(played_at.timestamp()),
    )
    await db.execute(
        "INSERT INTO lastfm_scrobble_match (scrobble_id, track_id, match_score, match_method)"
        " VALUES ($1, $2, 1.0, 'name_artist_title')",
        sid,
        track_id,
    )


@pytest.mark.asyncio
async def test_lastfm_rows_stop_at_the_cutover(db):
    user_id, track_id = await _setup(db)
    await _scrobble(db, track_id, CUTOVER - timedelta(hours=1))
    await _scrobble(db, track_id, CUTOVER + timedelta(hours=1))
    assert await _history(db, user_id) == [("lastfm", CUT - 3600)]

    await db.execute('UPDATE "user" SET listenbrainz_cutover = NULL WHERE id = $1', user_id)
    assert [src for src, _ in await _history(db, user_id)] == ["lastfm", "lastfm"]


@pytest.mark.asyncio
async def test_external_row_within_a_minute_of_a_local_play_is_that_play(db):
    user_id, track_id = await _setup(db)
    local_at = CUTOVER - timedelta(hours=2)
    await db.execute(
        'INSERT INTO playback_history (track_id, user_id, "timestamp") VALUES ($1, $2, $3)',
        track_id,
        user_id,
        local_at,
    )
    await _scrobble(db, track_id, local_at + timedelta(seconds=40))   # same play, drifted
    await _scrobble(db, track_id, local_at + timedelta(minutes=10))   # a real replay
    assert await _history(db, user_id) == [
        ("local", int(local_at.timestamp())),
        ("lastfm", int(local_at.timestamp()) + 600),
    ]


# --------------------------------------------------------------------------
# Endpoint
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_endpoint_requires_connection(auth_client):
    response = await auth_client.post("/api/listenbrainz/sync")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_sync_endpoint_runs_sync(auth_client, db):
    await db.execute(
        """UPDATE "user" SET listenbrainz_username = 'lbname', listenbrainz_token = 'tok',
           listenbrainz_since = $1, listenbrainz_cutover = $1 WHERE username = 'testuser'""",
        CUTOVER,
    )
    lb.set_client(FakeReader([listen(CUT + 10, title="Elsewhere", artist="Someone")]))
    try:
        response = await auth_client.post("/api/listenbrainz/sync")
    finally:
        lb.set_client(None)
    assert response.status_code == 200, response.text
    assert response.json()["new"] == 1
    status = (await auth_client.get("/api/listenbrainz/status")).json()
    assert status["synced_at"] is not None
