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


@pytest.mark.asyncio
async def test_fetch_artist_metadata_uses_client(monkeypatch):
    """Regression: ensure fetch_artist_metadata has a defined client helper and does not NameError."""
    from app.scanner import metadata as md

    async def fake_fanart(client, mbid):
        return {"thumb": None, "background": None}

    monkeypatch.setattr(md, "fetch_fanart_artist_images", fake_fanart)

    # All network flags off except artwork (fanart patched), should not raise NameError
    result = await md.fetch_artist_metadata(
        mbid="test-mbid",
        artist_name="Test Artist",
        fetch_metadata=False,
        fetch_bio=False,
        fetch_artwork=True,
        fetch_links=False,
        fetch_top_tracks=False,
        fetch_singles=False,
        bio_only=False,
        fetch_similar_artists=False,
    )

    assert result["mbid"] == "test-mbid"
    assert result["name"] == "Test Artist"


@pytest.mark.asyncio
async def test_album_artist_conflict_update_no_ambiguous(db):
    """Regression: upsert conflict on artist (album artist path) should not raise ambiguous column errors."""
    mbid = "conflict-mbid"
    # Existing name should be preserved when incoming name is null
    await db.execute('INSERT INTO artist (mbid, name) VALUES ($1, $2)', mbid, "Existing Name")
    await db.execute("""
        INSERT INTO artist (mbid, name, updated_at) VALUES ($1, $2, NOW())
        ON CONFLICT(mbid) DO UPDATE SET name=COALESCE(artist.name, excluded.name)
    """, mbid, None)
    row = await db.fetchrow('SELECT name FROM artist WHERE mbid=$1', mbid)
    assert row["name"] == "Existing Name"
