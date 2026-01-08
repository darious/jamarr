import pytest


@pytest.mark.asyncio
async def test_scan_rematch_clears_matches_without_rematch(db):
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS lastfm_scrobble (
            id BIGSERIAL PRIMARY KEY,
            lastfm_username TEXT NOT NULL,
            played_at TIMESTAMPTZ NOT NULL,
            played_at_uts BIGINT,
            track_mbid TEXT,
            track_name TEXT NOT NULL,
            track_url TEXT,
            artist_mbid TEXT,
            artist_name TEXT NOT NULL,
            artist_url TEXT,
            album_mbid TEXT,
            album_name TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS lastfm_scrobble_match (
            id BIGSERIAL PRIMARY KEY,
            scrobble_id BIGINT NOT NULL UNIQUE,
            track_id BIGINT NOT NULL,
            match_score DOUBLE PRECISION NOT NULL,
            match_method TEXT NOT NULL,
            match_reason TEXT,
            cache_key TEXT,
            matched_at TIMESTAMPTZ DEFAULT NOW(),
            FOREIGN KEY(scrobble_id) REFERENCES lastfm_scrobble(id) ON DELETE CASCADE,
            FOREIGN KEY(track_id) REFERENCES track(id) ON DELETE CASCADE
        );
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS lastfm_skip_artist (
            id BIGSERIAL PRIMARY KEY,
            artist_name TEXT NOT NULL UNIQUE
        );
        """
    )
    await db.execute(
        """
        INSERT INTO artist (mbid, name) VALUES ('artist-1', 'Test Artist')
        """
    )
    track_id = await db.fetchval(
        """
        INSERT INTO track (path, title, artist, album, artist_mbid, updated_at)
        VALUES ('music/test.flac', 'My Song', 'Test Artist', 'My Album', 'artist-1', NOW())
        RETURNING id
        """
    )
    await db.execute(
        """
        INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, 'artist-1')
        """,
        track_id,
    )
    scrobble_id = await db.fetchval(
        """
        INSERT INTO lastfm_scrobble (
            lastfm_username, played_at, played_at_uts,
            track_mbid, track_name, track_url,
            artist_mbid, artist_name, artist_url,
            album_mbid, album_name
        )
        VALUES (
            'user1', NOW(), 1700000000,
            NULL, 'My Song', NULL,
            'artist-1', 'Test Artist', NULL,
            NULL, 'My Album'
        )
        RETURNING id
        """
    )
    await db.execute(
        """
        INSERT INTO lastfm_scrobble_match (scrobble_id, track_id, match_score, match_method, match_reason, cache_key)
        VALUES ($1, $2, 1.0, 'name_artist_title', 'track_name', 'name:test artist|my song')
        """,
        scrobble_id,
        track_id,
    )

    from app.scanner.scan_manager import ScanManager

    manager = ScanManager.get_instance()
    manager.scanner._updated_track_ids = {track_id}
    manager.scanner._new_track_ids = set()
    manager.scanner._deleted_track_ids = set()
    manager.scanner._deleted_artist_mbids = set()

    await manager._sync_lastfm_matches(db)

    row = await db.fetchrow(
        "SELECT track_id FROM lastfm_scrobble_match WHERE scrobble_id = $1",
        scrobble_id,
    )
    assert row is None
