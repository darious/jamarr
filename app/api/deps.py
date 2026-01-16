"""FastAPI dependencies for JWT authentication."""
from typing import Optional

import asyncpg
from fastapi import Depends, Header, HTTPException, Request, status

from app.auth import get_user_by_id
from app.auth_tokens import verify_access_token
from app.db import get_db


async def get_current_user_jwt(
    authorization: Optional[str] = Header(None),
    request: Request = None,
    db: asyncpg.Connection = Depends(get_db),
) -> asyncpg.Record:
    """Dependency to require JWT authentication.
    
    Extracts and validates JWT from Authorization header.
    Returns user record from database.
    
    Args:
        authorization: Authorization header value (should be "Bearer <token>")
        db: Database connection
        
    Returns:
        User record from database
        
    Raises:
        HTTPException: 401 if token is missing, invalid, or expired
    """
    if not authorization and request is not None:
        token = request.query_params.get("access_token")
        if token:
            authorization = f"Bearer {token}"

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Parse "Bearer <token>" format
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Expected: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = parts[1]
    
    # Verify JWT and extract claims
    claims = verify_access_token(token)  # Raises 401 if invalid
    
    # Get user from database
    user_id = int(claims["sub"])
    user = await get_user_by_id(db, user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


async def get_optional_user_jwt(
    authorization: Optional[str] = Header(None),
    request: Request = None,
    db: asyncpg.Connection = Depends(get_db),
) -> Optional[asyncpg.Record]:
    """Optional JWT authentication dependency.
    
    Returns user if valid JWT provided, None otherwise.
    Does not raise exceptions for missing or invalid tokens.
    
    Args:
        authorization: Authorization header value (should be "Bearer <token>")
        db: Database connection
        
    Returns:
        User record if valid token provided, None otherwise
    """
    if not authorization and request is not None:
        token = request.query_params.get("access_token")
        if token:
            authorization = f"Bearer {token}"

    if not authorization:
        return None
    
    try:
        return await get_current_user_jwt(authorization, request, db)
    except HTTPException:
        return None
