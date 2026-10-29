"""Renderer capability contract over the API."""

import pytest
from httpx import AsyncClient


NEW_CAPABILITY_KEYS = {
    "queue_ownership",
    "queue_operations",
    "can_stage_next",
    "pairing",
    "has_credentials",
    "output",
}


@pytest.mark.asyncio
async def test_renderers_expose_optional_capabilities(auth_client: AsyncClient):
    response = await auth_client.get("/api/renderers", headers={"X-Jamarr-Client-Id": "caps"})

    assert response.status_code == 200, response.text
    rows = response.json()
    local = next(r for r in rows if r["kind"] == "local")
    assert NEW_CAPABILITY_KEYS <= set(local["capabilities"])
    assert local["capabilities"]["queue_ownership"] == "server"
    assert local["capabilities"]["can_stage_next"] is False
    assert local["capabilities"]["can_play"] is True
