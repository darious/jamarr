"""The stored Last.fm scrobbles keep getting matched after Last.fm itself is gone."""

from datetime import datetime, timezone

import pytest

from app.lastfm_archive import match_all_archives, match_archive

PLAYED = datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)


async def _seed(db):
    await db.execute(
        """
        INSERT INTO "user" (username, email, password_hash, lastfm_username)
        VALUES ('archivist', 'a@example.com', 'x', 'lfm')
        """
    )
    await db.execute(
        """
        INSERT INTO artist (mbid, name) VALUES ('a74b1b7f-71a5-4011-9441-d0b5e4122711', 'Artist')
        """
    )
    track_id = await db.fetchval(
        """
        INSERT INTO track (path, title, artist, album, artist_mbid, duration_seconds)
        VALUES ('/m/a.flac', 'Song', 'Artist', 'Album', 'a74b1b7f-71a5-4011-9441-d0b5e4122711', 200)
        RETURNING id
        """
    )
    await db.execute(
        "INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, 'a74b1b7f-71a5-4011-9441-d0b5e4122711')",
        track_id,
    )
    ids = []
    for n in range(2):
        ids.append(
            await db.fetchval(
                """
                INSERT INTO lastfm_scrobble (lastfm_username, played_at, played_at_uts, track_name, artist_name, album_name)
                VALUES ('lfm', $1, $2, 'Song', 'Artist', 'Album') RETURNING id
                """,
                PLAYED.replace(hour=12 + n),
                int(PLAYED.timestamp()) + n * 3600,
            )
        )
    return track_id, ids


@pytest.mark.asyncio
async def test_unmatched_scrobbles_get_matched_and_rematch_all_redoes_them(db):
    track_id, ids = await _seed(db)
    matched, unmatched = await match_archive(db, "lfm")
    assert (matched, unmatched) == (2, 0)
    rows = await db.fetch("SELECT track_id FROM lastfm_scrobble_match ORDER BY scrobble_id")
    assert [r["track_id"] for r in rows] == [track_id, track_id]

    # Nothing left unmatched: a second pass does nothing.
    assert await match_archive(db, "lfm") == (0, 0)
    # A full rematch drops and redoes every match.
    assert await match_archive(db, "lfm", rematch_all=True) == (2, 0)


@pytest.mark.asyncio
async def test_daily_upkeep_covers_every_archive(db):
    await _seed(db)
    assert await match_all_archives(db) == (2, 0)
