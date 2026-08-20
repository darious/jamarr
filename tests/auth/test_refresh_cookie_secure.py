"""The refresh cookie's Secure attribute must follow the request's scheme.

A Secure cookie handed out over plain HTTP is never sent back, so the client
looks logged in until its access token expires and then can never refresh.
"""
import pytest
from httpx import AsyncClient

from app.api import auth as auth_api


def _cookie_header(response) -> str:
    for name, value in response.headers.multi_items():
        if name.lower() == "set-cookie" and value.startswith("jamarr_refresh="):
            return value
    raise AssertionError("no jamarr_refresh cookie in response")


@pytest.mark.asyncio
async def test_plain_http_login_cookie_is_not_secure(client: AsyncClient, test_user):
    response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"},
    )
    assert response.status_code == 200
    assert "secure" not in _cookie_header(response).lower()

    # ...and the client can therefore actually use it.
    assert (await client.post("/api/auth/refresh")).status_code == 200


@pytest.mark.asyncio
async def test_forwarded_https_login_cookie_is_secure(client: AsyncClient, test_user):
    response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"},
        headers={"X-Forwarded-Proto": "https"},
    )
    assert response.status_code == 200
    assert "Secure" in _cookie_header(response)


@pytest.mark.asyncio
async def test_env_override_pins_secure(client: AsyncClient, test_user, monkeypatch):
    monkeypatch.setattr(auth_api, "REFRESH_COOKIE_SECURE", True)
    response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"},
    )
    assert response.status_code == 200
    assert "Secure" in _cookie_header(response)


@pytest.mark.asyncio
async def test_env_override_can_disable_secure(client: AsyncClient, test_user, monkeypatch):
    monkeypatch.setattr(auth_api, "REFRESH_COOKIE_SECURE", False)
    response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"},
        headers={"X-Forwarded-Proto": "https"},
    )
    assert response.status_code == 200
    assert "secure" not in _cookie_header(response).lower()


@pytest.mark.asyncio
async def test_rotated_cookie_follows_the_same_rule(client: AsyncClient, test_user):
    login = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"},
    )
    assert login.status_code == 200

    plain = await client.post("/api/auth/refresh")
    assert plain.status_code == 200
    assert "secure" not in _cookie_header(plain).lower()

    forwarded = await client.post(
        "/api/auth/refresh", headers={"X-Forwarded-Proto": "https"}
    )
    assert forwarded.status_code == 200
    assert "Secure" in _cookie_header(forwarded)
