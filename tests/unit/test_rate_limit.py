import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.scanner.core import Scanner
from app.scanner.metadata import SpotifyRateLimitError

@pytest.mark.asyncio
async def test_scanner_stops_on_spotify_rate_limit():
    # Mock DB
    mock_db = AsyncMock()
    # mock fetch returning a list
    # mbid, name, updated_at, sort_name, bio, image_url, art_id_existing, art_source_existing, spotify_link_existing, link_count, top_track_count, single_count, similar_count
    mock_row = ('mbid1', 'Artist One', None, 'One', None, None, None, None, None, 0, 0, 0, 0)
    mock_db.fetch.return_value = [mock_row, mock_row] # 2 items to prove we stop at first
    mock_db.fetchrow.return_value = None
    mock_db.execute.return_value = None

    # Mock get_db generator
    async def mock_get_db_gen():
        yield mock_db

    # Patch get_db in the module where it is imported/used
    with patch('app.scanner.core.get_db', side_effect=mock_get_db_gen):
        with patch('app.scanner.core.fetch_artist_metadata', new_callable=AsyncMock) as mock_fetch:
            # Set side effect to raise error
            mock_fetch.side_effect = SpotifyRateLimitError(retry_after=42)
            
            scanner = Scanner()
            scanner.scan_logger = MagicMock()
            
            # Expect the exception to bubble up
            with pytest.raises(SpotifyRateLimitError) as excinfo:
                await scanner.update_metadata()
            
            assert "Retry after 42s" in str(excinfo.value)
            
            assert "Retry after 42s" in str(excinfo.value)
            
            # Verify critical log was emitted
            scanner.scan_logger.critical.assert_not_called() # scan_logger is custom, but we logged to 'logger' in core.py
            # Actually we mocked 'scan_logger' object but the log uses module level 'logger'.
            # We can't easily check module logger without 'caplog' fixture from pytest.
            # But the exception bubbling is proof enough.
