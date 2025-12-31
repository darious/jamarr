import pytest
from httpx import AsyncClient
from tests.utils.assertions import (
    assert_track_structure, 
    assert_artist_structure, 
    assert_album_structure,
    SPECIAL_CHAR_STRINGS
)

@pytest.fixture
async def library_data(db):
    """Insert dummy data for library tests."""
    
    # Insert Artwork First
    await db.execute("""
        INSERT INTO artwork (id, sha1, path_on_disk)
        VALUES 
            (101, '1111111111222222222233333333334444444444', '/tmp/art1.jpg'),
            (201, 'aaaaabbbbbcccccdddddeeeeefffff1111122222', '/tmp/art2.jpg')
    """)
    
    # Artist
    # Schema has 'artwork_id', not 'art_id'
    await db.execute("""
        INSERT INTO artist (mbid, name, sort_name, artwork_id)
        VALUES 
            ('artist-1', 'The Testers', 'Testers, The', 101),
            ('artist-2', 'Solo Guy', 'Solo Guy', NULL)
    """)
    # Album
    # UPDATED: mbid is Release ID, added release_group_mbid
    await db.execute("""
        INSERT INTO album (mbid, release_group_mbid, title, release_date)
        VALUES 
            ('release-1', 'rg-1', 'Test Album', '2023-01-01'),
            ('release-2', 'rg-2', 'Single Hit', '2023-02-01')
    """)
    # Tracks
    # Updated to include release_mbid and release_group_mbid
    # Track One/Two -> Release 1 (RG 1)
    # Solo Hit -> Release 2 (RG 2)
    # Schema has 'artwork_id'
    await db.execute("""
        INSERT INTO track (path, title, artist, album, duration_seconds, track_no, disc_no, artist_mbid, album_artist_mbid, release_mbid, release_group_mbid, release_date, artwork_id)
        VALUES 
            ('/music/test1.flac', 'Track One', 'The Testers', 'Test Album', 180, 1, 1, 'artist-1', 'artist-1', 'release-1', 'rg-1', '2023-01-01', 201),
            ('/music/test2.flac', 'Track Two', 'The Testers', 'Test Album', 200, 2, 1, 'artist-1', 'artist-1', 'release-1', 'rg-1', '2023-01-01', 201),
            ('/music/test3.flac', 'Solo Hit', 'Solo Guy', 'Single Hit', 210, 1, 1, 'artist-2', 'artist-2', 'release-2', 'rg-2', '2023-01-01', NULL)
    """)
    # Track-Artist Relations
    row1 = await db.fetchrow("SELECT id FROM track WHERE title = 'Track One'")
    row2 = await db.fetchrow("SELECT id FROM track WHERE title = 'Track Two'")
    row3 = await db.fetchrow("SELECT id FROM track WHERE title = 'Solo Hit'")
    
    await db.execute("INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, 'artist-1')", row1['id'])
    await db.execute("INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, 'artist-1')", row2['id'])
    await db.execute("INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, 'artist-2')", row3['id'])

@pytest.mark.asyncio
async def test_get_artists(client: AsyncClient, db, library_data):
    # 1. List all
    response = await client.get("/api/artists")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2
    
    for artist in data:
        assert_artist_structure(artist)

    names = [a["name"] for a in data]
    assert "The Testers" in names
    assert "Solo Guy" in names
    
    # Verify artwork fields logic
    tester = next(a for a in data if a["name"] == "The Testers")
    assert tester["art_id"] == 101
    assert tester["art_sha1"] == '1111111111222222222233333333334444444444'

    # 2. Filter by name
    response = await client.get("/api/artists", params={"name": "The Testers"})
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "The Testers"
    assert_artist_structure(data[0])
    
    # 3. Get Single Artist (Detailed)
    response = await client.get("/api/artists", params={"mbid": "artist-1"})
    data = response.json()
    assert len(data) == 1
    artist = data[0]
    assert_artist_structure(artist)
    assert artist["mbid"] == "artist-1"
    # Detailed fields should be present
    assert "top_tracks" in artist
    assert isinstance(artist["top_tracks"], list)

