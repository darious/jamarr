import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_stream_missing(auth_client: AsyncClient):
    # Stream non-existent track
    response = await auth_client.get("/api/stream/99999")
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_art_missing(auth_client: AsyncClient):
    # Art non-existent
    response = await auth_client.get("/api/art/file/0000000000000000000000000000000000000000")
    assert response.status_code == 404

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as unauth_client:
        unauth_response = await unauth_client.get("/api/art/file/0000000000000000000000000000000000000000")
        assert unauth_response.status_code == 404

@pytest.mark.asyncio
async def test_art_test_endpoint(auth_client: AsyncClient):
    # UPnP test art
    response = await auth_client.get("/api/art/test")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
