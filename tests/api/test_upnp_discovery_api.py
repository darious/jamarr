"""Manual add, subnet-scan cancel and UPnP diagnostics routes (issue #315)."""

import pytest
from httpx import AsyncClient

from app.services.renderer.contracts import RendererDevice


class FakeManager:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel_subnet_scan(self) -> bool:
        self.cancelled = True
        return True

    def diagnostics(self) -> dict:
        return {"listener": "running", "search_targets": ["x"], "devices": []}


class FakeUpnpBackend:
    kind = "upnp"

    def __init__(self) -> None:
        self.manager = FakeManager()
        self.addresses: list[str] = []

    async def add_manual(self, address: str):
        self.addresses.append(address)
        if address.endswith(".10") or address.startswith("http"):
            return RendererDevice(
                renderer_id="upnp:uuid:added",
                kind="upnp",
                native_id="uuid:added",
                udn="uuid:added",
                name="Added Speaker",
                ip="192.0.2.10",
            )
        return None

    async def list_devices(self):
        return []


@pytest.fixture
def fake_upnp(monkeypatch):
    import app.api.player as player_api

    backend = FakeUpnpBackend()
    monkeypatch.setitem(player_api.renderer_orchestrator.registry.backends, "upnp", backend)
    return backend


@pytest.mark.asyncio
async def test_add_manual_returns_registered_renderer(auth_client: AsyncClient, fake_upnp):
    response = await auth_client.post("/api/player/add_manual", json={"ip": " 192.0.2.10 "})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "found"
    assert body["renderer"]["renderer_id"] == "upnp:uuid:added"
    assert fake_upnp.addresses == ["192.0.2.10"]


@pytest.mark.asyncio
async def test_add_manual_accepts_description_url(auth_client: AsyncClient, fake_upnp):
    url = "http://192.0.2.10:49152/description.xml"
    response = await auth_client.post("/api/player/add_manual", json={"url": url})
    assert response.status_code == 200
    assert fake_upnp.addresses == [url]


@pytest.mark.asyncio
async def test_add_manual_404_when_nothing_registered(auth_client: AsyncClient, fake_upnp):
    response = await auth_client.post("/api/player/add_manual", json={"ip": "192.0.2.99"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_add_manual_400_without_address(auth_client: AsyncClient, fake_upnp):
    response = await auth_client.post("/api/player/add_manual", json={})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_cancel_scan_and_diagnostics(auth_client: AsyncClient, fake_upnp):
    response = await auth_client.post("/api/scan/cancel")
    assert response.status_code == 200
    assert response.json() == {"cancelled": True}
    assert fake_upnp.manager.cancelled

    response = await auth_client.get("/api/player/upnp/diagnostics")
    assert response.status_code == 200
    assert response.json()["listener"] == "running"
