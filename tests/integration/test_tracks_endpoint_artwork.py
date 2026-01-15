import pytest

@pytest.mark.asyncio
async def test_tracks_endpoint_returns_artwork(auth_client, db):
    """
    Verify that /api/tracks endpoint returns art_sha1.
    """
    # 1. Setup Data
    artist_name = "Debug Tracks Artist"
    track_id = 77777
    artwork_id = 66666
    artwork_sha1 = "debug-tracks-sha1"
    
    # Insert Artwork
    await db.execute(
        "INSERT INTO artwork (id, sha1, path_on_disk) VALUES ($1, $2, '/tmp/debug_tracks.jpg')",
        artwork_id, artwork_sha1
    )
    
    # Insert Track linked to Artwork
    await db.execute("""
        INSERT INTO track (id, title, artist, album, path, duration_seconds, artwork_id)
        VALUES ($1, 'Debug Track', $3, 'Debug Album', '/tmp/debug_track.flac', 300, $2)
    """, track_id, artwork_id, artist_name)
    
    # Insert Track-Artist link (needed for get_tracks aggregation sometimes)
    await db.execute(
        "INSERT INTO artist (mbid, name) VALUES ('debug-mbid-tracks', $1)",
        artist_name
    )
    await db.execute(
        "INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, 'debug-mbid-tracks')",
        track_id
    )

    # 2. Execute Request (Query by Album to avoid complex artist SQL filter issues)
    response = await auth_client.get("/api/tracks?album=Debug%20Album")
    assert response.status_code == 200
    data = response.json()
    
    assert len(data) > 0, "Should have returned tracks"
    track = data[0]
    
    print(f"Track Data: {track}")
    
    # 3. Verify Fields
    assert "art_sha1" in track, "Track missing art_sha1"
    assert track["art_sha1"] == artwork_sha1
    
