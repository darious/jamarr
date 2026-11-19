"""Last.fm -> ListenBrainz reload: duplicate rule, MBID confidence policy, cutover, sending."""

import argparse
from datetime import datetime, timedelta, timezone

import pytest

from app import listenbrainz as lb
from app.listenbrainz_import import (
    Plan,
    build_import_listen,
    build_plan,
    drop_duplicates,
    run,
    send,
)

RECORDING = "8f3471b5-7e6a-48da-86a9-c1c07a0f47ae"
RELEASE = "1dc4c347-a1db-32aa-b14f-bc9cc507b843"
ARTIST = "a74b1b7f-71a5-4011-9441-d0b5e4122711"
T0 = datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)


def row(id_, offset_s, *, track_id=1, duration=240, jamarr=False, method="name_artist_album",
        artist="Artist", title="Song", album="Album", track_album="Album"):
    played = T0 + timedelta(seconds=offset_s)
    return {
        "id": id_,
        "played_at": played,
        "played_at_uts": int(played.timestamp()),
        "artist_name": artist,
        "track_name": title,
        "album_name": album,
        "track_id": track_id,
        "match_method": method if track_id else None,
        "match_score": 1.0,
        "track_album": track_album,
        "duration_seconds": duration if track_id else None,
        "artist_mbid": ARTIST,
        "track_mbid": RECORDING,
        "release_mbid": RELEASE,
        "release_group_mbid": None,
        "release_track_mbid": None,
        "jamarr_play": jamarr,
    }


# --------------------------------------------------------------------------
# Duplicates
# --------------------------------------------------------------------------


def test_scrobbles_closer_than_half_the_track_are_one_listen():
    kept, dropped = drop_duplicates([row(1, 0), row(2, 60), row(3, 125)])
    # 240 s track: the window is 120 s. #2 is 60 s after #1 (duplicate);
    # #3 is 125 s after #1, the last kept one (a real replay).
    assert [r["id"] for r in kept] == [1, 3]
    assert [(d["id"], k["id"]) for d, k in dropped] == [(2, 1)]


def test_window_caps_at_four_minutes():
    kept, _ = drop_duplicates([row(1, 0, duration=1200), row(2, 239, duration=1200), row(3, 480, duration=1200)])
    assert [r["id"] for r in kept] == [1, 3]


def test_later_scrobble_kept_when_it_is_jamarrs_own():
    kept, dropped = drop_duplicates([row(1, 0), row(2, 20, jamarr=True)])
    assert [r["id"] for r in kept] == [2]
    assert [(d["id"], k["id"]) for d, k in dropped] == [(1, 2)]


def test_report_names_the_row_that_finally_stayed():
    # #2 duplicates #1; then #3 (Jamarr's own) replaces #1.
    kept, dropped = drop_duplicates([row(1, 0), row(2, 10), row(3, 20, jamarr=True)])
    assert [r["id"] for r in kept] == [3]
    assert sorted((d["id"], k["id"]) for d, k in dropped) == [(1, 3), (2, 3)]


def test_different_tracks_never_collide():
    kept, dropped = drop_duplicates([row(1, 0, track_id=1), row(2, 5, track_id=2)])
    assert len(kept) == 2 and dropped == []


def test_unmatched_duplicates_use_names_and_a_short_window():
    rows = [
        row(1, 0, track_id=None, artist="Prodıgy", title="Firestarter"),
        row(2, 10, track_id=None, artist="prodıgy", title="FIRESTARTER"),
        row(3, 45, track_id=None, artist="Prodıgy", title="Firestarter"),
    ]
    kept, dropped = drop_duplicates(rows)
    assert [r["id"] for r in kept] == [1, 3]
    assert len(dropped) == 1


# --------------------------------------------------------------------------
# MBID policy
# --------------------------------------------------------------------------


def test_album_match_sends_recording_and_release():
    info = build_import_listen(row(1, 0))["track_metadata"]["additional_info"]
    assert info["recording_mbid"] == RECORDING
    assert info["release_mbid"] == RELEASE
    assert info["artist_mbids"] == [ARTIST]


