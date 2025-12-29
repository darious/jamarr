
import pytest
from unittest.mock import AsyncMock
from app.scanner.metadata import match_track_to_library

@pytest.mark.asyncio
async def test_match_track_basic_match():
    """
    Test basic matching functionality where one candidate clearly wins.
    """
    mock_db = AsyncMock()
    # Mock data: id, title, album, duration, track_mbid, release_track_mbid, date
    candidates = [
        (1, "Hometown Glory", "19", 250, "mbid-1", "rmbid-1", "2008-01-28"),
        (2, "Some Other Song", "19", 200, "mbid-2", "rmbid-2", "2008-01-28"),
    ]
    mock_db.fetch.return_value = candidates

    # Pass album_name="19" which boosts score for candidate 1
    match_id = await match_track_to_library(mock_db, "artist-mbid", "Hometown Glory", album_name="19")
    assert match_id == 1

@pytest.mark.asyncio
async def test_match_track_date_tiebreaker_studio_vs_live():
    """
    Test tie-breaking logic where two tracks match well but one is earlier (Studio) and one is later (Live).
    """
    mock_db = AsyncMock()
    # Scenario: Finding "Hometown Glory". 
    # Candidate 2 (Live) is "Live at the Royal Albert Hall" (2011)
    # Candidate 1 (Studio) is "19" (2008)
    
    # Even if we don't provide album_name (simulating just track title match)
    # Both will score 1.0 on title. The tie-breaker should pick the earlier date.
    
    # We order them such that Live is first, to ensure "first found" isn't the winner
    candidates = [
        (101, "Hometown Glory", "Live at the Royal Albert Hall", 250, "mbid-live", "rel-mbid-live", "2011-11-29"),
        (102, "Hometown Glory", "19", 250, "mbid-19", "rel-mbid-19", "2008-01-28"),
    ]
    mock_db.fetch.return_value = candidates

    match_id = await match_track_to_library(mock_db, "artist-mbid", "Hometown Glory", album_name=None)
    
    # Should pick 102 (2008)
    assert match_id == 102

@pytest.mark.asyncio
async def test_match_track_date_tiebreaker_studio_vs_live_reverse_order():
    """
    Test tie-breaking logic ensures order doesn't matter.
    """
    mock_db = AsyncMock()
    # Studio first this time
    candidates = [
        (102, "Hometown Glory", "19", 250, "mbid-19", "rel-mbid-19", "2008-01-28"),
        (101, "Hometown Glory", "Live at the Royal Albert Hall", 250, "mbid-live", "rel-mbid-live", "2011-11-29"),
    ]
    mock_db.fetch.return_value = candidates

    match_id = await match_track_to_library(mock_db, "artist-mbid", "Hometown Glory", album_name=None)
    
    # Should still pick 102 (2008)
    assert match_id == 102

@pytest.mark.asyncio
async def test_match_track_date_normalization_year_only():
    """
    Test that year-only dates are handled correctly (YYYY -> YYYY-01-01).
    """
    mock_db = AsyncMock()
    candidates = [
        (201, "Track A", "Album A", 200, "m1", "r1", "2010"),      # Treating as 2010-01-01
        (202, "Track A", "Album B", 200, "m2", "r2", "2009-12-31") # Earlier
    ]
    mock_db.fetch.return_value = candidates
    
    match_id = await match_track_to_library(mock_db, "artist-mbid", "Track A", album_name=None)
    assert match_id == 202

@pytest.mark.asyncio
async def test_match_track_date_vs_no_date():
    """
    Test that a track with a date is preferred over one without, if match score is tied.
    """
    mock_db = AsyncMock()
    candidates = [
        (301, "Track X", "Album X", 200, "m1", "r1", None),     
        (302, "Track X", "Album Y", 200, "m2", "r2", "2020"), 
    ]
    mock_db.fetch.return_value = candidates
    
    match_id = await match_track_to_library(mock_db, "artist-mbid", "Track X", album_name=None)
    assert match_id == 302

@pytest.mark.asyncio
async def test_match_prefer_better_score_over_date():
    """
    Ensure we don't pick an earlier track if the match score is significantly worse.
    """
    mock_db = AsyncMock()
    # Candidate 1: Exact title match, later date
    # Candidate 2: Partial title match, earlier date
    candidates = [
        (401, "Exact Title Match", "Album New", 200, "m1", "r1", "2020"),
        (402, "Exact Title But Not Really", "Album Old", 200, "m2", "r2", "1990"),
    ]
    mock_db.fetch.return_value = candidates
    
    match_id = await match_track_to_library(mock_db, "artist-mbid", "Exact Title Match", album_name=None)
    assert match_id == 401

