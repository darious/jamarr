
import pytest

@pytest.mark.asyncio
async def test_get_tracks_returns_artists_list(auth_client, db):
    """
    Test that /api/tracks returns a list of artist objects for each track.
    
    Validates:
    1. 'artists' field is present in the response
    2. 'artists' contains objects with name and mbid
    3. Multiple artists are correctly returned
    """
    track_id = 990020
    
    # Artists
    artist1_mbid = "artist-1-mbid"
    artist1_name = "Artist One"
    artist2_mbid = "artist-2-mbid"
    artist2_name = "Artist Two"
    
    await db.execute(
        "INSERT INTO artist (mbid, name) VALUES ($1, $2) ON CONFLICT (mbid) DO NOTHING",
        artist1_mbid, artist1_name
    )
    await db.execute(
        "INSERT INTO artist (mbid, name) VALUES ($1, $2) ON CONFLICT (mbid) DO NOTHING",
        artist2_mbid, artist2_name
    )
    
    # Track
    await db.execute("""
        INSERT INTO track (id, title, artist, album, path, duration_seconds)
        VALUES ($1, 'Multi Artist Track', $2, 'Test Album', '/tmp/multi_artist.flac', 180)
        ON CONFLICT (path) DO NOTHING
    """, track_id, f"{artist1_name}, {artist2_name}")
    
    # Link artists to track
    await db.execute(
        "INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        track_id, artist1_mbid
    )
    await db.execute(
        "INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        track_id, artist2_mbid
    )
    
    # Query
    response = await auth_client.get("/api/tracks?album=Test Album")
    assert response.status_code == 200
    
    tracks = response.json()
    track = next(t for t in tracks if t["id"] == track_id)
    
    # Check for new 'artists' field
    assert "artists" in track, "Track response missing 'artists' field"
    assert isinstance(track["artists"], list), "'artists' field should be a list"
    assert len(track["artists"]) == 2
    
    # Verify contents
    names = {a["name"] for a in track["artists"]}
    mbids = {a["mbid"] for a in track["artists"]}
    
    assert artist1_name in names
    assert artist2_name in names
    assert artist1_mbid in mbids
    assert artist2_mbid in mbids
