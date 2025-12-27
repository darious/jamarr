import pytest
from httpx import AsyncClient
from tests.utils.assertions import (
    assert_track_structure, 
    assert_artist_structure, 
    SPECIAL_CHAR_STRINGS,
    MALICIOUS_SQL_STRINGS
)

@pytest.fixture
async def search_data(db):
    # Insert with artwork
    await db.execute("""
        INSERT INTO artwork (id, sha1, path_on_disk) 
        VALUES (500, '5555555555666666666677777777778888888888', '/tmp/search.jpg')
    """)
    
    await db.execute("""
        INSERT INTO track (path, title, artist, album, fts_vector, artwork_id) VALUES 
        ('/music/search.flac', 'Searchable Song', 'Search Artist', 'Search Album', 
         to_tsvector('english', 'Searchable Song') || to_tsvector('english', 'Search Artist') || to_tsvector('english', 'Search Album'),
         500)
    """)
    await db.execute("""
        INSERT INTO artist (mbid, name, sort_name, artwork_id) 
        VALUES ('s1', 'Search Artist', 'Search Artist', 500)
    """)

@pytest.mark.asyncio
async def test_search(client: AsyncClient, db, search_data):
    # 1. Search existing
    response = await client.get("/api/search", params={"q": "Searchable"})
    assert response.status_code == 200
    data = response.json()
    assert "tracks" in data
    assert "artists" in data
    assert "albums" in data
    
    assert len(data["tracks"]) >= 1
    track = data["tracks"][0]
    assert track["title"] == "Searchable Song"
    assert_track_structure(track)
    assert track["art_id"] == 500
    
    # 2. Search artist
    response = await client.get("/api/search", params={"q": "Search Artist"})
    data = response.json()
    assert len(data["artists"]) >= 1
    artist = data["artists"][0]
    assert artist["name"] == "Search Artist"
    assert_artist_structure(artist)
    assert artist["art_id"] == 500
    
    # 3. Empty/Short
    # Should be empty results, not error
    response = await client.get("/api/search", params={"q": "a"})
    assert response.status_code == 200
    # Depending on implementation, minimal length might return empty dict or list
    
    # 4. Special Characters
    for s in SPECIAL_CHAR_STRINGS:
        response = await client.get("/api/search", params={"q": s})
        assert response.status_code == 200

    # 5. Malicious SQL
    for s in MALICIOUS_SQL_STRINGS:
        response = await client.get("/api/search", params={"q": s})
        assert response.status_code == 200
        # Should not throw 500

