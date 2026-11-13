"""match_and_store across batches, against the test DB (issue #366).

On prod, a full re-match credited 51 "Refuge" scrobbles that named the
original release to the Extended edition: Last.fm gives both the same track
MBID, the cache key is that MBID alone, and later batches copied whichever
edition's match came back first.
"""

import pytest

from app.matching.matcher import match_and_store

TRACK_MBID = "lastfm-refuge"  # Last.fm's id, unknown to the library


async def _setup(db):
    await db.execute(
        "INSERT INTO artist (mbid, name) VALUES ('dk', 'Dermot Kennedy') ON CONFLICT DO NOTHING"
    )
    ids = {}
    for key, album, release in (
        ("og", "The Weight of the Woods", "release-og"),
        ("ext", "The Weight of the Woods (Extended)", "release-ext"),
    ):
        ids[key] = await db.fetchval(
            """
            INSERT INTO track (path, title, artist, album, album_artist, artist_mbid,
                               release_mbid, release_type, updated_at)
            VALUES ($1, 'Refuge', 'Dermot Kennedy', $2, 'Dermot Kennedy', 'dk', $3, 'album', NOW())
            RETURNING id
            """,
            f"{key}/03 Refuge.flac", album, release,
        )
    await db.execute(
        "INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, 'dk'), ($2, 'dk')",
        ids["og"], ids["ext"],
    )
    return ids


async def _scrobble(db, minutes_ago, album, release):
    return await db.fetchval(
        """
        INSERT INTO lastfm_scrobble (lastfm_username, played_at, track_mbid, track_name,
                                     artist_name, album_mbid, album_name)
        VALUES ('tester', NOW() - make_interval(mins => $1), $2, 'Refuge',
                'Dermot Kennedy', $3, $4)
        RETURNING id
        """,
        minutes_ago, TRACK_MBID, release, album,
    )


async def _match_all(db, batch_size):
    scrobbles = await db.fetch(
        """
        SELECT id, lastfm_username, track_mbid, track_name, album_mbid, album_name,
               artist_mbid, artist_name
        FROM lastfm_scrobble ORDER BY played_at DESC, id DESC
        """
    )
    await match_and_store(db, scrobbles, batch_size=batch_size)
    rows = await db.fetch("SELECT scrobble_id, track_id FROM lastfm_scrobble_match")
    return {r["scrobble_id"]: r["track_id"] for r in rows}


async def _seed(db):
    ids = await _setup(db)
    # Newest first: an original play, an Extended play, then an older
    # original play that lands in the second batch.
    og_new = await _scrobble(db, 1, "The Weight of the Woods", "release-og")
    ext = await _scrobble(db, 2, "The Weight of the Woods (Extended)", "release-ext")
    og_old = await _scrobble(db, 3, "The Weight of the Woods", "release-og")
    return ids, og_new, ext, og_old


@pytest.mark.asyncio
async def test_first_batch_matches_each_edition(db):
    ids, og_new, ext, _ = await _seed(db)
    matches = await _match_all(db, batch_size=2)
    assert matches[og_new] == ids["og"]
    assert matches[ext] == ids["ext"]


@pytest.mark.asyncio
async def test_rematch_is_repeatable(db):
    await _seed(db)
    first = await _match_all(db, batch_size=2)
    await db.execute("DELETE FROM lastfm_scrobble_match")
    second = await _match_all(db, batch_size=2)
    assert first == second


@pytest.mark.asyncio
@pytest.mark.xfail(strict=True, reason="issue #366: the track-MBID cache key ignores the album")
async def test_later_batch_keeps_the_edition_its_scrobble_names(db):
    ids, _, _, og_old = await _seed(db)
    matches = await _match_all(db, batch_size=2)
    assert matches[og_old] == ids["og"]
