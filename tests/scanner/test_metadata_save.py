import pytest
from unittest.mock import AsyncMock
from app.scanner.services.coordinator import MetadataCoordinator

@pytest.fixture
def mock_db():
    db = AsyncMock()
    tx_ctx = AsyncMock()
    tx_ctx.__aenter__.return_value = None
    tx_ctx.__aexit__.return_value = None
    db.transaction = lambda: tx_ctx
    db.execute = AsyncMock()
    db.fetch = AsyncMock(return_value=[])
    return db

@pytest.mark.asyncio
async def test_top_tracks_string_to_int_conversion(mock_db):
    """Test that top track rank and popularity strings are converted to integers"""
    coord = MetadataCoordinator()
    
    # Simulate Last.fm API response with string values
    metadata = {
        "top_tracks": [
            {"name": "Track 1", "mbid": "mbid1", "rank": "1", "popularity": "2549495"},
            {"name": "Track 2", "mbid": "mbid2", "rank": "2", "popularity": "1234567"},
        ]
    }
    
    await coord.save_artist_metadata(mock_db, "artist-mbid", metadata, None)
    
    # Verify execute was called
    assert mock_db.execute.called
    
    # Find the INSERT INTO top_track calls
    insert_calls = [call for call in mock_db.execute.call_args_list 
                    if "INSERT INTO top_track" in str(call)]
    
    assert len(insert_calls) == 2, "Should have 2 top track inserts"
    
    # Check first insert - rank and popularity should be int, not str
    first_call_args = insert_calls[0][0]
    rank_arg = first_call_args[3]  # 4th positional arg
    popularity_arg = first_call_args[4]  # 5th positional arg
    
    assert isinstance(rank_arg, int), f"Rank should be int, got {type(rank_arg)}"
    assert isinstance(popularity_arg, int), f"Popularity should be int, got {type(popularity_arg)}"
    assert rank_arg == 1
    assert popularity_arg == 2549495

@pytest.mark.asyncio
async def test_singles_saved_to_top_track(mock_db):
    """Test that singles are saved to top_track table with type='single'"""
    coord = MetadataCoordinator()
    
    metadata = {
        "singles": [
            {"mbid": "single1", "title": "Single 1", "date": "2020-01-01"},
            {"mbid": "single2", "title": "Single 2", "date": "2021-01-01"},
        ]
    }
    
    await coord.save_artist_metadata(mock_db, "artist-mbid", metadata, None)
    
    # Find the INSERT INTO top_track calls with type='single'
    insert_calls = [call for call in mock_db.execute.call_args_list 
                    if "INSERT INTO top_track" in str(call) and "'single'" in str(call)]
    
    assert len(insert_calls) == 2, "Should have 2 single inserts into top_track"
