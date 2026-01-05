import pytest
from httpx import AsyncClient

@pytest.fixture
async def search_data(db):
    # Insert with artwork
    await db.execute("""
        INSERT INTO artwork (id, sha1, path_on_disk) 
        VALUES (500, '5555555555666666666677777777778888888888', '/tmp/search.jpg')
    """)
    
    # Setup Tracks (for Track Search)
    await db.execute("""
        INSERT INTO track (path, title, artist, album, fts_vector, artwork_id) VALUES 
        ('/music/search.flac', 'Searchable Song', 'Search Artist', 'Search Album', 
         to_tsvector('english', 'Searchable Song') || to_tsvector('english', 'Search Artist') || to_tsvector('english', 'Search Album'),
         500)
    """)

    # Setup Artists
    await db.execute("""
        INSERT INTO artist (mbid, name, sort_name, artwork_id) 
        VALUES ('s1', 'Search Artist', 'Search Artist', 500)
    """)

    # Setup Album Table (for Album Search)
    await db.execute("""
        INSERT INTO album (mbid, title, artwork_id) 
        VALUES ('alb1', 'Search Album', 500)
    """)
    # Link artist to album
    await db.execute("""
        INSERT INTO artist_album (artist_mbid, album_mbid, type)
        VALUES ('s1', 'alb1', 'primary')
    """)

    # Setup "Duplicate" Album scenario
    # Single Album "Compilation 2024" with multiple artists
    await db.execute("""
        INSERT INTO album (mbid, title) VALUES ('comp1', 'Compilation 2024')
    """)
    await db.execute("INSERT INTO artist (mbid, name) VALUES ('artA', 'Artist A')")
    await db.execute("INSERT INTO artist (mbid, name) VALUES ('artB', 'Artist B')")
    # Both artists linked to same album
    await db.execute("INSERT INTO artist_album (artist_mbid, album_mbid, type) VALUES ('artA', 'comp1', 'primary')")
    await db.execute("INSERT INTO artist_album (artist_mbid, album_mbid, type) VALUES ('artB', 'comp1', 'primary')")

    # Setup for Ranking Test
    # Album: "Now That's What I Call Music" (The target)
    await db.execute("""
        INSERT INTO album (mbid, title) VALUES ('now1', 'Now That''s What I Call Music')
    """)
    await db.execute("INSERT INTO artist_album (artist_mbid, album_mbid, type) VALUES ('s1', 'now1', 'primary')")
    
    # "Noise" albums that usually rank higher because "Now" is a stopword
    # "Music Box" matches "Music" (2 words vs 7 words, so higher density/rank usually)
    await db.execute("INSERT INTO album (mbid, title) VALUES ('noise1', 'Music Box')")
    await db.execute("INSERT INTO artist_album (artist_mbid, album_mbid, type) VALUES ('s1', 'noise1', 'primary')")
    
    await db.execute("INSERT INTO album (mbid, title) VALUES ('noise2', 'Addicted to Music')")
    await db.execute("INSERT INTO artist_album (artist_mbid, album_mbid, type) VALUES ('s1', 'noise2', 'primary')")
    
    # Track with "Music" in title (would rank high in old system)
    await db.execute("""
        INSERT INTO track (path, title, artist, album, fts_vector) VALUES 
        ('/music/distraction.flac', 'Music for Airports', 'Eno', 'Ambient 1', 
         to_tsvector('english', 'Music for Airports') || to_tsvector('english', 'Eno'))
    """)


@pytest.mark.asyncio
async def test_search(client: AsyncClient, db, search_data):
    # 1. Search existing
    response = await client.get("/api/search", params={"q": "Searchable"})
    assert response.status_code == 200
    data = response.json()
    assert len(data["tracks"]) >= 1
    track = data["tracks"][0]
    assert track["title"] == "Searchable Song"
    
    # 2. Search artist
    response = await client.get("/api/search", params={"q": "Search Artist"})
    data = response.json()
    assert len(data["artists"]) >= 1
    assert data["artists"][0]["name"] == "Search Artist"
    
    # 3. Search Album (explicitly via Album table now)
    response = await client.get("/api/search", params={"q": "Search Album"})
    data = response.json()
    assert len(data["albums"]) >= 1
    assert data["albums"][0]["title"] == "Search Album"
    assert data["albums"][0]["artist"] == "Search Artist"

@pytest.mark.asyncio
async def test_search_duplicate_albums(client: AsyncClient, db, search_data):
    # Search for "Compilation"
    # Should return ONE album entry, despite two artists
    response = await client.get("/api/search", params={"q": "Compilation"})
    assert response.status_code == 200
    data = response.json()
    
    comp_albums = [a for a in data["albums"] if a["title"] == "Compilation 2024"]
    assert len(comp_albums) == 1
    # Check artist name is one of them (order deterministic by name in SQL)
    assert comp_albums[0]["artist"] in ["Artist A", "Artist B"]

@pytest.mark.asyncio
async def test_search_ranking_fix(client: AsyncClient, db, search_data):
    # Search "Now Music"
    # Should find the album "Now That's What I Call Music" AT THE TOP
    # Because "Now" is in the title, whereas "Music Box" misses "Now".
    response = await client.get("/api/search", params={"q": "Now Music"})
    assert response.status_code == 200
    data = response.json()
    
    assert len(data["albums"]) >= 2
    
    # The first result MUST be the one containing both words
    first = data["albums"][0]
    assert first["title"] == "Now That's What I Call Music"

@pytest.mark.asyncio
async def test_search_limits(client: AsyncClient, db):
    # Clear and insert 25 artists matching "LimitTest"
    await db.execute("DELETE FROM artist WHERE name LIKE 'LimitTest%'")
    for i in range(25):
        await db.execute(f"INSERT INTO artist (mbid, name) VALUES ('l{i}', 'LimitTest {i}')")
        
    response = await client.get("/api/search", params={"q": "LimitTest"})
    data = response.json()
    
    # Should be limited to 20 (new limit) instead of 5
    assert len(data["artists"]) == 20


