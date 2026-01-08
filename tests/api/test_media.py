import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_stream_missing(client: AsyncClient):
    # Stream non-existent track
    response = await client.get("/api/stream/99999")
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_art_missing(client: AsyncClient):
    # Art non-existent
    response = await client.get("/api/art/file/0000000000000000000000000000000000000000")
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_art_test_endpoint(client: AsyncClient):
    # UPnP test art
    response = await client.get("/api/art/test")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