@pytest.mark.asyncio
async def test_get_albums(client: AsyncClient, db, library_data):
    # 1. List all
    response = await client.get("/api/albums")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2
    
    for album in data:
        assert_album_structure(album)
        
    titles = [a["album"] for a in data]
    assert "Test Album" in titles
    
    # Check artwork
    test_album = next(a for a in data if a["album"] == "Test Album")
    assert test_album["art_id"] == 201
    
    # 2. Filter by Artist
    response = await client.get("/api/albums", params={"artist": "The Testers"})
    data = response.json()
    assert len(data) == 1
    assert data[0]["album"] == "Test Album"

@pytest.mark.asyncio
async def test_get_albums_appears_on(client: AsyncClient, db, library_data):
    # Insert a track where "The Testers" are a featured artist (appears on)
    # Primary artist is "Solo Guy", Track Artist is "Solo Guy feat. The Testers"
    # We need to link "The Testers" (artist-1) to this track in track_artist
    
    # 1. Get track ID for 'Solo Hit'
    row = await db.fetchrow("SELECT id FROM track WHERE title = 'Solo Hit'")
    track_id = row['id']
    
    # 2. Add 'The Testers' as a secondary artist
    await db.execute("INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, 'artist-1') ON CONFLICT DO NOTHING", track_id)
    
    # 3. Query albums for "The Testers"
    response = await client.get("/api/albums", params={"artist": "The Testers"})
    assert response.status_code == 200
    data = response.json()
    
    # Should have 2 albums now: "Test Album" (main) and "Single Hit" (appears_on)
    # The order depends on year, both are 2023.
    assert len(data) == 2
    
    main_album = next((a for a in data if a["album"] == "Test Album"), None)
    appears_album = next((a for a in data if a["album"] == "Single Hit"), None)
    
    assert main_album is not None
    assert main_album["type"] == "main"
    
    assert appears_album is not None
    assert appears_album["type"] == "appears_on"

@pytest.mark.asyncio
async def test_get_albums_release_type(client: AsyncClient, db, library_data):
    # Update title "Test Album" to have release_type='EP' in the album table
    # Schema check: does album table have 'release_type'?
    # Assuming yes based on user input.
    # Note: album table insertion in library_data fixture didn't specify release_type, so it defaults to NULL.
    
    # 1. Update existing album to be an EP
    await db.execute("UPDATE album SET release_type = 'EP' WHERE title = 'Test Album'")
    
    # 2. Update existing album to be a Single
    await db.execute("UPDATE album SET release_type = 'Single' WHERE title = 'Single Hit'")
    
    # 3. Query albums
    response = await client.get("/api/albums")
    assert response.status_code == 200
    data = response.json()
    
    ep = next(a for a in data if a["album"] == "Test Album")
    single = next(a for a in data if a["album"] == "Single Hit")
    
    # 4. Verify release_type
    assert ep["release_type"] == "EP"
    assert single["release_type"] == "Single"

@pytest.mark.asyncio
async def test_get_albums_details(client: AsyncClient, db, library_data):
    # Update existing album to have a description and chart position
    await db.execute("UPDATE album SET description = 'A great album', peak_chart_position = 1 WHERE title = 'Test Album'")
    
    # Query albums
    response = await client.get("/api/albums", params={"artist": "The Testers"})
    assert response.status_code == 200
    data = response.json()
    
    test_album = next(a for a in data if a["album"] == "Test Album")
    
    assert test_album["description"] == "A great album"
    assert test_album["peak_chart_position"] == 1
    assert "label" in test_album
    assert "external_links" in test_album
    assert isinstance(test_album["external_links"], list)

