
import asyncio
import os
import sys
import yaml
from unittest.mock import MagicMock, AsyncMock

# Add project root to path
sys.path.insert(0, os.path.abspath("/root/code/jamarr"))

from app import config
from app.api import library

# Mock config loading
original_load_config = config.load_config

def mock_load_config():
    return {
        "musicbrainz": {
            "root_url": "https://custom.musicbrainz.org"
        }
    }

config.load_config = mock_load_config

async def test_get_albums():
    print("Testing get_albums with custom MusicBrainz URL...")
    
    # Mock database
    mock_db = MagicMock()
    mock_cursor = AsyncMock()
    mock_db.execute.return_value.__aenter__.return_value = mock_cursor
    
    # Mock rows
    mock_rows = [
        (
            "Test Album", 
            1, 
            "sha1hash", 
            "Test Artist", 
            0, 
            "2023", 
            10, 
            3600, 
            "release-uuid-123", 
            "main"
        )
    ]
    mock_cursor.fetchall.return_value = mock_rows
    
    # Call the function
    # Note: get_albums depends on get_db, but we are calling it directly with a mock db if possible?
    # actually get_albums takes db as dependency.
    
    # We need to adapt the row to be dict-like or standard tuple if the code expects it.
    # The code does `d = dict(row)`. So row needs to be a mapping or have keys.
    # checking code: `rows = await cursor.fetchall()` then `d = dict(row)`.
    # `aiosqlite` rows can be cast to dict if they are Row objects.
    # We can perform a simple mock by making row a dict directly? 
    # `dict(dict_obj)` works.
    
    mock_row_dict = {
        "album": "Test Album",
        "art_id": 1,
        "art_sha1": "sha1hash",
        "artist_name": "Test Artist",
        "is_hires": 0,
        "year": "2023",
        "track_count": 10,
        "total_duration": 3600,
        "mb_release_id": "release-uuid-123",
        "type": "main"
    }
    
    mock_cursor.fetchall.return_value = [mock_row_dict]
    
    results = await library.get_albums(artist=None, db=mock_db)
    
    if not results:
        print("FAIL: No results returned")
        return
        
    album = results[0]
    expected_url = "https://custom.musicbrainz.org/release/release-uuid-123"
    
    if album.get("musicbrainz_url") == expected_url:
        print(f"PASS: Correct URL found: {album.get('musicbrainz_url')}")
    else:
        print(f"FAIL: Expected {expected_url}, got {album.get('musicbrainz_url')}")

if __name__ == "__main__":
    asyncio.run(test_get_albums())
