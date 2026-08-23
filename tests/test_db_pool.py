"""Regression tests for the pool exhaustion that took prod down for 25 hours.

The pool was drained by connections that were checked out and never returned,
and because `acquire()` had no timeout the symptom was an infinite hang rather
than an error: static assets kept serving while every DB-backed route blocked
forever, with nothing in the logs and monitoring still green.

These cover the three properties that stop that recurring:
  * a handler shares the connection its auth dependency already holds, instead
    of taking a second one and deadlocking the pool against itself,
  * `db_conn()` gives the connection back even when the body raises or breaks,
  * an exhausted pool answers 503 instead of hanging.
"""
import asyncio

import asyncpg
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

import app.db as app_db
from app.db import db_conn, get_db


def _free(pool: asyncpg.Pool) -> int:
    """Connections the pool could hand out right now."""
    return pool.get_max_size() - (pool.get_size() - pool.get_idle_size())


async def test_db_conn_releases_after_exception():
    pool = app_db.get_pool()
    before = _free(pool)

    with pytest.raises(RuntimeError):
        async with db_conn() as conn:
            await conn.fetchval("SELECT 1")
            raise RuntimeError("boom")

    assert _free(pool) == before


async def test_db_conn_releases_on_early_return():
    """The old `async for db in get_db()` leaked exactly here."""
    pool = app_db.get_pool()
    before = _free(pool)

    async def bail_out():
        async with db_conn() as conn:
            await conn.fetchval("SELECT 1")
            return "done"

    assert await bail_out() == "done"
    assert _free(pool) == before


async def test_nested_dependencies_share_one_connection():
    """A handler and its auth dependency must not hold two connections.

    Both declare Depends(get_db); FastAPI caches per request, so the handler
    gets the same connection the dependency already acquired. Taking a second
    one is what deadlocked the pool: every in-flight request held one and
    waited on another that could only be freed by a request that would never
    finish.
    """
    probe = FastAPI()

    async def fake_auth(conn: asyncpg.Connection = Depends(get_db)):
        # Stands in for get_current_user_jwt, which looks the user up here.
        await conn.fetchval("SELECT 1")
        return conn

    @probe.get("/probe")
    async def probe_route(
        auth_conn=Depends(fake_auth),
        conn: asyncpg.Connection = Depends(get_db),
    ):
        return {"shared": auth_conn is conn}

    pool = app_db.get_pool()
    before = _free(pool)

    transport = ASGITransport(app=probe)
    async with AsyncClient(transport=transport, base_url="http://probe") as client:
        response = await client.get("/probe")

    assert response.status_code == 200
    assert response.json() == {"shared": True}
    assert _free(pool) == before


async def test_exhausted_pool_returns_503_instead_of_hanging(monkeypatch):
    """The whole point: fail loudly and fast rather than block forever."""
    monkeypatch.setattr(app_db, "DB_POOL_ACQUIRE_TIMEOUT", 0.25)

    probe = FastAPI()

    @probe.get("/probe")
    async def probe_route(conn: asyncpg.Connection = Depends(get_db)):
        return {"status": "ok"}

    pool = app_db.get_pool()
    hogged = [await pool.acquire() for _ in range(_free(pool))]
    try:
        transport = ASGITransport(app=probe)
        async with AsyncClient(transport=transport, base_url="http://probe") as client:
            response = await asyncio.wait_for(client.get("/probe"), timeout=10)
    finally:
        for conn in hogged:
            await pool.release(conn)

    assert response.status_code == 503
    assert "busy" in response.json()["detail"].lower()

    # And the pool recovers once the hogs let go.
    async with db_conn() as conn:
        assert await conn.fetchval("SELECT 1") == 1
