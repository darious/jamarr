import pytest
from httpx import AsyncClient

@pytest.fixture
async def search_data(db):
    await db.execute("""
        INSERT INTO track (path, title, artist, album, fts_vector) VALUES 
        ('/music/search.flac', 'Searchable Song', 'Search Artist', 'Search Album', 
         to_tsvector('english', 'Searchable Song') || to_tsvector('english', 'Search Artist') || to_tsvector('english', 'Search Album'))
    """)
    await db.execute("INSERT INTO artist (mbid, name, sort_name) VALUES ('s1', 'Search Artist', 'Search Artist')")

@pytest.mark.asyncio
async def test_search(client: AsyncClient, db, search_data):
    # 1. Search existing
    response = await client.get("/api/search", params={"q": "Searchable"})
    assert response.status_code == 200
    data = response.json()
    assert len(data["tracks"]) >= 1
    assert data["tracks"][0]["title"] == "Searchable Song"
    
    # 2. Search artist
    response = await client.get("/api/search", params={"q": "Search Artist"})
    data = response.json()
    assert len(data["artists"]) >= 1
    assert data["artists"][0]["name"] == "Search Artist"
    
    # 3. Empty/Short
    response = await client.get("/api/search", params={"q": "a"})
    assert len(response.json()["tracks"]) == 0
