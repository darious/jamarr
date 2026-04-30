import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_phase1_player_state_includes_renderer_id_fields(auth_client: AsyncClient):
    response = await auth_client.get(
        "/api/player/state",
        headers={"X-Jamarr-Client-Id": "phase1-client"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["renderer"] == "local:phase1-client"
    assert data["renderer_id"] == "local:phase1-client"
    assert data["renderer_kind"] == "local"


@pytest.mark.asyncio
async def test_phase1_set_renderer_accepts_renderer_id_and_keeps_udn_compat(
    auth_client: AsyncClient,
    db,
):
    response = await auth_client.post(
        "/api/player/renderer",
        json={"renderer_id": "upnp:uuid:phase1"},
        headers={"X-Jamarr-Client-Id": "phase1-client"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["active"] == "uuid:phase1"
    assert response.json()["renderer_id"] == "upnp:uuid:phase1"

    row = await db.fetchrow(
        """
        SELECT active_renderer_udn, active_renderer_id
        FROM client_session
        WHERE client_id = 'phase1-client'
        """
    )
    assert row["active_renderer_udn"] == "uuid:phase1"
    assert row["active_renderer_id"] == "upnp:uuid:phase1"


@pytest.mark.asyncio
async def test_phase1_renderers_include_unified_fields(auth_client: AsyncClient):
    response = await auth_client.get(
        "/api/renderers",
        headers={"X-Jamarr-Client-Id": "phase1-client"},
    )

    assert response.status_code == 200
    local = response.json()[0]
    assert local["renderer_id"] == "local:phase1-client"
    assert local["kind"] == "local"
    assert local["native_id"] == "phase1-client"
    assert local["udn"] == "local:phase1-client"
    assert local["type"] == "local"
