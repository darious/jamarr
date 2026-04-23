import logging
import uuid

import pytest
from httpx import AsyncClient

from app.auth import hash_password


async def _login_user(client: AsyncClient, db, is_admin: bool) -> str:
    username = f"monitor_{uuid.uuid4().hex}"
    password = "password123"
    await db.execute(
        """
        INSERT INTO "user" (username, email, password_hash, display_name, is_admin, created_at)
        VALUES ($1, $2, $3, $4, $5, NOW())
        """,
        username,
        f"{username}@example.com",
        hash_password(password),
        username,
        is_admin,
    )
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_monitoring_endpoints_require_admin(client: AsyncClient, db):
    token = await _login_user(client, db, is_admin=False)

    response = await client.get(
        "/api/monitoring/summary",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin privileges required"


@pytest.mark.asyncio
async def test_admin_can_view_redacted_security_logs(client: AsyncClient, db):
    token = await _login_user(client, db, is_admin=True)
    logging.getLogger("app.security.audit").warning(
        "monitoring-test Authorization: Bearer SECRET_BEARER "
        "access_token=SECRET_ACCESS lastfm_session_key=SECRET_LASTFM"
    )

    summary = await client.get(
        "/api/monitoring/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    log_response = await client.get(
        "/api/monitoring/logs?file=security&lines=50",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert summary.status_code == 200
    assert log_response.status_code == 200
    assert any(log["key"] == "security" for log in summary.json()["logs"])
    assert any("monitoring-test" in alert for alert in summary.json()["alerts"])

    text = "\n".join(log_response.json()["lines"])
    assert "monitoring-test" in text
    assert "SECRET_BEARER" not in text
    assert "SECRET_ACCESS" not in text
    assert "SECRET_LASTFM" not in text
    assert "[REDACTED]" in text


@pytest.mark.asyncio
async def test_monitoring_rejects_unknown_log_files(client: AsyncClient, db):
    token = await _login_user(client, db, is_admin=True)

    response = await client.get(
        "/api/monitoring/logs?file=../backend&lines=10",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
