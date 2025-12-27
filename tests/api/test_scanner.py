import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_scan_endpoints(client: AsyncClient, db):
    # Mock ScanManager to avoid conflicts and background tasks
    from unittest.mock import AsyncMock, patch
    
    with patch("app.api.scan.ScanManager") as MockSM:
        mock_instance = AsyncMock()
        MockSM.get_instance.return_value = mock_instance
        
        # 1. Trigger Filesystem Scan
        response = await client.post("/api/library/scan", json={"type": "filesystem"})
        assert response.status_code == 200
        assert response.json()["message"] == "Filesystem scan started"
        
        # 2. Trigger Metadata Scan
        response = await client.post("/api/library/scan", json={"type": "metadata"})
        assert response.status_code == 200
        assert response.json()["message"] == "Metadata update started"
    
    # 3. Status
    # Status endpoint uses ScanManager.get_instance().status
    # We need to maintain the mock or check if it returns valid format
    # But endpoint might be importing ScanManager directly?
    # app.api.scan.ScanManager vs from app.scanner.scan_manager import ScanManager
    # Depends on how app.api.scan imports it.
    # Logic: app.api.scan imports ScanManager.
    # The patch above patches 'app.api.scan.ScanManager'.
    
    # 3. Status
    response = await client.get("/api/library/status")
    # Without mock, it returns real status (which is fine if we stopped scans)
    assert response.status_code == 200
    
    # 4. Cancel
    response = await client.post("/api/library/cancel")
    assert response.status_code == 200
