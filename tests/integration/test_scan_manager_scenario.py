import pytest
from unittest.mock import AsyncMock, patch
from app.scanner.scan_manager import ScanManager

@pytest.mark.asyncio
async def test_scenario_full_refresh_no_errors(db):
    """
    Scenario Test: "Scan All (Full Refresh)"
    
    This replicates the exact user scenario from the screenshot:
    1. User clicks "Scan All" (which calls ScanManager.start_full with force=True/False).
    2. The scanner runs `scan_filesystem` (mocked here to avoid file IO).
    3. The scanner runs `update_metadata`.
    
    We verify that this flow completes WITHOUT the "InterfaceError" seen in the logs.
    """
    manager = ScanManager.get_instance()
    
    # Mock filesystem scan to return empty set (no new files found), 
    # but strictly ensure 'update_metadata' is still called passed 'force=True' logic.
    # In the bug scenario, forcing a scan causes update_metadata to be called with mbid_filter=None (update all).
    with patch.object(manager.scanner, 'scan_filesystem', new_callable=AsyncMock) as mock_fs:
        mock_fs.return_value = set()
        
        # Start the Full Scan (Simulating the UI Button Press)
        # We use force=True to ensure it attempts to update metadata for the whole DB,
        # which triggers the "mbid_filter=None" case that caused the InterfaceError.
        task = await manager.start_full(force=True)
        
        # Wait for completion
        await task
        
        # If the bug were still present, 'task' would have raised InterfaceError here,
        # failing the test. Success means the fix works for this scenario.
        assert task.done()
        assert task.exception() is None
