import pytest
from httpx import AsyncClient

from app.auth import hash_password


async def _login_user(client: AsyncClient, db, username: str, is_admin: bool) -> str:
    password = "password123"
    await db.execute(
        'DELETE FROM "user" WHERE username = $1',
        username,
    )
    await db.fetchrow(
        """
        INSERT INTO "user" (username, email, password_hash, display_name, is_admin, created_at)
        VALUES ($1, $2, $3, $4, $5, NOW())
        RETURNING *
        """,
        username,
        f"{username}@example.com",
        hash_password(password),
        username.title(),
        is_admin,
    )
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_normal_user_blocked_from_admin_endpoints(client: AsyncClient, db):
    token = await _login_user(client, db, "normal_admin_blocked", False)
    headers = {"Authorization": f"Bearer {token}"}

    requests = [
        ("post", "/api/library/scan", {"json": {"type": "filesystem", "path": "/tmp"}}),
        ("post", "/api/library/cancel", {}),
        ("post", "/api/scan/missing", {}),
        ("post", "/api/library/optimize", {}),
        ("post", "/api/download/pearlarr", {"json": {"mbid": "test-mbid"}}),
        ("get", "/api/media-quality/summary", {}),
        ("get", "/api/scheduler/jobs", {}),
        ("get", "/api/player/debug", {}),
        ("post", "/api/player/add_manual", {"json": {"ip": "127.0.0.1"}}),
        ("get", "/api/player/test_upnp", {}),
        ("post", "/api/charts/refresh", {}),
    ]

    for method, url, kwargs in requests:
        response = await getattr(client, method)(url, headers=headers, **kwargs)
        assert response.status_code == 403, f"{method.upper()} {url}"
        assert response.json()["detail"] == "Admin privileges required"


@pytest.mark.asyncio
async def test_normal_user_can_access_playback_and_renderer_endpoints(
    client: AsyncClient, db
):
    token = await _login_user(client, db, "normal_playback_allowed", False)
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Jamarr-Client-Id": "normal-playback-client",
    }
    track = {
        "id": 1,
        "title": "Allowed",
        "artist": "Artist",
        "album": "Album",
        "duration_seconds": 120,
    }

    allowed_requests = [
        ("get", "/api/renderers?refresh=true", {}),
        ("get", "/api/scan-status", {}),
        ("post", "/api/player/renderer", {"json": {"renderer_id": "local:normal-playback-client"}}),
        ("post", "/api/player/queue", {"json": {"queue": [track], "start_index": 0}}),
        ("post", "/api/player/queue/append", {"json": {"tracks": [track]}}),
        ("post", "/api/player/queue/reorder", {"json": {"queue": [track]}}),
        ("post", "/api/player/index", {"json": {"index": 0}}),
        ("post", "/api/player/pause", {}),
        ("post", "/api/player/resume", {}),
        ("post", "/api/player/volume", {"json": {"percent": 50}}),
        ("post", "/api/player/seek", {"json": {"seconds": 10}}),
        ("post", "/api/player/queue/clear", {}),
    ]

    for method, url, kwargs in allowed_requests:
        response = await getattr(client, method)(url, headers=headers, **kwargs)
        assert response.status_code != 403, f"{method.upper()} {url}"

    play_response = await client.post(
        "/api/player/play",
        json={"track_id": 1},
        headers=headers,
    )
    assert play_response.status_code == 404
    assert play_response.json()["detail"] == "Track not found"


@pytest.mark.asyncio
async def test_admin_user_can_access_admin_read_endpoint(client: AsyncClient, db):
    token = await _login_user(client, db, "admin_allowed", True)
    response = await client.get(
        "/api/scheduler/jobs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
