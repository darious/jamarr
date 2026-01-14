"""Unit tests for JWT token operations."""
import os
from datetime import timedelta, datetime, timezone
import pytest
from jose import jwt


# We'll import these after creating the module
# from app.auth_tokens import create_access_token, verify_access_token


# Test configuration
TEST_SECRET = "test-secret-key-for-jwt-testing"
TEST_ISSUER = "jamarr-test"
TEST_AUDIENCE = "jamarr-api-test"


@pytest.fixture(autouse=True)
def set_test_env():
    """Set test environment variables for JWT configuration."""
    os.environ["JWT_SECRET_KEY"] = TEST_SECRET
    os.environ["JWT_ALGORITHM"] = "HS256"
    os.environ["JWT_ISSUER"] = TEST_ISSUER
    os.environ["JWT_AUDIENCE"] = TEST_AUDIENCE
    os.environ["ACCESS_TOKEN_TTL_MINUTES"] = "10"
    yield
    # Cleanup
    for key in ["JWT_SECRET_KEY", "JWT_ALGORITHM", "JWT_ISSUER", "JWT_AUDIENCE", "ACCESS_TOKEN_TTL_MINUTES"]:
        os.environ.pop(key, None)


def test_create_access_token_valid_structure():
    """Test that created JWT has correct structure and claims."""
    from app.auth_tokens import create_access_token
    
    user_id = 42
    expires_delta = timedelta(minutes=10)
    
    token = create_access_token(user_id=user_id, expires_delta=expires_delta)
    
    # Decode without verification to inspect structure
    unverified = jwt.get_unverified_claims(token)
    
    assert "sub" in unverified
    assert unverified["sub"] == str(user_id)
    assert "exp" in unverified
    assert "iat" in unverified
    assert "iss" in unverified
    assert unverified["iss"] == TEST_ISSUER
    assert "aud" in unverified
    assert unverified["aud"] == TEST_AUDIENCE
    
    # Verify expiry is approximately correct (within 5 seconds tolerance)
    expected_exp = datetime.now(timezone.utc) + expires_delta
    actual_exp = datetime.fromtimestamp(unverified["exp"], tz=timezone.utc)
    assert abs((expected_exp - actual_exp).total_seconds()) < 5


def test_verify_access_token_success():
    """Test successful token verification returns correct user_id."""
    from app.auth_tokens import create_access_token, verify_access_token
    
    user_id = 123
    token = create_access_token(user_id=user_id, expires_delta=timedelta(minutes=10))
    
    claims = verify_access_token(token)
    
    assert claims["sub"] == str(user_id)
    assert claims["iss"] == TEST_ISSUER
    assert claims["aud"] == TEST_AUDIENCE


def test_verify_access_token_expired():
    """Test that expired tokens raise HTTPException with 401."""
    from app.auth_tokens import create_access_token, verify_access_token
    from fastapi import HTTPException
    
    user_id = 123
    # Create token that expired 1 minute ago
    token = create_access_token(user_id=user_id, expires_delta=timedelta(minutes=-1))
    
    with pytest.raises(HTTPException) as exc_info:
        verify_access_token(token)
    
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


def test_verify_access_token_invalid_signature():
    """Test that tokens with invalid signatures are rejected."""
    from app.auth_tokens import verify_access_token
    from fastapi import HTTPException
    
    # Create a token with wrong secret
    fake_token = jwt.encode(
        {"sub": "123", "exp": datetime.now(timezone.utc) + timedelta(minutes=10)},
        "wrong-secret",
        algorithm="HS256"
    )
    
    with pytest.raises(HTTPException) as exc_info:
        verify_access_token(fake_token)
    
    assert exc_info.value.status_code == 401


def test_verify_access_token_wrong_issuer():
    """Test that tokens with wrong issuer are rejected."""
    from app.auth_tokens import verify_access_token
    from fastapi import HTTPException
    
    # Create token with wrong issuer
    wrong_issuer_token = jwt.encode(
        {
            "sub": "123",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            "iat": datetime.now(timezone.utc),
            "iss": "wrong-issuer",
            "aud": TEST_AUDIENCE,
        },
        TEST_SECRET,
        algorithm="HS256"
    )
    
    with pytest.raises(HTTPException) as exc_info:
        verify_access_token(wrong_issuer_token)
    
    assert exc_info.value.status_code == 401


def test_verify_access_token_wrong_audience():
    """Test that tokens with wrong audience are rejected."""
    from app.auth_tokens import verify_access_token
    from fastapi import HTTPException
    
    # Create token with wrong audience
    wrong_aud_token = jwt.encode(
        {
            "sub": "123",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            "iat": datetime.now(timezone.utc),
            "iss": TEST_ISSUER,
            "aud": "wrong-audience",
        },
        TEST_SECRET,
        algorithm="HS256"
    )
    
    with pytest.raises(HTTPException) as exc_info:
        verify_access_token(wrong_aud_token)
    
    assert exc_info.value.status_code == 401


def test_verify_access_token_malformed():
    """Test that malformed tokens are rejected."""
    from app.auth_tokens import verify_access_token
    from fastapi import HTTPException
    
    with pytest.raises(HTTPException) as exc_info:
        verify_access_token("not.a.valid.jwt.token")
    
    assert exc_info.value.status_code == 401
