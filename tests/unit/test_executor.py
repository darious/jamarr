
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.scanner.core import Scanner
from app.scanner.artwork import extract_and_save_artwork

@pytest.mark.asyncio
async def test_process_file_offloads_tags_extraction():
    """
    Verify that _process_file uses loop.run_in_executor for extract_tags.
    """
    scanner = Scanner()
    scanner.stats = {"scanned": 0, "added": 0, "updated": 0, "errors": 0}
    scanner._db_files_cache = {}
    
    # Mocks
    db = AsyncMock()
    path = "/music/test.mp3"
    scanner.scan_logger = None
    
    # We patch things to isolate I/O and side effects
    with patch("app.scanner.core.extract_tags") as mock_extract_tags, \
         patch("app.scanner.core.asyncio.get_running_loop") as mock_get_loop, \
         patch("app.scanner.core.os.path.getmtime", return_value=1000), \
         patch("app.scanner.core.extract_and_save_artwork", new_callable=AsyncMock) as mock_art_extract, \
         patch("app.scanner.core.upsert_artwork_record", new_callable=AsyncMock) as mock_upsert_art, \
         patch("app.scanner.core.upsert_image_mapping", new_callable=AsyncMock) as mock_upsert_map:
         
        # Setup Loop & Executor
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        
        # run_in_executor returns a future/awaitable. AsyncMock handles 'await'.
        mock_loop.run_in_executor = AsyncMock()
        mock_loop.run_in_executor.return_value = {"title": "Test Title"} 
        
        # Setup Artwork flow success
        mock_art_extract.return_value = {"sha1": "testsha1", "meta": {}}
        mock_upsert_art.return_value = 1 # ID
        mock_upsert_map.return_value = None

        # Act
        await scanner._process_file(path, db, set(), False)
        
        # Assert
        # Check that run_in_executor was called with (None, extract_tags, path)
        mock_loop.run_in_executor.assert_called_with(None, mock_extract_tags, path)

        # Ensure no errors logged (implies no exception raised)
        assert scanner.stats["errors"] == 0


@pytest.mark.asyncio
async def test_extract_artwork_offloads_to_executor():
    """
    Verify that extract_and_save_artwork uses loop.run_in_executor for _extract_artwork_data.
    """
    path = "/music/test.mp3"
    
    with patch("app.scanner.artwork._extract_artwork_data") as mock_extract_data, \
         patch("app.scanner.artwork.asyncio.get_running_loop") as mock_get_loop, \
         patch("app.scanner.artwork._save_artwork_to_disk", new_callable=AsyncMock) as mock_save:
         
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        
        # Mock executor to return bytes
        mock_loop.run_in_executor = AsyncMock()
        mock_loop.run_in_executor.return_value = b"imagedata" 
        
        mock_save.return_value = ("sha1hash", {})
        
        # Act
        await extract_and_save_artwork(path)
        
        # Assert
        # We patched "app.scanner.artwork._extract_artwork_data", so we should check against that mock.
        mock_loop.run_in_executor.assert_called_with(None, mock_extract_data, path)
