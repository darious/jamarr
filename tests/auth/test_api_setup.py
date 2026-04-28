"""Integration tests for setup-status and setup endpoints."""
import pytest
from httpx import AsyncClient
import asyncpg


@pytest.mark.asyncio
async def test_setup_status_required_when_empty(client: AsyncClient, db: asyncpg.Connection):
    """setup-status returns setup_required: true when no users exist."""
    response = await client.get("/api/auth/setup-status")
    assert response.status_code == 200
    assert response.json() == {"setup_required": True}


@pytest.mark.asyncio
async def test_setup_status_not_required_when_users_exist(client: AsyncClient, test_user):
    """setup-status returns setup_required: false when users exist."""
    response = await client.get("/api/auth/setup-status")
    assert response.status_code == 200
    assert response.json() == {"setup_required": False}


@pytest.mark.asyncio
async def test_setup_creates_admin_and_returns_token(
    client: AsyncClient, db: asyncpg.Connection
):
    """setup creates the first user as admin and returns access token + user."""
    response = await client.post(
        "/api/auth/setup",
        json={
            "username": "admin_setup",
            "email": "admin@example.com",
            "password": "password123",
            "display_name": "Admin User",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["username"] == "admin_setup"
    assert data["user"]["email"] == "admin@example.com"
    assert data["user"]["display_name"] == "Admin User"
    assert data["user"]["is_admin"] is True

    # Verify refresh cookie was set
    assert "jamarr_refresh" in response.cookies


@pytest.mark.asyncio
async def test_setup_creates_admin_in_database(
    client: AsyncClient, db: asyncpg.Connection
):
    """setup correctly sets is_admin = TRUE in the database."""
    await client.post(
        "/api/auth/setup",
        json={
            "username": "db_admin",
            "email": "dbadmin@example.com",
            "password": "password123",
        },
    )
    user = await db.fetchrow('SELECT * FROM "user" WHERE username = $1', "db_admin")
    assert user is not None
    assert user["is_admin"] is True


@pytest.mark.asyncio
async def test_second_setup_returns_409(client: AsyncClient, db: asyncpg.Connection):
    """A second setup request returns 409 Conflict."""
    # First setup succeeds
    first = await client.post(
        "/api/auth/setup",
        json={
            "username": "first_admin",
            "email": "first@example.com",
            "password": "password123",
        },
    )
    assert first.status_code == 201

    # Second setup must fail
    second = await client.post(
        "/api/auth/setup",
        json={
            "username": "second_admin",
            "email": "second@example.com",
            "password": "password123",
        },
    )
    assert second.status_code == 409
    detail = second.json()
    assert "already been completed" in detail["detail"]


@pytest.mark.asyncio
async def test_setup_rejects_short_password(
    client: AsyncClient, db: asyncpg.Connection
):
    """setup rejects passwords shorter than 8 characters."""
    response = await client.post(
        "/api/auth/setup",
        json={
            "username": "shortpw",
            "email": "short@example.com",
            "password": "abc",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_setup_creates_refresh_session(
    client: AsyncClient, db: asyncpg.Connection
):
    """setup creates a refresh session in the database."""
    response = await client.post(
        "/api/auth/setup",
        json={
            "username": "session_test",
            "email": "session@example.com",
            "password": "password123",
        },
    )
    assert response.status_code == 201
    user_id = response.json()["user"]["id"]

    session_count = await db.fetchval(
        "SELECT COUNT(*) FROM auth_refresh_session WHERE user_id = $1 AND revoked_at IS NULL",
        user_id,
    )
    assert session_count == 1
