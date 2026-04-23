import json
import os
import subprocess
import sys

from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
import pytest

from app.security import (
    configure_security_middleware,
    fastapi_docs_config,
    get_client_ip,
    parse_csv_env,
)


def _security_test_app() -> FastAPI:
    app = FastAPI()
    configure_security_middleware(app)

    @app.get("/whoami")
    async def whoami(request: Request):
        return {
            "client_ip": get_client_ip(request),
            "scheme": request.url.scheme,
        }

    return app


def test_parse_csv_env_trims_empty_values(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", " jamarr.darious.co.uk, ,REDACTED_IP ")

    assert parse_csv_env("ALLOWED_HOSTS") == [
        "jamarr.darious.co.uk",
        "REDACTED_IP",
    ]


def test_fastapi_docs_disabled_in_production(monkeypatch):
    monkeypatch.setenv("ENV", "production")

    assert fastapi_docs_config() == {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }


def test_fastapi_docs_enabled_outside_production(monkeypatch):
    monkeypatch.setenv("ENV", "development")

    assert fastapi_docs_config() == {
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "openapi_url": "/openapi.json",
    }


def test_production_app_does_not_register_docs_or_debug_routes():
    script = """
import asyncio
import json
from httpx import ASGITransport, AsyncClient
from app.main import app

async def main():
    paths = sorted({route.path for route in app.routes})
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://REDACTED_IP:8111",
    ) as client:
        statuses = {
            path: (await client.get(path)).status_code
            for path in (
                "/docs",
                "/redoc",
                "/openapi.json",
                "/api/player/debug",
                "/api/player/test_upnp",
                "/art/test",
            )
        }
    print(json.dumps({
        "docs_url": app.docs_url,
        "redoc_url": app.redoc_url,
        "openapi_url": app.openapi_url,
        "paths": paths,
        "statuses": statuses,
    }))

asyncio.run(main())
"""
    env = {
        **os.environ,
        "ENV": "production",
        "DB_NAME": "jamarr_test",
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    data = json.loads(result.stdout)

    assert data["docs_url"] is None
    assert data["redoc_url"] is None
    assert data["openapi_url"] is None
    assert "/api/player/debug" not in data["paths"]
    assert "/api/player/test_upnp" not in data["paths"]
    assert "/art/test" not in data["paths"]
    assert "/api/auth/me" in data["paths"]
    assert data["statuses"] == {
        "/docs": 404,
        "/redoc": 404,
        "/openapi.json": 404,
        "/api/player/debug": 404,
        "/api/player/test_upnp": 404,
        "/art/test": 404,
    }


@pytest.mark.asyncio
async def test_allowed_hosts_are_enforced_when_configured(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", "jamarr.darious.co.uk,REDACTED_IP")
    app = _security_test_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://REDACTED_IP:8111"
    ) as client:
        allowed = await client.get("/whoami", headers={"Host": "REDACTED_IP:8111"})
        blocked = await client.get("/whoami", headers={"Host": "evil.example"})

    assert allowed.status_code == 200
    assert blocked.status_code == 400


@pytest.mark.asyncio
async def test_cors_allows_only_configured_origins(monkeypatch):
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "https://jamarr.darious.co.uk,http://REDACTED_IP:8111",
    )
    app = _security_test_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://REDACTED_IP:8111"
    ) as client:
        allowed = await client.options(
            "/whoami",
            headers={
                "Origin": "https://jamarr.darious.co.uk",
                "Access-Control-Request-Method": "GET",
            },
        )
        blocked = await client.options(
            "/whoami",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed.status_code == 200
    assert (
        allowed.headers["access-control-allow-origin"]
        == "https://jamarr.darious.co.uk"
    )
    assert blocked.status_code == 400
    assert "access-control-allow-origin" not in blocked.headers


@pytest.mark.asyncio
async def test_proxy_headers_are_trusted_only_from_configured_proxy(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_IPS", "REDACTED_IP")
    app = _security_test_app()
    headers = {
        "X-Forwarded-For": "203.0.113.50",
        "X-Forwarded-Proto": "https",
    }

    async with AsyncClient(
        transport=ASGITransport(app=app, client=("REDACTED_IP", 12345)),
        base_url="http://REDACTED_IP:8111",
    ) as client:
        trusted = await client.get("/whoami", headers=headers)

    async with AsyncClient(
        transport=ASGITransport(app=app, client=("REDACTED_IP", 12345)),
        base_url="http://REDACTED_IP:8111",
    ) as client:
        untrusted = await client.get("/whoami", headers=headers)

    assert trusted.json() == {"client_ip": "203.0.113.50", "scheme": "https"}
    assert untrusted.json() == {"client_ip": "REDACTED_IP", "scheme": "http"}
