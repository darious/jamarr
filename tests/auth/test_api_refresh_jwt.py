"""Integration tests for JWT refresh endpoint."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_refresh_with_valid_cookie(client: AsyncClient, test_user):
    """Test that refresh returns new access token with valid refresh cookie."""
    # First login to get refresh cookie
    login_response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"}
    )
    assert login_response.status_code == 200
    
    # Use refresh endpoint
    refresh_response = await client.post("/api/auth/refresh")
    
    assert refresh_response.status_code == 200
    data = refresh_response.json()
    
    # Should have new access token
    assert "access_token" in data
    assert isinstance(data["access_token"], str)
    assert len(data["access_token"]) > 0
    
    # Should have token_type
    assert data.get("token_type") == "bearer"
    
    # Verify it's a valid JWT structure (header.payload.signature)
    assert data["access_token"].count(".") == 2
    assert len(data["access_token"]) > 100  # JWTs are long strings



@pytest.mark.asyncio
async def test_refresh_rotates_token(client: AsyncClient, test_user, db):
    """Test that refresh rotates the refresh token (old one revoked)."""
    # Login to get initial refresh cookie
    login_response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"}
    )
    assert login_response.status_code == 200
    initial_refresh = login_response.cookies["jamarr_refresh"]
    
    # Count active sessions before refresh
    count_before = await db.fetchval(
        "SELECT COUNT(*) FROM auth_refresh_session WHERE user_id = $1 AND revoked_at IS NULL",
        test_user["id"]
    )
    
    # Refresh token
    refresh_response = await client.post("/api/auth/refresh")
    assert refresh_response.status_code == 200
    
    # Should have new refresh cookie
    new_refresh = refresh_response.cookies.get("jamarr_refresh")
    assert new_refresh is not None
    assert new_refresh != initial_refresh
    
    # Should still have only 1 active session (old revoked, new created)
    count_after = await db.fetchval(
        "SELECT COUNT(*) FROM auth_refresh_session WHERE user_id = $1 AND revoked_at IS NULL",
        test_user["id"]
    )
    assert count_after == 1


@pytest.mark.asyncio
async def test_refresh_without_cookie(client: AsyncClient):
    """Test that refresh without cookie returns 401."""
    response = await client.post("/api/auth/refresh")
    
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_with_revoked_token(client: AsyncClient, test_user, db):
    """Test that refresh with revoked token returns 401."""
    from app.auth_tokens import generate_refresh_token, hash_refresh_token
    from app.auth import create_refresh_session, revoke_refresh_session
    from datetime import datetime, timedelta, timezone
    
    # Create and immediately revoke a refresh session
    token = generate_refresh_token()
    token_hash = hash_refresh_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=21)
    
    await create_refresh_session(
        db=db,
        user_id=test_user["id"],
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent="Test",
        ip="127.0.0.1"
    )
    await revoke_refresh_session(db, token_hash)
    
    # Try to use revoked token
    client.cookies.set("jamarr_refresh", token)
    response = await client.post("/api/auth/refresh")
    
    assert response.status_code == 401



@pytest.mark.asyncio
async def test_refresh_with_expired_token(client: AsyncClient, test_user, db):
    """Test that refresh with expired token returns 401."""
    from app.auth_tokens import generate_refresh_token, hash_refresh_token
    from app.auth import create_refresh_session
    from datetime import datetime, timedelta, timezone
    
    # Create an already-expired refresh session
    token = generate_refresh_token()
    token_hash = hash_refresh_token(token)
    expires_at = datetime.now(timezone.utc) - timedelta(days=1)  # Already expired
    
    await create_refresh_session(
        db=db,
        user_id=test_user["id"],
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent="Test",
        ip="127.0.0.1"
    )
    
    # Try to use expired token
    client.cookies.set("jamarr_refresh", token)
    response = await client.post("/api/auth/refresh")
    
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_reuse_detection(client: AsyncClient, test_user):
    """Test that reusing a revoked refresh token returns 401."""
    # Login to get refresh cookie
    login_response = await client.post(
        "/api/auth/login",
        json={"username": "testuser_jwt", "password": "password123"}
    )
    assert login_response.status_code == 200
    first_refresh = login_response.cookies["jamarr_refresh"]
    
    # Use refresh once (this rotates the token)
    refresh1 = await client.post("/api/auth/refresh")
    assert refresh1.status_code == 200
    
    # Try to reuse the old (now revoked) refresh token
    client.cookies.set("jamarr_refresh", first_refresh)
    refresh2 = await client.post("/api/auth/refresh")
    
    # Should be rejected
    assert refresh2.status_code == 401
