"""Integration tests for JWT /api/auth/me endpoint."""
import pytest
from httpx import AsyncClient
from datetime import timedelta


@pytest.mark.asyncio
async def test_me_with_valid_jwt(client: AsyncClient, test_user):
    """Test that /me returns user data with valid JWT."""
    from app.auth_tokens import create_access_token
    
    # Create access token
    token = create_access_token(
        user_id=test_user["id"],
        expires_delta=timedelta(minutes=10)
    )
    
    # Call /me endpoint
    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Should return user profile
    assert data["id"] == test_user["id"]
    assert data["username"] == test_user["username"]
    assert data["email"] == test_user["email"]


@pytest.mark.asyncio
async def test_me_without_jwt(client: AsyncClient):
    """Test that /me without JWT returns 401."""
    response = await client.get("/api/auth/me")
    
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_with_invalid_jwt(client: AsyncClient):
    """Test that /me with invalid JWT returns 401."""
    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer invalid.token.here"}
    )
    
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_with_expired_jwt(client: AsyncClient, test_user):
    """Test that /me with expired JWT returns 401."""
    from app.auth_tokens import create_access_token
    
    # Create expired token
    token = create_access_token(
        user_id=test_user["id"],
        expires_delta=timedelta(minutes=-1)  # Already expired
    )
    
    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_does_not_refresh(client: AsyncClient, test_user):
    """Test that /me does not issue new tokens."""
    from app.auth_tokens import create_access_token
    
    # Create access token
    token = create_access_token(
        user_id=test_user["id"],
        expires_delta=timedelta(minutes=10)
    )
    
    # Call /me endpoint
    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Should NOT have access_token field
    assert "access_token" not in data
    
    # Should NOT set refresh cookie
    assert "jamarr_refresh" not in response.cookies
