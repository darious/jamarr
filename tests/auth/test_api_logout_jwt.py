"""Integration tests for JWT logout endpoints."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_logout_revokes_refresh_session(client: AsyncClient, test_user, db):
    """Test that logout revokes the refresh session in database."""
    # Login to get refresh cookie
    login_response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"}
    )
    assert login_response.status_code == 200
    
    # Verify session exists and is active
    active_count = await db.fetchval(
        "SELECT COUNT(*) FROM auth_refresh_session WHERE user_id = $1 AND revoked_at IS NULL",
        test_user["id"]
    )
    assert active_count == 1
    
    # Logout
    logout_response = await client.post("/api/auth/logout")
    assert logout_response.status_code == 200
    
    # Verify session is revoked
    active_count_after = await db.fetchval(
        "SELECT COUNT(*) FROM auth_refresh_session WHERE user_id = $1 AND revoked_at IS NULL",
        test_user["id"]
    )
    assert active_count_after == 0


@pytest.mark.asyncio
async def test_logout_clears_cookie(client: AsyncClient, test_user):
    """Test that logout clears the refresh cookie."""
    # Login to get refresh cookie
    login_response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"}
    )
    assert login_response.status_code == 200
    assert "jamarr_refresh" in login_response.cookies
    
    # Logout
    logout_response = await client.post("/api/auth/logout")
    assert logout_response.status_code == 200
    
    # Cookie should be cleared (empty or max-age=0)
    # httpx represents cleared cookies differently, check if it's gone or empty
    refresh_cookie = logout_response.cookies.get("jamarr_refresh", "")
    assert refresh_cookie == "" or logout_response.headers.get("set-cookie", "").find("Max-Age=0") > -1


@pytest.mark.asyncio
async def test_logout_after_refresh_fails(client: AsyncClient, test_user):
    """Test that using refresh token after logout fails."""
    # Login
    login_response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"}
    )
    assert login_response.status_code == 200
    
    # Logout
    logout_response = await client.post("/api/auth/logout")
    assert logout_response.status_code == 200
    
    # Try to refresh (should fail)
    refresh_response = await client.post("/api/auth/refresh")
    assert refresh_response.status_code == 401


@pytest.mark.asyncio
async def test_logout_all_revokes_all_sessions(client: AsyncClient, test_user, db):
    """Test that logout-all revokes all user sessions."""
    # Create multiple sessions by logging in from different "devices"
    sessions = []
    for i in range(3):
        response = await client.post(
            "/api/auth/login",
            json={"username": "testuser_jwt", "password": "password123"}
        )
        assert response.status_code == 200
        sessions.append(response.json()["access_token"])
    
    # Verify 3 active sessions
    active_count = await db.fetchval(
        "SELECT COUNT(*) FROM auth_refresh_session WHERE user_id = $1 AND revoked_at IS NULL",
        test_user["id"]
    )
    assert active_count == 3
    
    # Logout all using one of the access tokens
    logout_all_response = await client.post(
        "/api/auth/logout-all",
        headers={"Authorization": f"Bearer {sessions[0]}"}
    )
    assert logout_all_response.status_code == 200
    
    # Verify all sessions revoked
    active_count_after = await db.fetchval(
        "SELECT COUNT(*) FROM auth_refresh_session WHERE user_id = $1 AND revoked_at IS NULL",
        test_user["id"]
    )
    assert active_count_after == 0
    
    # Response should indicate how many sessions were revoked
    data = logout_all_response.json()
    assert data.get("sessions_revoked") == 3


@pytest.mark.asyncio
async def test_logout_all_requires_jwt(client: AsyncClient):
    """Test that logout-all requires valid JWT."""
    # Try without authorization header
    response = await client.post("/api/auth/logout-all")
    assert response.status_code == 401
    
    # Try with invalid token
    response = await client.post(
        "/api/auth/logout-all",
        headers={"Authorization": "Bearer invalid.token.here"}
    )
    assert response.status_code == 401
