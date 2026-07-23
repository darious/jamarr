"""A renderer that disappears must not stay selected forever.

Regression: a Cast device that vanished stayed the active renderer for a
client_id, so every /api/player/index report returned 409 — including reports
from clients that were playing locally.
"""

import pytest

from app.services.renderer.contracts import RendererDevice
from app.services.renderer.orchestrator import RendererOrchestrator
from app.services.renderer.registry import RendererRegistry

GONE = "cast:2e6bc8d0-3dc6-0a37-89bf-0d17061f6604"
ALIVE = "cast:1111-2222"


class FakeCastBackend:
    """Cast backend that only knows about ALIVE."""

    def __init__(self, devices=None) -> None:
        self._devices = devices if devices is not None else [
            RendererDevice(
                renderer_id=ALIVE,
                kind="cast",
                native_id="1111-2222",
                name="Kitchen",
            )
        ]

    async def list_devices(self) -> list[RendererDevice]:
        return list(self._devices)

    async def pause(self, renderer_id: str) -> None:
        # Mirrors CastRendererBackend._get_cast: unknown device -> ValueError.
        if not any(device.renderer_id == renderer_id for device in self._devices):
            raise ValueError(f"Cast renderer {renderer_id} not found")


class ExplodingCastBackend(FakeCastBackend):
    async def list_devices(self):
        raise RuntimeError("discovery is down")


class FakeDb:
    """Captures executed SQL and reports an asyncpg-style command tag."""

    def __init__(self, rows_updated: int = 1) -> None:
        self.rows_updated = rows_updated
        self.calls: list[tuple[str, tuple]] = []

    async def execute(self, sql: str, *args) -> str:
        self.calls.append((sql, args))
        return f"UPDATE {self.rows_updated}"

    async def fetchrow(self, _sql: str, *_args):
        return None


def make_orchestrator(backend=None) -> RendererOrchestrator:
    registry = RendererRegistry()
    registry.backends["cast"] = backend or FakeCastBackend()
    return RendererOrchestrator(registry=registry)


@pytest.mark.asyncio
async def test_renderer_available_false_for_vanished_device():
    orchestrator = make_orchestrator()

    assert await orchestrator._renderer_available(ALIVE) is True
    assert await orchestrator._renderer_available(GONE) is False


@pytest.mark.asyncio
async def test_renderer_available_true_when_backend_missing_entirely():
    orchestrator = make_orchestrator()

    # No 'upnp' backend registered — treat as unavailable, not crash.
    assert await orchestrator._renderer_available("upnp:uuid:whatever") is False


@pytest.mark.asyncio
async def test_flaky_discovery_does_not_clear_the_renderer():
    """A backend erroring is transient; only absence from a good listing counts."""
    orchestrator = make_orchestrator(ExplodingCastBackend())

    assert await orchestrator._renderer_available(GONE) is True


@pytest.mark.asyncio
async def test_clear_stale_renderer_resets_sessions_to_local():
    orchestrator = make_orchestrator()
    db = FakeDb(rows_updated=2)

    cleared = await orchestrator.clear_stale_renderer(db, GONE, ValueError("not found"))

    assert cleared == 2
    sql, args = db.calls[0]
    assert "UPDATE client_session" in sql
    assert "'local:' || client_id" in sql
    assert args == (GONE,)


@pytest.mark.asyncio
async def test_clear_stale_renderer_ignores_local_renderers():
    orchestrator = make_orchestrator()
    db = FakeDb()

    assert await orchestrator.clear_stale_renderer(db, "local:abc") == 0
    assert db.calls == []


@pytest.mark.asyncio
async def test_heal_clears_active_renderer_when_device_is_gone(monkeypatch):
    orchestrator = make_orchestrator()
    db = FakeDb()
    monkeypatch.setattr(
        orchestrator, "get_active", lambda _db, _cid: _resolved((GONE, GONE))
    )

    await orchestrator._heal_if_renderer_gone(db, "client-1", ValueError("not found"))

    assert db.calls, "expected the stale renderer to be cleared"


@pytest.mark.asyncio
async def test_heal_leaves_a_live_renderer_alone(monkeypatch):
    orchestrator = make_orchestrator()
    db = FakeDb()
    monkeypatch.setattr(
        orchestrator, "get_active", lambda _db, _cid: _resolved((ALIVE, ALIVE))
    )

    await orchestrator._heal_if_renderer_gone(db, "client-1", ValueError("boom"))

    assert db.calls == []


@pytest.mark.asyncio
async def test_heal_leaves_local_playback_alone(monkeypatch):
    orchestrator = make_orchestrator()
    db = FakeDb()
    monkeypatch.setattr(
        orchestrator,
        "get_active",
        lambda _db, _cid: _resolved(("local:client-1", "local:client-1")),
    )

    await orchestrator._heal_if_renderer_gone(db, "client-1", ValueError("boom"))

    assert db.calls == []


@pytest.mark.asyncio
async def test_control_call_heals_then_still_raises(monkeypatch):
    """The decorator clears the session but keeps the 409 contract intact."""
    orchestrator = make_orchestrator()
    db = FakeDb()
    monkeypatch.setattr(
        orchestrator, "get_active", lambda _db, _cid: _resolved((GONE, GONE))
    )

    with pytest.raises(ValueError):
        await orchestrator.pause(db, "client-1")

    assert any(
        "UPDATE client_session" in sql for sql, _ in db.calls
    ), "expected the stale renderer to be cleared before raising"


async def _resolved(value):
    return value
