"""match_and_store across batches, against the test DB (issue #366).

On prod, a full re-match credited 51 "Refuge" scrobbles that named the
original release to the Extended edition: Last.fm gives both the same track
MBID, the cache key was that MBID alone, and later batches copied whichever
edition's match came back first. The key now holds the album too.
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


async def _match_all(db, batch_size, fuzzy=True):
    scrobbles = await db.fetch(
        """
        SELECT id, lastfm_username, track_mbid, track_name, album_mbid, album_name,
               artist_mbid, artist_name
        FROM lastfm_scrobble ORDER BY played_at DESC, id DESC
        """
    )
    await match_and_store(db, scrobbles, batch_size=batch_size, fuzzy=fuzzy)
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
async def test_later_batch_keeps_the_edition_its_scrobble_names(db):
    ids, _, _, og_old = await _seed(db)
    matches = await _match_all(db, batch_size=2)
    assert matches[og_old] == ids["og"]


@pytest.mark.asyncio
async def test_labelled_version_does_not_reuse_the_plain_match(db):
    # Same album, same artist, no MBID: before, normalize_title made
    # "Refuge" and "Refuge (Acoustic)" share a key.
    ids = await _setup(db)
    acoustic = await db.fetchval(
        """
        INSERT INTO track (path, title, artist, album, album_artist, artist_mbid,
                           release_mbid, release_type, updated_at)
        VALUES ('og/13 Refuge (Acoustic).flac', 'Refuge (Acoustic)', 'Dermot Kennedy',
                'The Weight of the Woods', 'Dermot Kennedy', 'dk', 'release-og', 'album', NOW())
        RETURNING id
        """
    )
    await db.execute("INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, 'dk')", acoustic)
    plain = await _scrobble(db, 1, "The Weight of the Woods", "release-og")
    labelled = await db.fetchval(
        """
        INSERT INTO lastfm_scrobble (lastfm_username, played_at, track_name, artist_name,
                                     album_mbid, album_name)
        VALUES ('tester', NOW() - make_interval(mins => 5), 'Refuge (Acoustic)',
                'Dermot Kennedy', 'release-og', 'The Weight of the Woods')
        RETURNING id
        """
    )
    matches = await _match_all(db, batch_size=1)
    assert matches[plain] == ids["og"]
    assert matches[labelled] == acoustic


async def _artist_track(db, artist_mbid, artist, title, album):
    await db.execute(
        "INSERT INTO artist (mbid, name) VALUES ($1, $2) ON CONFLICT DO NOTHING", artist_mbid, artist
    )
    track_id = await db.fetchval(
        """
        INSERT INTO track (path, title, artist, album, album_artist, artist_mbid, release_type, updated_at)
        VALUES ($1, $2, $3, $4, $3, $5, 'album', NOW())
        RETURNING id
        """,
        f"{artist}/{title}.flac", title, artist, album, artist_mbid,
    )
    await db.execute("INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, $2)", track_id, artist_mbid)
    return track_id


async def _named_scrobble(db, minutes_ago, artist, title, album=None, track_mbid=None):
    return await db.fetchval(
        """
        INSERT INTO lastfm_scrobble (lastfm_username, played_at, track_mbid, track_name,
                                     artist_name, album_name)
        VALUES ('tester', NOW() - make_interval(mins => $1), $2, $3, $4, $5)
        RETURNING id
        """,
        minutes_ago, track_mbid, title, artist, album,
    )


@pytest.mark.asyncio
async def test_unmatched_scrobble_takes_the_track_its_mbid_shares(db):
    # Last.fm spells the artist two ways; only one reaches the library, and
    # the other borrows its match through the shared track MBID. Fuzzy is
    # off: in a one-track library the title-only fallback would find it.
    # The album differs so the cache key does too.
    track_id = await _artist_track(db, "tstm", "Thirty Seconds to Mars", "Kings and Queens", "This Is War")
    spelled_out = await _named_scrobble(db, 1, "Thirty Seconds to Mars", "Kings and Queens", track_mbid="kq")
    digits = await _named_scrobble(
        db, 2, "30 Seconds to Mars", "Kings and Queens", album="Live in Paris", track_mbid="kq"
    )
    no_mbid = await _named_scrobble(db, 3, "30 Seconds to Mars", "Kings and Queens")
    matches = await _match_all(db, batch_size=1, fuzzy=False)
    assert matches[spelled_out] == track_id
    assert matches[digits] == track_id
    assert no_mbid not in matches
    method = await db.fetchval(
        "SELECT match_method FROM lastfm_scrobble_match WHERE scrobble_id = $1", digits
    )
    assert method == "track_mbid_shared"


@pytest.mark.asyncio
async def test_shared_mbid_never_overrides_a_match(db):
    # Both editions carry one track MBID; the Extended play still matches
    # its own edition rather than the more common original.
    ids = await _setup(db)
    for minutes in (1, 2, 3):
        await _scrobble(db, minutes, "The Weight of the Woods", "release-og")
    ext = await _scrobble(db, 4, "The Weight of the Woods (Extended)", "release-ext")
    matches = await _match_all(db, batch_size=10)
    assert matches[ext] == ids["ext"]
