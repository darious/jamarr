"""JWT and refresh token operations for authentication.

This module provides functions for creating and verifying JWT access tokens,
and generating/hashing refresh tokens for the new JWT-based authentication system.
"""
import os
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from jose import JWTError, jwt


# JWT Configuration from environment
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ISSUER = os.getenv("JWT_ISSUER", "jamarr")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "jamarr-api")
ACCESS_TOKEN_TTL_MINUTES = int(os.getenv("ACCESS_TOKEN_TTL_MINUTES", "10"))
REFRESH_TOKEN_TTL_DAYS = int(os.getenv("REFRESH_TOKEN_TTL_DAYS", "21"))


def _get_jwt_settings() -> dict:
    secret_key = os.getenv("JWT_SECRET_KEY", "")
    if not secret_key and os.getenv("ENV", "development") != "production":
        secret_key = "dev-secret"
    return {
        "secret_key": secret_key,
        "algorithm": os.getenv("JWT_ALGORITHM", "HS256"),
        "issuer": os.getenv("JWT_ISSUER", "jamarr"),
        "audience": os.getenv("JWT_AUDIENCE", "jamarr-api"),
        "ttl_minutes": int(os.getenv("ACCESS_TOKEN_TTL_MINUTES", "10")),
    }


def _validate_jwt_config(secret_key: str) -> None:
    """Validate that required JWT configuration is present."""
    if not secret_key:
        raise RuntimeError(
            "JWT_SECRET_KEY environment variable is required but not set. "
            "Generate a secret key with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )


def create_access_token(user_id: int, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token for the given user.
    
    Args:
        user_id: The user's database ID
        expires_delta: Optional custom expiration time. Defaults to ACCESS_TOKEN_TTL_MINUTES.
        
    Returns:
        Signed JWT token string
        
    Raises:
        RuntimeError: If JWT_SECRET_KEY is not configured
    """
    settings = _get_jwt_settings()
    _validate_jwt_config(settings["secret_key"])
    
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings["ttl_minutes"])
    
    now = datetime.now(timezone.utc)
    expire = now + expires_delta
    
    claims = {
        "sub": str(user_id),  # Subject (user ID)
        "exp": expire,        # Expiration time
        "iat": now,           # Issued at
        "iss": settings["issuer"],    # Issuer
        "aud": settings["audience"],  # Audience
    }
    
    encoded_jwt = jwt.encode(
        claims,
        settings["secret_key"],
        algorithm=settings["algorithm"],
    )
    return encoded_jwt


def verify_access_token(token: str) -> dict:
    """Verify and decode a JWT access token.
    
    Args:
        token: The JWT token string to verify
        
    Returns:
        Decoded token claims as a dictionary
        
    Raises:
        HTTPException: 401 if token is invalid, expired, or has wrong issuer/audience
    """
    settings = _get_jwt_settings()
    _validate_jwt_config(settings["secret_key"])
    
    try:
        payload = jwt.decode(
            token,
            settings["secret_key"],
            algorithms=[settings["algorithm"]],
            issuer=settings["issuer"],
            audience=settings["audience"],
        )
        return payload
    except JWTError as e:
        # Handle specific JWT errors
        error_msg = str(e).lower()
        if "expired" in error_msg:
            detail = "Access token has expired"
        elif "signature" in error_msg:
            detail = "Invalid token signature"
        elif "issuer" in error_msg or "audience" in error_msg:
            detail = "Invalid token issuer or audience"
        else:
            detail = "Invalid access token"
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


def generate_refresh_token() -> str:
    """Generate a cryptographically secure random refresh token.
    
    Returns:
        URL-safe random token string (32 bytes, ~43 characters)
    """
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """Hash a refresh token using SHA-256.
    
    Refresh tokens are never stored in plaintext. This function creates
    a deterministic hash for database storage and lookup.
    
    Args:
        token: The raw refresh token string
        
    Returns:
        Lowercase hex digest of the SHA-256 hash (64 characters)
    """
    return hashlib.sha256(token.encode()).hexdigest()
