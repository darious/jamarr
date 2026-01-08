"""
Test for /api/tracks endpoint with artist filtering.

This test validates the bug fix for the SQL syntax error that was causing
Internal Server Error when querying tracks by artist name.

Bug: The artist filter had invalid SQL with backtick operators and type mismatches
Fix: Simplified the artist matching query to use basic equality checks
"""
import pytest


@pytest.mark.asyncio
async def test_get_tracks_by_artist(client, db):
    """
    Test that /api/tracks?artist=X returns tracks with artwork fields.
    
    This validates:
    1. The SQL query doesn't crash with syntax errors
    2. Artist name matching works correctly
    3. Artwork fields (art_sha1) are returned
    """
    # Setup test data - use high IDs to avoid conflicts
    artist_name = "Test Artist For Tracks"
    artist_mbid = "test-artist-tracks-mbid"
    track_id = 990001
    artwork_id = 880001
    artwork_sha1 = "test-tracks-artwork-sha1"
    
    # Insert artwork (use ON CONFLICT to handle re-runs)
    await db.execute(
        "INSERT INTO artwork (id, sha1, path_on_disk) VALUES ($1, $2, '/tmp/test.jpg') ON CONFLICT (id) DO NOTHING",
        artwork_id, artwork_sha1
    )
    
    # Insert artist (use ON CONFLICT to handle re-runs)
    await db.execute(
        "INSERT INTO artist (mbid, name) VALUES ($1, $2) ON CONFLICT (mbid) DO NOTHING",
        artist_mbid, artist_name
    )
    
    # Insert track with artwork (use ON CONFLICT to handle re-runs)
    await db.execute("""
        INSERT INTO track (id, title, artist, album, path, duration_seconds, artwork_id)
        VALUES ($1, 'Test Track', $2, 'Test Album', '/tmp/test.flac', 180, $3)
        ON CONFLICT (path) DO NOTHING
    """, track_id, artist_name, artwork_id)
    
    # Link track to artist in junction table (use ON CONFLICT to handle re-runs)
    await db.execute(
        "INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        track_id, artist_mbid
    )
    
    # Test 1: Query by artist name (this was crashing before the fix)
    response = await client.get(f"/api/tracks?artist={artist_name}")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    tracks = response.json()
    assert len(tracks) > 0, "Should return at least one track"
    
    # Test 2: Verify artwork fields are present
    track = tracks[0]
    assert track["title"] == "Test Track"
    assert track["artist"] == artist_name
    assert "art_sha1" in track, "Track must have art_sha1 field"
    assert track["art_sha1"] == artwork_sha1
    
    print(f"\n✅ Track returned with artwork: art_sha1={track['art_sha1'][:20]}...")


@pytest.mark.asyncio
async def test_get_tracks_by_album(client, db):
    """
    Test that /api/tracks?album=X returns tracks with artwork.
    """
    # Setup - use high IDs to avoid conflicts
    album_name = "Test Album For Tracks"
    track_id = 990002
    artwork_id = 880002
    artwork_sha1 = "test-album-tracks-sha1"
    
    await db.execute(
        "INSERT INTO artwork (id, sha1, path_on_disk) VALUES ($1, $2, '/tmp/test2.jpg') ON CONFLICT (id) DO NOTHING",
        artwork_id, artwork_sha1
    )
    
    await db.execute("""
        INSERT INTO track (id, title, artist, album, path, duration_seconds, artwork_id)
        VALUES ($1, 'Album Track', 'Artist', $2, '/tmp/test2.flac', 200, $3)
        ON CONFLICT (path) DO NOTHING
    """, track_id, album_name, artwork_id)
    
    # Query by album
    response = await client.get(f"/api/tracks?album={album_name}")
    assert response.status_code == 200
    
    tracks = response.json()
    assert len(tracks) > 0
    
    track = tracks[0]
    assert track["album"] == album_name
    assert track["art_sha1"] == artwork_sha1


@pytest.mark.asyncio
async def test_get_tracks_with_special_characters_in_artist_name(client, db):
    """
    Test that artist names with special characters don't cause SQL errors.
    
    This was part of the original bug - the REPLACE logic for handling
    quotes and backticks was causing SQL syntax errors.
    """
    # Artist name with apostrophe (common case) - use high ID
    artist_name = "Artist's Name"
    artist_mbid = "test-special-chars-mbid"
    track_id = 990003
    
    await db.execute(
        "INSERT INTO artist (mbid, name) VALUES ($1, $2) ON CONFLICT (mbid) DO NOTHING",
        artist_mbid, artist_name
    )
    
    await db.execute("""
        INSERT INTO track (id, title, artist, album, path, duration_seconds)
        VALUES ($1, 'Special Track', $2, 'Album', '/tmp/special.flac', 180)
        ON CONFLICT (path) DO NOTHING
    """, track_id, artist_name)
    
    await db.execute(
        "INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        track_id, artist_mbid
    )
    
    # This should not crash with SQL syntax error
    response = await client.get(f"/api/tracks?artist={artist_name}")
    assert response.status_code == 200
    
    tracks = response.json()
    assert len(tracks) > 0
    assert tracks[0]["artist"] == artist_name


@pytest.mark.asyncio
async def test_tracks_response_excludes_quick_hash_and_maps_release_ids(client, db):
    """
    Ensure /api/tracks does not include quick_hash (binary column) and exposes
    release IDs via mb_release_id/mb_release_group_id aliases.
    """
    artist_name = "Quick Hash Artist"
    artist_mbid = "quick-hash-artist-mbid"
    track_id = 990010
    release_id = "release-123"
    release_group_id = "rg-456"

    # Artist + track with quick_hash populated (bytea)
    await db.execute(
        "INSERT INTO artist (mbid, name) VALUES ($1, $2) ON CONFLICT (mbid) DO NOTHING",
        artist_mbid, artist_name
    )
    await db.execute(
        """
        INSERT INTO track (id, title, artist, album, path, duration_seconds, quick_hash, release_mbid, release_group_mbid)
        VALUES ($1, 'Quick Hash Track', $2, 'Quick Album', '/tmp/qh.flac', 123, decode('01020304', 'hex'), $3, $4)
        ON CONFLICT (path) DO NOTHING
        """,
        track_id, artist_name, release_id, release_group_id
    )
    await db.execute(
        "INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        track_id, artist_mbid
    )

    response = await client.get(f"/api/tracks?artist={artist_name}")
    assert response.status_code == 200

    tracks = response.json()
    assert tracks, "Expected at least one track in response"
    track = tracks[0]

    # quick_hash should not be present in response payload
    assert "quick_hash" not in track

    # Release IDs should be exposed via frontend-friendly keys
    assert track.get("mb_release_id") == release_id
    assert track.get("mb_release_group_id") == release_group_id
