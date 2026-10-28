"""Manual add, subnet-scan cancel and UPnP diagnostics routes (issue #315)."""

import pytest
from httpx import AsyncClient

from app.services.renderer.contracts import RendererDevice


class FakeManager:
    def __init__(self) -> None:
        self.cancelled = False
        self.sweeps = 0

    def start_subnet_scan(self) -> bool:
        self.sweeps += 1
        return True

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

    async def discover(self, refresh: bool = False):
        # Discovery saves renderers on connections of its own; the request
        # must not be holding one while it runs.
        self.held_during_discover = _connections_in_use()
        return []


def _connections_in_use() -> int:
    from app.db import get_pool

    pool = get_pool()
    return pool.get_size() - pool.get_idle_size()


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


@pytest.mark.asyncio
async def test_refresh_holds_no_connection_and_does_not_sweep(
    auth_client: AsyncClient, fake_upnp, monkeypatch
):
    import app.api.player as player_api

    monkeypatch.setattr(player_api.renderer_orchestrator.registry, "backends", {"upnp": fake_upnp})
    baseline = _connections_in_use()  # e.g. the test's own db fixture

    response = await auth_client.get(
        "/api/renderers?refresh=true", headers={"X-Jamarr-Client-Id": "c1"}
    )

    assert response.status_code == 200
    assert response.json()[0]["renderer_id"] == "local:c1"
    assert fake_upnp.held_during_discover == baseline
    assert fake_upnp.manager.sweeps == 0


@pytest.mark.asyncio
async def test_subnet_sweep_is_an_explicit_admin_action(auth_client: AsyncClient, fake_upnp):
    response = await auth_client.post("/api/scan/subnet")
    assert response.status_code == 200
    assert response.json() == {"started": True}
    assert fake_upnp.manager.sweeps == 1


@pytest.mark.asyncio
async def test_migrate_renderer_udn_repoints_saved_settings(db):
    """Root-UDN rows from older installs move to the embedded endpoint's UDN."""
    from app.upnp import UPnPManager

    old, new = "uuid:root-0001", "uuid:zone-0001"
    for udn, enabled in ((old, False), (new, True)):
        await db.execute(
            """
            INSERT INTO renderer (udn, kind, native_id, renderer_id, friendly_name, enabled_by_default)
            VALUES ($1, 'upnp', $1, 'upnp:' || $1, 'Amp', $2)
            """,
            udn,
            enabled,
        )
    await db.execute(
        """
        INSERT INTO client_session (client_id, active_renderer_udn, active_renderer_id, last_seen_at)
        VALUES ('migrate-client', $1, 'upnp:' || $1, NOW())
        """,
        old,
    )
    await db.execute(
        "INSERT INTO renderer_state (renderer_udn, queue, current_index) VALUES ($1, '[1]', 0)",
        old,
    )

    manager = UPnPManager()
    manager.renderers[old] = {"udn": old}
    manager.active_renderer = old
    await manager.migrate_renderer_udn(old, new)

    assert await db.fetchval("SELECT count(*) FROM renderer WHERE udn = $1", old) == 0
    assert await db.fetchval("SELECT enabled_by_default FROM renderer WHERE udn = $1", new) is False
    session = await db.fetchrow(
        "SELECT active_renderer_udn, active_renderer_id FROM client_session WHERE client_id = 'migrate-client'"
    )
    assert tuple(session) == (new, f"upnp:{new}")
    assert await db.fetchval("SELECT queue FROM renderer_state WHERE renderer_udn = $1", new) == "[1]"
    assert await db.fetchval("SELECT count(*) FROM renderer_state WHERE renderer_udn = $1", old) == 0
    assert old not in manager.renderers
    assert manager.active_renderer == new
