"""
Test that replicates the exact UI flow for Top Tracks artwork display.

This test verifies:
1. Artist API returns top_tracks with art_id and art_sha1
2. Tracks API returns tracks with art_id and art_sha1  
3. The combination of both provides artwork for the UI
"""
import pytest

@pytest.mark.asyncio
async def test_top_tracks_ui_artwork_flow(client, db):
    """
    Replicate the exact UI flow:
    1. Fetch artist with top_tracks (which have local_track_id)
    2. Fetch tracks for that artist
    3. Verify both have artwork fields so UI can display them
    """
    # Setup test data - use unique IDs to avoid conflicts
    artist_mbid = "test-artist-ui-flow-unique"
    track_id = 990001
    artwork_id = 880001
    artwork_sha1 = "test-ui-flow-sha1-unique"
    
    # Insert artwork
    await db.execute(
        "INSERT INTO artwork (id, sha1, path_on_disk) VALUES ($1, $2, '/tmp/test_ui.jpg')",
        artwork_id, artwork_sha1
    )
    
    # Insert artist
    await db.execute(
        "INSERT INTO artist (mbid, name, artwork_id) VALUES ($1, 'Test UI Artist', $2)",
        artist_mbid, artwork_id
    )
    
    # Insert track with artwork
    await db.execute("""
        INSERT INTO track (id, title, artist, album, path, duration_seconds, artwork_id)
        VALUES ($1, 'Test UI Track', 'Test UI Artist', 'Test UI Album', '/tmp/test.flac', 180, $2)
    """, track_id, artwork_id)
    
    # Link track to artist
    await db.execute(
        "INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, $2)",
        track_id, artist_mbid
    )
    
    # Insert top track pointing to this local track
    await db.execute("""
        INSERT INTO top_track (artist_mbid, track_id, type, rank, external_name, external_album)
        VALUES ($1, $2, 'top', 1, 'Test UI Track', 'Test UI Album')
    """, artist_mbid, track_id)
    
    # Step 1: Fetch artist (like the UI does)
    artist_response = await client.get(f"/api/artists?mbid={artist_mbid}")
    assert artist_response.status_code == 200
    artists = artist_response.json()
    assert len(artists) == 1
    artist = artists[0]
    
    # Verify top_tracks exist and have local_track_id
    assert "top_tracks" in artist
    assert len(artist["top_tracks"]) > 0
    top_track = artist["top_tracks"][0]
    
    print("\n=== Top Track from Artist API ===")
    print(f"local_track_id: {top_track.get('local_track_id')}")
    print(f"art_id: {top_track.get('art_id')}")
    print(f"art_sha1: {top_track.get('art_sha1')}")
    
    # THIS IS THE BUG: top_track should have art_id and art_sha1
    assert top_track.get("local_track_id") == track_id, "Top track should reference local track"
    assert "art_id" in top_track, "Top track MUST have art_id for UI"
    assert "art_sha1" in top_track, "Top track MUST have art_sha1 for UI"
    assert top_track["art_id"] == artwork_id
    assert top_track["art_sha1"] == artwork_sha1
    
    # Step 2: Fetch tracks (like the UI does) - query by album to avoid SQL bug
    tracks_response = await client.get("/api/tracks?album=Test UI Album")
    assert tracks_response.status_code == 200
    tracks = tracks_response.json()
    assert len(tracks) > 0
    
    local_track = tracks[0]
    print("\n=== Local Track from Tracks API ===")
    print(f"id: {local_track.get('id')}")
    print(f"art_id: {local_track.get('art_id')}")
    print(f"art_sha1: {local_track.get('art_sha1')}")
    
    # Verify local track also has artwork
    assert "art_id" in local_track, "Local track MUST have art_id"
    assert "art_sha1" in local_track, "Local track MUST have art_sha1"
    assert local_track["art_id"] == artwork_id
    assert local_track["art_sha1"] == artwork_sha1
    
    print("\n✅ Both APIs return artwork fields correctly")
