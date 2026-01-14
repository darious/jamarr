"""Integration tests for JWT authentication dependency."""
import pytest
from datetime import timedelta
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_get_current_user_jwt_valid(db, test_user):
    """Test that valid JWT returns user record."""
    from app.auth_tokens import create_access_token
    from app.api.deps import get_current_user_jwt
    
    # Create valid access token
    token = create_access_token(
        user_id=test_user["id"],
        expires_delta=timedelta(minutes=10)
    )
    
    # Call dependency with proper Authorization header
    authorization = f"Bearer {token}"
    user = await get_current_user_jwt(authorization=authorization, db=db)
    
    assert user is not None
    assert user["id"] == test_user["id"]
    assert user["username"] == test_user["username"]


@pytest.mark.asyncio
async def test_get_current_user_jwt_missing_header(db):
    """Test that missing Authorization header returns 401."""
    from app.api.deps import get_current_user_jwt
    
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_jwt(authorization=None, db=db)
    
    assert exc_info.value.status_code == 401
    assert "missing" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_get_current_user_jwt_invalid_format(db):
    """Test that invalid header format returns 401."""
    from app.api.deps import get_current_user_jwt
    
    # Missing "Bearer" prefix
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_jwt(authorization="just-a-token", db=db)
    
    assert exc_info.value.status_code == 401
    assert "invalid" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_get_current_user_jwt_invalid_token(db):
    """Test that invalid JWT returns 401."""
    from app.api.deps import get_current_user_jwt
    
    authorization = "Bearer invalid.jwt.token"
    
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_jwt(authorization=authorization, db=db)
    
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_jwt_expired_token(db, test_user):
    """Test that expired JWT returns 401."""
    from app.auth_tokens import create_access_token
    from app.api.deps import get_current_user_jwt
    
    # Create expired token
    token = create_access_token(
        user_id=test_user["id"],
        expires_delta=timedelta(minutes=-1)  # Already expired
    )
    
    authorization = f"Bearer {token}"
    
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_jwt(authorization=authorization, db=db)
    
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_jwt_user_not_found(db):
    """Test that JWT for non-existent user returns 401."""
    from app.auth_tokens import create_access_token
    from app.api.deps import get_current_user_jwt
    
    # Create token for non-existent user
    token = create_access_token(
        user_id=99999,  # Non-existent user ID
        expires_delta=timedelta(minutes=10)
    )
    
    authorization = f"Bearer {token}"
    
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_jwt(authorization=authorization, db=db)
    
    assert exc_info.value.status_code == 401
    assert "not found" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_get_optional_user_jwt_valid(db, test_user):
    """Test that optional dependency returns user for valid token."""
    from app.auth_tokens import create_access_token
    from app.api.deps import get_optional_user_jwt
    
    token = create_access_token(
        user_id=test_user["id"],
        expires_delta=timedelta(minutes=10)
    )
    
    authorization = f"Bearer {token}"
    user = await get_optional_user_jwt(authorization=authorization, db=db)
    
    assert user is not None
    assert user["id"] == test_user["id"]


@pytest.mark.asyncio
async def test_get_optional_user_jwt_missing_header(db):
    """Test that optional dependency returns None for missing header."""
    from app.api.deps import get_optional_user_jwt
    
    user = await get_optional_user_jwt(authorization=None, db=db)
    
    assert user is None


@pytest.mark.asyncio
async def test_get_optional_user_jwt_invalid_token(db):
    """Test that optional dependency returns None for invalid token."""
    from app.api.deps import get_optional_user_jwt
    
    authorization = "Bearer invalid.token"
    user = await get_optional_user_jwt(authorization=authorization, db=db)
    
    assert user is None
