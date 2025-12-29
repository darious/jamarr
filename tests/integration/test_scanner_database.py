import pytest
from app.scanner.core import Scanner

"""
This module tests the underlying logic of the Scanner core class against a real database.
It is separate from `tests/api/test_scanner.py` because that file tests the API endpoints
and uses Mocks for the Scanner/ScanManager to ensure speed and isolation.

These tests verify that the SQL queries and logic inside Scanner.update_metadata
execute correctly against the PostgreSQL schema without InterfaceErrors.
"""

@pytest.mark.asyncio
async def test_repro_metadata_update_interface_error(db):
    """
    Reproduce InterfaceError: the server expects 0 arguments for this query, 1 was passed
    Steps:
    1. Call update_metadata with mbid_filter as empty or None.
    2. This results in empty params [], but the code calls fetch(query, params) without unpacking.
    3. asyncpg receives ([],) as args (1 argument).
    4. Query has no placeholders (0 arguments expected).
    """
    scanner = Scanner()
    
    # CASE: No filters -> params=[]
    # This passed previously because it raised InterfaceError (caught).
    # Now it should run without error.
    await scanner.update_metadata(mbid_filter=None, artist_filter=None)
    
    # CASE: With filters -> params=[list]
    # Ensure *params unpacking handles list argument correctly (as $1 array)
    await scanner.update_metadata(mbid_filter={"some-uuid"})

    # CASE: scan_missing_albums with no filters (Same bug pattern at line 1385)
    # Using missing_only=True logic inside scan_missing_albums logic? No, it has different args.
    # It just takes filters.
    await scanner.scan_missing_albums(artist_filter=None, mbid_filter=None)


@pytest.mark.asyncio
async def test_rematch_tracks_top_updates_track_id(monkeypatch, db):
    """
    Ensure rematch_tracks_top passes arguments correctly to asyncpg (no InterfaceError)
    and updates track_id/updated_at when match_track_to_library returns a hit.
    """
    scanner = Scanner()
    artist_mbid = "rematch-artist-001"
    track_id = 4242

    # Insert minimal artist and track
    await db.execute("INSERT INTO artist (mbid, name) VALUES ($1, 'Rematch Artist') ON CONFLICT DO NOTHING", artist_mbid)
    await db.execute(
        """
        INSERT INTO track (id, title, artist, album, path, duration_seconds)
        VALUES ($1, 'Rematch Track', 'Rematch Artist', 'Rematch Album', '/tmp/rematch.flac', 123)
        ON CONFLICT (id) DO NOTHING
        """,
        track_id,
    )

    # Top track with no local match yet
    await db.execute(
        """
        INSERT INTO top_track (artist_mbid, type, rank, external_name, external_album, track_id)
        VALUES ($1, 'top', 1, 'Rematch Track', 'Rematch Album', NULL)
        """,
        artist_mbid,
    )

    # Force match_track_to_library to return our track_id
    async def _fake_match_track_to_library(_db, _mbid, _name, _album):
        return track_id

    monkeypatch.setattr(
        "app.scanner.metadata.match_track_to_library",
        _fake_match_track_to_library,
    )

    await scanner.rematch_tracks_top({(artist_mbid, "Rematch Artist")})

    row = await db.fetchrow("SELECT track_id, updated_at FROM top_track WHERE artist_mbid=$1", artist_mbid)
    assert row["track_id"] == track_id
    assert row["updated_at"] is not None


@pytest.mark.asyncio
async def test_scanner_real_row_unpacking(monkeypatch, db):
    """
    Regression Test: Ensure the exact SQL query in update_metadata matching the
    row unpacking logic in the consumer loops (has_selected_gaps, main loop, etc.).

    This inserts a real artist, mocks the network fetch (to avoid external hits),
    and runs update_metadata(). If unpacking fails (ValueError), this test will fail.
    """
    scanner = Scanner()
    mbid = "unpacking-test-mbid"

    # 1. Insert valid artist
    await db.execute("INSERT INTO artist (mbid, name) VALUES ($1, 'Unpack Artist')", mbid)

    # 2. Mock network calls so we don't actually hit APIs,
    # but strictly verify the DB->App->DB cycle.
    async def mock_fetch_meta(*args, **kwargs):
        # Return mostly empty meta, we just want to ensure it gets here
        return {"mbid": mbid, "name": "Unpack Artist"}

    monkeypatch.setattr("app.scanner.core.fetch_artist_metadata", mock_fetch_meta)

    # 3. Scanner should find the artist and process it.
    # Note: we need at least one gap to trigger 'fetch'.
    # Default artist w/o updated_at, link_count=0 etc should trigger scan.

    await scanner.update_metadata(mbid_filter={mbid})

    # 4. If we reached here without raising ValueError, the unpacking logic matches the SQL schema.
    # Verify updated_at to ensure it actually ran.
    row = await db.fetchrow("SELECT updated_at FROM artist WHERE mbid=$1", mbid)
    assert row["updated_at"] is not None
