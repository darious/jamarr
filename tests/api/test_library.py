import pytest
from httpx import AsyncClient

@pytest.fixture
async def library_data(db):
    """Insert dummy data for library tests."""
    # Artist
    await db.execute("""
        INSERT INTO artist (mbid, name, sort_name, image_url)
        VALUES 
            ('artist-1', 'The Testers', 'Testers, The', 'http://img/1'),
            ('artist-2', 'Solo Guy', 'Solo Guy', 'http://img/2')
    """)
    # Album
    await db.execute("""
        INSERT INTO album (mbid, title, release_date)
        VALUES 
            ('album-1', 'Test Album', '2023-01-01'),
            ('album-2', 'Single Hit', '2023-02-01')
    """)
    # Tracks
    await db.execute("""
        INSERT INTO track (path, title, artist, album, duration_seconds, track_no, disc_no, artist_mbid, release_group_mbid, date)
        VALUES 
            ('/music/test1.flac', 'Track One', 'The Testers', 'Test Album', 180, 1, 1, 'artist-1', 'album-1', '2023'),
            ('/music/test2.flac', 'Track Two', 'The Testers', 'Test Album', 200, 2, 1, 'artist-1', 'album-1', '2023'),
            ('/music/test3.flac', 'Solo Hit', 'Solo Guy', 'Single Hit', 210, 1, 1, 'artist-2', 'album-2', '2023')
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
    names = [a["name"] for a in data]
    assert "The Testers" in names
    assert "Solo Guy" in names
    
    # 2. Filter by name
    response = await client.get("/api/artists", params={"name": "The Testers"})
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "The Testers"
    
    # 3. Get Single Artist (Detailed)
    response = await client.get("/api/artists", params={"name": "The Testers"})
    assert response.status_code == 200
    # Logic in code: if filtered by name/mbid return list.
    # The frontend usually expects a single object for details? 
    # The API returns a filter list. 
    # But usually frontend calls filtering by MBID to get details logic in backend.
    
    response = await client.get("/api/artists", params={"mbid": "artist-1"})
    data = response.json()
    assert len(data) == 1
    artist = data[0]
    assert artist["mbid"] == "artist-1"
    # Detailed fields should be present (top_tracks etc - might be empty)
    assert "top_tracks" in artist

@pytest.mark.asyncio
async def test_get_albums(client: AsyncClient, db, library_data):
    # 1. List all
    response = await client.get("/api/albums")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2
    titles = [a["album"] for a in data]
    assert "Test Album" in titles
    
    # 2. Filter by Artist
    response = await client.get("/api/albums", params={"artist": "The Testers"})
    data = response.json()
    assert len(data) == 1
    assert data[0]["album"] == "Test Album"

@pytest.mark.asyncio
async def test_get_tracks(client: AsyncClient, db, library_data):
    # 1. List by Album
    response = await client.get("/api/tracks", params={"album": "Test Album"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["title"] == "Track One"

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
    # Just verify endpoints return 200 and correct structure
    endpoints = [
        "/api/home/new-releases",
        "/api/home/recently-added-albums",
        "/api/home/recently-played-albums",
        "/api/home/recently-played-artists",
        "/api/home/discover-artists"
    ]
    for ep in endpoints:
        response = await client.get(ep)
        assert response.status_code == 200
        assert isinstance(response.json(), list)
