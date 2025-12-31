import pytest
from unittest.mock import AsyncMock
from app.scanner.core import match_track_to_library

@pytest.fixture
def mock_db():
    db = AsyncMock()
    # Mock fetch defaults
    db.fetch.return_value = []
    # Mock row class to simulate record
    class MockRecord(list):
        def __getitem__(self, key):
            # Not needed if we unpack
            return super().__getitem__(key)
    return db

@pytest.mark.asyncio
async def test_priority_single_vs_album(mock_db):
    """
    Test that Single (1) beats Album (3) when titles are identical.
    """
    # cid, ctitle, calbum, cseconds, cmb_track_id, cmb_release_track_id, cdate, ctype
    candidates = [
        [101, "Test Song", "Test Single", 200, "mb1", "rmb1", "2020-01-01", "single"],
        [102, "Test Song", "Test Album",  200, "mb2", "rmb2", "2020-01-01", "album"]
    ]
    mock_db.fetch.return_value = candidates

    match_id = await match_track_to_library(mock_db, "artist-mbid", "Test Song")
    
    assert match_id == 101, "Should pick Single (101) over Album (102)"

@pytest.mark.asyncio
async def test_priority_album_vs_live(mock_db):
    """
    Test that Album (3) beats Live (6) when titles are identical.
    """
    candidates = [
        [201, "Live Song", "Live at Venue", 300, "mb1", "rmb1", "2020-01-01", "live"],
        [202, "Live Song", "Studio Album",  300, "mb2", "rmb2", "2020-01-01", "album"]
    ]
    mock_db.fetch.return_value = candidates

    match_id = await match_track_to_library(mock_db, "artist-mbid", "Live Song")
    
    assert match_id == 202, "Should pick Album (202) over Live (201)"

@pytest.mark.asyncio
async def test_priority_date_tiebreaker(mock_db):
    """
    Test that Earlier Date wins when Type is same.
    """
    candidates = [
        [301, "My Song", "Single 2020", 200, "mb1", "rmb1", "2020-01-01", "single"],
        [302, "My Song", "Single 2010", 200, "mb2", "rmb2", "2010-01-01", "single"]
    ]
    mock_db.fetch.return_value = candidates

    match_id = await match_track_to_library(mock_db, "artist-mbid", "My Song")
    
    assert match_id == 302, "Should pick Earlier Date (302: 2010) over 2020"

@pytest.mark.asyncio
async def test_score_trumps_type(mock_db):
    """
    Test that a much better title match wins even if type priority is worse.
    Track: "Beautiful Day"
    Candidate 1: "Beautiful Day" (Live) - Score 1.0, Priority 6
    Candidate 2: "Beautiful" (Single) - Score ~0.7, Priority 1
    
    Live should win.
    """
    candidates = [
        [401, "Beautiful Day", "Live 2020", 200, "mb1", "rmb1", "2020-01-01", "live"],
        [402, "Beautiful",     "Single 2010", 200, "mb2", "rmb2", "2010-01-01", "single"]
    ]
    mock_db.fetch.return_value = candidates

    match_id = await match_track_to_library(mock_db, "artist-mbid", "Beautiful Day")
    
    assert match_id == 401, "Should pick Exact Match (401) despite worse type priority"

@pytest.mark.asyncio
async def test_unknown_type_handling(mock_db):
    """
    Test that unknown type maps to 'other' (5) and loses to Album (3).
    """
    candidates = [
        [501, "Song", "Unknown Release", 200, "mb1", "rmb1", "2020-01-01", None],   # Priority 5
        [502, "Song", "Album Release",   200, "mb2", "rmb2", "2020-01-01", "album"] # Priority 3
    ]
    mock_db.fetch.return_value = candidates

    match_id = await match_track_to_library(mock_db, "artist-mbid", "Song")
    
    assert match_id == 502, "Should pick Album (502) over Unknown/None (501)"