def test_track_mbid_match_sends_release_only_when_album_agrees():
    other_album = build_import_listen(row(1, 0, method="mbid_track", album="Greatest Hits"))
    info = other_album["track_metadata"]["additional_info"]
    assert info["recording_mbid"] == RECORDING
    assert "release_mbid" not in info
    assert other_album["track_metadata"]["release_name"] == "Greatest Hits"

    same_album = build_import_listen(row(1, 0, method="mbid_track", album="album"))
    assert same_album["track_metadata"]["additional_info"]["release_mbid"] == RELEASE


@pytest.mark.parametrize("method", ["name_artist_title", "fuzzy_title"])
def test_weaker_matches_go_by_name_only(method):
    listen = build_import_listen(row(1, 0, method=method))
    info = listen["track_metadata"]["additional_info"]
    assert not {"recording_mbid", "release_mbid", "artist_mbids"} & info.keys()
    assert listen["track_metadata"]["track_name"] == "Song"


def test_unmatched_goes_by_name_and_empty_names_are_skipped():
    listen = build_import_listen(row(1, 0, track_id=None))
    assert "recording_mbid" not in listen["track_metadata"]["additional_info"]
    assert build_import_listen(row(2, 0, track_id=None, title=" ")) is None


def test_plan_counts():
    plan = build_plan([row(1, 0), row(2, 30), row(3, 600, track_id=None, title="")])
    assert len(plan.listens) == 1
    assert len(plan.duplicates) == 1
    assert len(plan.skipped_empty) == 1
    assert plan.with_recording == 1 and plan.with_release == 1


# --------------------------------------------------------------------------
# Sending
# --------------------------------------------------------------------------


class FakeClient:
    def __init__(self, fail=None):
        self.batches = []
        self.fail = fail

    async def submit_listens(self, token, listen_type, listens):
        if self.fail:
            exc = self.fail(listens)
            if exc:
                raise exc
        self.batches.append((listen_type, [item["listened_at"] for item in listens]))


def _plan(n):
    plan = Plan()
    for i in range(n):
        plan.listens.append({"listened_at": 1000 + i, "track_metadata": {"artist_name": "A", "track_name": f"T{i}"}})
    return plan


async def _no_sleep(_):
    return None


@pytest.mark.asyncio
async def test_send_batches_resumes_and_isolates_refused_listen(monkeypatch):
    monkeypatch.setattr("app.listenbrainz_import.BATCH_SIZE", 4)
    client = FakeClient(
        fail=lambda listens: lb.ListenBrainzRejectedError("bad")
        if any(item["listened_at"] == 1005 for item in listens) else None
    )
    out = []
    sent, rejected = await send(client, "tok", _plan(10), after=1001, sleep=_no_sleep, out=out.append)
    assert [item["listened_at"] for item in rejected] == [1005]
    assert sent == 7  # 1002..1009 minus the refused one
    # First batch 1002..1005 is refused and bisected down to the bad listen.
    assert client.batches[:2] == [("import", [1002, 1003]), ("single", [1004])]


@pytest.mark.asyncio
async def test_batches_never_split_a_second(monkeypatch):
    monkeypatch.setattr("app.listenbrainz_import.BATCH_SIZE", 2)
    plan = Plan()
    for i, ts in enumerate([1, 2, 2, 2, 3]):
        plan.listens.append({"listened_at": ts, "track_metadata": {"artist_name": "A", "track_name": f"T{i}"}})
    client = FakeClient()
    await send(client, "tok", plan, sleep=_no_sleep, out=lambda *_: None)
    assert [stamps for _, stamps in client.batches] == [[1, 2, 2, 2], [3]]


@pytest.mark.asyncio
async def test_send_retries_when_listenbrainz_is_down():
    calls = {"n": 0}

    def fail(listens):
        calls["n"] += 1
        return lb.ListenBrainzUnavailableError("502") if calls["n"] < 3 else None

    client = FakeClient(fail=fail)
    sent, rejected = await send(client, "tok", _plan(2), sleep=_no_sleep, out=lambda *_: None)
    assert (sent, rejected) == (2, [])


