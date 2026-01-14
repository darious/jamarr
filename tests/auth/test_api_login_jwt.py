"""Integration tests for JWT login endpoint."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login_returns_access_token(client: AsyncClient, test_user):
    """Test that login returns access token in JSON response."""
    response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Should have access_token field
    assert "access_token" in data
    assert isinstance(data["access_token"], str)
    assert len(data["access_token"]) > 0
    
    # Should have token_type
    assert data.get("token_type") == "bearer"
    
    # Should have user data
    assert "user" in data
    assert data["user"]["id"] == test_user["id"]
    assert data["user"]["username"] == test_user["username"]


@pytest.mark.asyncio
async def test_login_sets_refresh_cookie(client: AsyncClient, test_user):
    """Test that login sets refresh token cookie."""
    response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"}
    )
    
    assert response.status_code == 200
    
    # Should have refresh cookie
    assert "jamarr_refresh" in response.cookies
    refresh_token = response.cookies["jamarr_refresh"]
    assert len(refresh_token) > 0


@pytest.mark.asyncio
async def test_login_creates_refresh_session(client: AsyncClient, test_user, db):
    """Test that login creates refresh session in database."""
    response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"}
    )
    
    assert response.status_code == 200
    
    # Check database for refresh session
    session_count = await db.fetchval(
        "SELECT COUNT(*) FROM auth_refresh_session WHERE user_id = $1 AND revoked_at IS NULL",
        test_user["id"]
    )
    
    assert session_count == 1


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: AsyncClient, test_user):
    """Test that login with wrong password returns 401."""
    response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "wrongpassword"}
    )
    
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient):
    """Test that login with non-existent user returns 401."""
    response = await client.post(
        "/api/auth/login",
        json={"username": "nonexistent", "password": "password123"}
    )
    
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_updates_last_login(client: AsyncClient, test_user, db):
    """Test that login updates last_login_at timestamp."""
    # Get initial last_login_at
    initial_login = test_user.get("last_login_at")
    
    response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"}
    )
    
    assert response.status_code == 200
    
    # Check updated timestamp
    user = await db.fetchrow('SELECT * FROM "user" WHERE id = $1', test_user["id"])
    assert user["last_login_at"] is not None
    if initial_login:
        assert user["last_login_at"] > initial_login


@pytest.mark.asyncio
async def test_login_rate_limiting(client: AsyncClient, test_user):
    """Test that login endpoint has rate limiting in production."""
    import os
    ENV = os.getenv("ENV", "development")
    
    if ENV != "production":
        # Rate limiting is disabled in dev/test
        pytest.skip("Rate limiting disabled in non-production environments")
    
    # Make 6 rapid login attempts (limit is 5/minute)
    responses = []
    for i in range(6):
        response = await client.post(
            "/api/auth/login",
            json={"username": "testuser_jwt", "password": "password123"}
        )
        responses.append(response)
    
    # First 5 should succeed or fail with 401 (wrong password)
    # 6th should be rate limited with 429
    status_codes = [r.status_code for r in responses]
    
    # Should have at least one 429 (rate limit exceeded)
    assert 429 in status_codes, f"Expected rate limiting (429), got: {status_codes}"
