from __future__ import annotations

import asyncio

import httpx
import pytest

from jamarr_tui.api.client import AuthError, JamarrClient


def _client_with_transport(
    handler: httpx.MockTransport,
) -> JamarrClient:
    return JamarrClient("https://jamarr.test", transport=handler)


@pytest.mark.asyncio
async def test_request_refreshes_and_retries_after_401() -> None:
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers.get("authorization")))
        if request.url.path == "/api/auth/refresh":
            return httpx.Response(200, json={"access_token": "new-token"})
        if request.headers.get("authorization") == "Bearer new-token":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(401, json={"detail": "expired"})

    client = _client_with_transport(httpx.MockTransport(handler))
    client._access_token = "old-token"  # noqa: SLF001

    try:
        data = await client._request("GET", "/api/example")  # noqa: SLF001
        assert data == {"ok": True}
        assert client._access_token == "new-token"  # noqa: SLF001
        assert seen == [
            ("/api/example", "Bearer old-token"),
            ("/api/auth/refresh", None),
            ("/api/example", "Bearer new-token"),
        ]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_request_raises_auth_error_when_refresh_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/refresh":
            return httpx.Response(401, json={"detail": "expired"})
        return httpx.Response(401, json={"detail": "expired"})

    client = _client_with_transport(httpx.MockTransport(handler))
    client._access_token = "old-token"  # noqa: SLF001

    try:
        with pytest.raises(AuthError):
            await client._request("GET", "/api/example")  # noqa: SLF001
        assert client._access_token is None  # noqa: SLF001
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_concurrent_401s_share_one_refresh_call() -> None:
    refresh_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal refresh_count
        if request.url.path == "/api/auth/refresh":
            refresh_count += 1
            await asyncio.sleep(0.01)
            return httpx.Response(200, json={"access_token": "new-token"})
        if request.headers.get("authorization") == "Bearer new-token":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(401, json={"detail": "expired"})

    client = _client_with_transport(httpx.MockTransport(handler))
    client._access_token = "old-token"  # noqa: SLF001

    try:
        results = await asyncio.gather(
            client._request("GET", "/api/one"),  # noqa: SLF001
            client._request("GET", "/api/two"),  # noqa: SLF001
        )
        assert results == [{"ok": True}, {"ok": True}]
        assert refresh_count == 1
    finally:
        await client.aclose()
