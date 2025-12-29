import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.scanner.core import Scanner
from app.scanner.metadata import SpotifyRateLimitError

@pytest.mark.asyncio
async def test_scanner_retries_on_spotify_rate_limit():
    # Mock DB
    mock_db = AsyncMock()
    # mock fetch returning a list
    # mbid, name, updated_at, sort_name, bio, image_url, art_id_existing, art_source_existing, spotify_link_existing, link_count, top_track_count, single_count, similar_count, primary_album_count
    mock_row = ('mbid1', 'Artist One', None, 'One', None, None, None, None, None, 0, 0, 0, 0, 0)
    mock_db.fetch.return_value = [mock_row]
    mock_db.fetchrow.return_value = None
    mock_db.execute.return_value = None

    # Mock get_db generator
    async def mock_get_db_gen():
        yield mock_db

    # Patch get_db in the module where it is imported/used
    with patch('app.scanner.core.get_db', side_effect=mock_get_db_gen):
        with patch('app.scanner.core.fetch_artist_metadata', new_callable=AsyncMock) as mock_fetch:
            # Set side effect: Raise Error ONCE, then Return Success
            mock_fetch.side_effect = [
                SpotifyRateLimitError(retry_after=1), # First call fails
                {"mbid": "mbid1", "name": "Artist One"} # Second call succeeds
            ]
            
            # Patch asyncio.sleep to not wait
            with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
                scanner = Scanner()
                scanner.scan_logger = MagicMock()
                
                # Should NOT raise exception now
                await scanner.update_metadata()
                
                # Verify sleep was called
                mock_sleep.assert_called_with(2) # 1s retry_after + 1s buffer
                
                # Verify fetch was called TWICE
                assert mock_fetch.call_count == 2