@pytest.mark.asyncio
async def test_get_tracks(client: AsyncClient, db, library_data):
    # 1. List by Album
    response = await client.get("/api/tracks", params={"album": "Test Album"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    
    for track in data:
        assert_track_structure(track)
        
    assert data[0]["title"] == "Track One"

@pytest.mark.asyncio
async def test_special_characters_library(client: AsyncClient, db):
    """Test inserting and retrieving items with special characters."""
    for i, name in enumerate(SPECIAL_CHAR_STRINGS):
        mbid = f"special-artist-{i}"
        track_path = f"/music/special-{i}.flac"

        # Insert Artist
        await db.execute(
            "INSERT INTO artist (mbid, name) VALUES ($1, $2) ON CONFLICT (mbid) DO NOTHING",
            mbid, name
        )
        
        # Insert Track
        # Use ON CONFLICT to avoid unique path constraint if re-running
        await db.execute(
            "INSERT INTO track (path, title, artist, album, duration_seconds) VALUES ($1, $2, $3, 'Special Album', 180) ON CONFLICT (path) DO NOTHING RETURNING id",
            track_path, f"Track {i}", name
        )
        
        # Get track ID (in case it existed)
        row = await db.fetchrow("SELECT id FROM track WHERE path = $1", track_path)
        track_id = row["id"]

        # Link Track-Artist
        await db.execute(
            "INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            track_id, mbid
        )

        # Search exact match
        response = await client.get("/api/artists", params={"name": name})
        assert response.status_code == 200, f"Failed lookup for {name}"
        data = response.json()

        # We might match multiple if we have partial matches, but we should find our exact one
        found = False
        for artist in data:
            if artist["name"] == name:
                found = True
                break
        
        assert found, f"Could not find artist with name: {name}"

@pytest.mark.asyncio
async def test_missing_albums(client: AsyncClient, db):
    # Inject missing album
    await db.execute("""
        INSERT INTO artist (mbid, name) VALUES ('artist-miss', 'Missing Person')
    """)
    await db.execute("""
        INSERT INTO missing_album (artist_mbid, release_group_mbid, title, release_date)
        VALUES ('artist-miss', 'rg-1', 'Lost Album', '2020')
    """)
    
    response = await client.get("/api/artists/artist-miss/missing")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Lost Album"

@pytest.mark.asyncio
async def test_home_feeds(client: AsyncClient, db, library_data):
    # 1. New Releases / Recently Added
    # library_data already adds tracks with dates.
    # We need to ensure updated_at is set for "recently-added"
    
    # Update updated_at of a track
    await db.execute("UPDATE track SET updated_at = NOW() WHERE title = 'Track One'")
    
    # 2. Playback History
    row = await db.fetchrow("SELECT id FROM track WHERE title = 'Track One'")
    track_id = row["id"]
    await db.execute("""
        INSERT INTO playback_history (track_id, timestamp, client_ip)
        VALUES ($1, NOW(), '127.0.0.1')
    """, track_id)

    # Test "New Releases" (by date)
    response = await client.get("/api/home/new-releases")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    # Expected structure for album-like items
    item = data[0]
    assert "album" in item
    assert "art_id" in item or "artwork_id" in item
    assert item["album"] == "Test Album"

    # Test "Recently Added" (by updated_at/id)
    response = await client.get("/api/home/recently-added-albums")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    item = data[0]
    assert "album" in item
    assert "art_id" in item or "artwork_id" in item

    # Test "Recently Played Albums"
    response = await client.get("/api/home/recently-played-albums")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    item = data[0]
    assert item["album"] == "Test Album"
    assert "art_id" in item or "artwork_id" in item

    # Test "Recently Played Artists"
    response = await client.get("/api/home/recently-played-artists")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    item = data[0]
    assert_artist_structure(item)
    assert item["name"] == "The Testers"
    assert "art_id" in item or "artwork_id" in item
    
    # Test "Discover Artists" (random/new)
    # The query for discover artists relies on 'last_added' via tracks
    response = await client.get("/api/home/discover-artists")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    item = data[0]
    assert_artist_structure(item)
    assert "art_id" in item or "artwork_id" in item
