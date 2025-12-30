import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.scanner.scan_manager import ScanManager


@pytest.mark.asyncio
async def test_scan_manager_uses_metadata_coordinator_without_db_arg():
    """
    Regression: MetadataCoordinator should be constructed without a db arg
    to avoid multiple values for progress_cb when running full scans.
    """
    manager = ScanManager()
    manager._stop_event = asyncio.Event()
    manager._current_task = None
    manager.scanner = MagicMock()
    manager.scanner.scan_filesystem = AsyncMock(return_value={("123", "Test Artist")})
    manager.scanner.get_artists_in_path = AsyncMock(return_value={"123"})
    manager.scanner.prune_library = AsyncMock()

    fake_db = AsyncMock()

    async def fake_get_db():
        yield fake_db

    with patch("app.scanner.scan_manager.get_db", return_value=fake_get_db()), \
         patch("app.scanner.scan_manager.MetadataCoordinator") as MC:
        mc_instance = AsyncMock()
        MC.return_value = mc_instance

        await manager._run_full("/tmp", False, fetch_metadata=True, prune=False)

        MC.assert_called_once()
        assert "progress_cb" in MC.call_args.kwargs
        assert len(MC.call_args.args) == 0
        mc_instance.update_metadata.assert_awaited()
