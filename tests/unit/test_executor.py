
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
         patch("app.scanner.core.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread, \
         patch("app.scanner.core.os.path.getmtime", return_value=1000), \
         patch("app.scanner.core.os.stat") as mock_stat, \
         patch("app.scanner.core.extract_and_save_artwork", new_callable=AsyncMock) as mock_art_extract, \
         patch("app.scanner.core.upsert_artwork_record", new_callable=AsyncMock) as mock_upsert_art, \
         patch("app.scanner.core.upsert_image_mapping", new_callable=AsyncMock) as mock_upsert_map, \
         patch("app.scanner.core.get_music_path", return_value="/music"):
         
        # Setup Stat
        mock_stat_obj = MagicMock()
        mock_stat_obj.st_mtime = 1000
        mock_stat_obj.st_size = 500
        mock_stat.return_value = mock_stat_obj
        
        # to_thread behavior
        mock_to_thread.return_value = {"title": "Test Title"} 
        # Note: core.py calls to_thread(_compute_quick_hash) too
        # We need to handle side_effect if called multiple times or stricter assertions
        
        # core.py logic:
        # 1. stat
        # 2. _compute_quick_hash (via to_thread?) Yes I added it.
        # 3. extract_tags (via to_thread)
        
        # We should set side_effect to return appropriate values based on args?
        # Or just assert it was called with extract_tags.
        
        async def side_effect(func, *args, **kwargs):
             if func == mock_extract_tags:
                 return {"title": "Test Title"}
             return b"hash" # for compute hash
             
        mock_to_thread.side_effect = side_effect
        
        # Setup Artwork flow success
        mock_art_extract.return_value = {"sha1": "testsha1", "meta": {}}
        mock_upsert_art.return_value = 1 # ID
        mock_upsert_map.return_value = None

        # Act
        await scanner._process_file(path, db, set(), False)
        
        # Assert
        # Check that to_thread was called with extract_tags
        # mock_to_thread.assert_called_with(mock_extract_tags, path) 
        # But it's also called with compute_quick_hash, so assert_any_call
        mock_to_thread.assert_any_call(mock_extract_tags, path)

        # Ensure no errors logged
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
