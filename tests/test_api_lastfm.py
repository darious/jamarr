"""
Tests for Last.fm API endpoints.
"""

import pytest
from unittest.mock import patch
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_lastfm_status_not_connected(client: AsyncClient, db, auth_token):
    """Test status endpoint when Last.fm not connected."""
    # Get status
    response = await client.get("/api/lastfm/status")
    assert response.status_code == 200
    
    data = response.json()
    assert data["connected"] is False
    assert data["username"] is None
    assert data["enabled"] is False


@pytest.mark.asyncio
async def test_lastfm_status_connected(client: AsyncClient, db, auth_token):
    """Test status endpoint when Last.fm is connected."""
    # Setup: Add Last.fm credentials to user
    await db.execute(
        """
        UPDATE "user"
        SET lastfm_username = $1,
            lastfm_session_key = $2,
            lastfm_enabled = $3,
            lastfm_connected_at = NOW()
        WHERE username = $1
        """,
        "testuser",
        "session_key_123",
        True
    )
    
    # Get status
    response = await client.get("/api/lastfm/status")
    assert response.status_code == 200
    
    data = response.json()
    assert data["connected"] is True
    assert data["enabled"] is True


@pytest.mark.asyncio
@patch('app.lastfm.get_auth_url')
async def test_lastfm_auth_start(mock_get_auth_url, client: AsyncClient, db, auth_token):
    """Test starting Last.fm authentication."""
    mock_get_auth_url.return_value = "https://www.last.fm/api/auth?token=abc123"
    
    # Start auth
    response = await client.get("/api/lastfm/auth/start")
    assert response.status_code == 200
    
    data = response.json()
    assert "auth_url" in data
    assert data["auth_url"] == "https://www.last.fm/api/auth?token=abc123"


@pytest.mark.asyncio
@patch('app.lastfm.get_session_key')
async def test_lastfm_callback_success(mock_get_session_key, client: AsyncClient, db, auth_token):
    """Test successful Last.fm callback."""
    mock_get_session_key.return_value = ("session_key_123", "lastfm_user")
    
    # Callback
    response = await client.get("/api/lastfm/callback?token=test_token", follow_redirects=False)
    assert response.status_code == 302
    assert "/settings?lastfm=connected" in response.headers["location"]
    
    # Verify database was updated
    user = await db.fetchrow(
        'SELECT lastfm_username, lastfm_enabled FROM "user" WHERE username = $1',
        "testuser"
    )
    assert user["lastfm_username"] == "lastfm_user"
    assert user["lastfm_enabled"] is True


@pytest.mark.asyncio
async def test_lastfm_disconnect(client: AsyncClient, db, auth_token):
    """Test disconnecting Last.fm account."""
    # Setup: Add Last.fm credentials
    await db.execute(
        """
        UPDATE "user"
        SET lastfm_username = $1,
            lastfm_session_key = $2,
            lastfm_enabled = $3
        WHERE username = $4
        """,
        "lastfm_user",
        "session_key_123",
        True,
        "testuser"
    )
    
    # Disconnect
    response = await client.post("/api/lastfm/disconnect")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    
    # Verify database was updated
    user = await db.fetchrow(
        'SELECT lastfm_username, lastfm_session_key, lastfm_enabled FROM "user" WHERE username = $1',
        "testuser"
    )
    assert user["lastfm_username"] is None
    assert user["lastfm_session_key"] is None
    assert user["lastfm_enabled"] is False


@pytest.mark.asyncio
async def test_lastfm_toggle(client: AsyncClient, db, auth_token):
    """Test toggling Last.fm scrobbling."""
    # Setup: Add Last.fm credentials
    await db.execute(
        """
        UPDATE "user"
        SET lastfm_username = $1,
            lastfm_session_key = $2,
            lastfm_enabled = $3
        WHERE username = $4
        """,
        "lastfm_user",
        "session_key_123",
        True,
        "testuser"
    )
    
    # Toggle off
    response = await client.post("/api/lastfm/toggle", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    
    # Verify database
    user = await db.fetchrow(
        'SELECT lastfm_enabled FROM "user" WHERE username = $1',
        "testuser"
    )
    assert user["lastfm_enabled"] is False
    
    # Toggle back on
    response = await client.post("/api/lastfm/toggle", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["enabled"] is True


@pytest.mark.asyncio
async def test_lastfm_toggle_without_connection(client: AsyncClient, db, auth_token):
    """Test toggling when Last.fm not connected should fail."""
    # Try to toggle
    response = await client.post("/api/lastfm/toggle", json={"enabled": True})
    assert response.status_code == 400
    assert "not connected" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_lastfm_endpoints_require_auth(client: AsyncClient, db):
    """Test that Last.fm endpoints require authentication."""
    # Clear cookies to test without auth
    client.cookies.clear()
    
    # Try without login
    response = await client.get("/api/lastfm/status")
    assert response.status_code == 401
    
    response = await client.get("/api/lastfm/auth/start")
    assert response.status_code == 401
    
    response = await client.post("/api/lastfm/disconnect")
    assert response.status_code == 401
    
    response = await client.post("/api/lastfm/toggle", json={"enabled": True})
    assert response.status_code == 401