@pytest.mark.asyncio
async def test_send_stops_with_resume_hint_on_bad_token():
    client = FakeClient(fail=lambda listens: lb.ListenBrainzAuthError("Invalid token"))
    out = []
    with pytest.raises(lb.ListenBrainzAuthError):
        await send(client, "tok", _plan(3), after=500, sleep=_no_sleep, out=out.append)
    assert out[-1] == "Stopped. Resume with --after 500"


# --------------------------------------------------------------------------
# End to end against the DB
# --------------------------------------------------------------------------


async def _seed(db):
    user_id = await db.fetchval(
        """
        INSERT INTO "user" (username, email, password_hash, lastfm_username,
                            listenbrainz_token, listenbrainz_username)
        VALUES ('importer', 'importer@example.com', 'x', 'lfm', 'tok', 'lbname') RETURNING id
        """
    )
    track_id = await db.fetchval(
        """
        INSERT INTO track (path, title, artist, album, duration_seconds, track_mbid, release_mbid, artist_mbid)
        VALUES ('/m/1.flac', 'Song', 'Artist', 'Album', 240, $1, $2, $3) RETURNING id
        """,
        RECORDING, RELEASE, ARTIST,
    )
    scrobbles = [
        (T0, "Song", "Album"),
        (T0 + timedelta(seconds=40), "Song", "Album"),          # duplicate
        (T0 + timedelta(hours=1), "Unknown Track", None),       # unmatched
        (T0 + timedelta(days=400), "Song", "Album"),            # after the cutover
    ]
    for played, title, album in scrobbles:
        sid = await db.fetchval(
            """
            INSERT INTO lastfm_scrobble (lastfm_username, played_at, played_at_uts, track_name, artist_name, album_name)
            VALUES ('lfm', $1, $2, $3, 'Artist', $4) RETURNING id
            """,
            played, int(played.timestamp()), title, album,
        )
        if title == "Song":
            await db.execute(
                """
                INSERT INTO lastfm_scrobble_match (scrobble_id, track_id, match_score, match_method)
                VALUES ($1, $2, 1.0, 'name_artist_album')
                """,
                sid, track_id,
            )
    return user_id


def _args(**kw):
    base = {"user": "importer", "cutover": None, "dry_run": False, "report": None, "after": 0}
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.mark.asyncio
async def test_dry_run_reports_and_sends_nothing(db, tmp_path):
    await _seed(db)
    client = FakeClient()
    out = []
    cutover = (T0 + timedelta(days=30)).isoformat()
    code = await run(_args(dry_run=True, cutover=cutover, report=str(tmp_path)), db, client, out.append)
    assert code == 0
    assert client.batches == []
    text = "\n".join(out)
    assert "scrobbles before" in text and ": 3" in text
    assert "duplicates dropped: 1" in text
    assert "to send: 2" in text
    assert (tmp_path / "duplicates.csv").read_text().count("\n") == 2
    # A dry run never moves the cutover.
    assert await db.fetchval("SELECT listenbrainz_cutover FROM \"user\" WHERE username = 'importer'") is None


@pytest.mark.asyncio
async def test_run_sets_cutover_and_sends_only_before_it(db):
    await _seed(db)
    client = FakeClient()
    cutover = T0 + timedelta(days=30)
    code = await run(_args(cutover=cutover.isoformat()), db, client, lambda *_: None)
    assert code == 0
    assert client.batches == [("import", [int(T0.timestamp()), int((T0 + timedelta(hours=1)).timestamp())])]
    row = await db.fetchrow(
        "SELECT listenbrainz_cutover, listenbrainz_since FROM \"user\" WHERE username = 'importer'"
    )
    assert row["listenbrainz_cutover"] == cutover
    assert row["listenbrainz_since"] == cutover


@pytest.mark.asyncio
async def test_run_refuses_without_cutover_or_connection(db):
    await _seed(db)
    out = []
    assert await run(_args(), db, FakeClient(), out.append) == 2
    assert "cutover" in out[-1].lower()
    await db.execute("UPDATE \"user\" SET listenbrainz_token = NULL WHERE username = 'importer'")
    assert await run(_args(cutover=T0.isoformat()), db, FakeClient(), out.append) == 2
    assert "Connect ListenBrainz" in out[-1]
    # A dry run needs no connection.
    assert await run(_args(cutover=T0.isoformat(), dry_run=True), db, FakeClient(), out.append) == 0
