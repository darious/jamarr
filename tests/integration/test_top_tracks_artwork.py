import pytest

@pytest.mark.asyncio
async def test_top_tracks_have_artwork(client, db):
    """
    Verify that top tracks endpoint returns artwork SHA1/ID.
    """
    # 1. Setup Data
    artist_mbid = "debug-artist-001"
    track_id = 99999
    artwork_id = 88888
    artwork_sha1 = "fake-sha-123"
    
    # Insert Artwork
    await db.execute(
        "INSERT INTO artwork (id, sha1, path_on_disk) VALUES ($1, $2, '/tmp/fake.jpg')",
        artwork_id, artwork_sha1
    )
    
    # Insert Artist
    await db.execute(
        "INSERT INTO artist (mbid, name, artwork_id) VALUES ($1, 'Test Artist', $2)",
        artist_mbid, artwork_id
    )
    
    # Insert Track linked to Artist and Artwork
    await db.execute("""
        INSERT INTO track (id, title, artist, album, path, duration_seconds, artwork_id)
        VALUES ($1, 'Test Track', 'Test Artist', 'Test Album', '/tmp/track.flac', 300, $2)
    """, track_id, artwork_id)
    
    # Link Track to Artist in track_artist (Required for get_artists join?)
    # The get_artists query uses `JOIN track_artist ta ON a.mbid = ta.artist_mbid`
    await db.execute(
        "INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, $2)",
        track_id, artist_mbid
    )

    # Insert Top Track
    await db.execute("""
        INSERT INTO top_track (artist_mbid, track_id, type, rank, external_name) 
        VALUES ($1, $2, 'top', 1, 'Test Track')
    """, artist_mbid, track_id)
    
    # Insert Single
    await db.execute("""
        INSERT INTO top_track (artist_mbid, track_id, type, rank, external_name, external_date, external_mbid) 
        VALUES ($1, $2, 'single', 1, 'Test Single', '2021-01-01', 'fake-single-mbid')
    """, artist_mbid, track_id)

    # 2. Execute Request
    response = await client.get(f"/api/artists?mbid={artist_mbid}")
    assert response.status_code == 200
    data = response.json()[0]
    
    # 3. Verify Top Tracks
    top_tracks = data.get("top_tracks", [])
    assert len(top_tracks) > 0, "Should have returned top tracks"
    tt = top_tracks[0]
    
    print(f"Top Track Data: {tt}")
    
    # The frontend likely needs both SHA1 and an ID (art_id or artwork_id)
    # Based on get_albums logic: "Frontend compatibility: expects art_id"
    
    assert "art_sha1" in tt, "Top track missing art_sha1"
    assert tt["art_sha1"] == artwork_sha1
    
    # Check for ID
    has_id = "art_id" in tt or "artwork_id" in tt
    assert has_id, "Top track missing art_id/artwork_id for frontend compatibility"

    # 4. Verify Singles
    singles = data.get("singles", [])
    assert len(singles) > 0, "Should have returned singles"
    sg = singles[0]
    
    print(f"Single Data: {sg}")
    assert "art_sha1" in sg, "Single missing art_sha1"
    has_id_sg = "art_id" in sg or "artwork_id" in sg
    assert has_id_sg, "Single missing art_id/artwork_id"
