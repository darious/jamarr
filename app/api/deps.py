"""FastAPI dependencies for JWT authentication."""
import logging
from typing import Optional

import asyncpg
from fastapi import Depends, Header, HTTPException, Request, status

from app.auth import get_refresh_session, get_user_by_id
from app.auth_tokens import (
    REFRESH_COOKIE_NAME,
    hash_refresh_token,
    verify_access_token,
)
from app.db import get_db
from app.security import log_security_event


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
    if not authorization:
        log_security_event("auth_missing", request, level=logging.INFO)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Parse "Bearer <token>" format
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        log_security_event("auth_invalid_header", request, level=logging.WARNING)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Expected: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = parts[1]
    
    # Verify JWT and extract claims
    try:
        claims = verify_access_token(token)  # Raises 401 if invalid
    except HTTPException as exc:
        log_security_event(
            "auth_invalid_token",
            request,
            level=logging.WARNING,
            reason=exc.detail,
        )
        raise
    
    # Get user from database
    user_id = int(claims["sub"])
    user = await get_user_by_id(db, user_id)
    
    if not user:
        log_security_event(
            "auth_user_not_found",
            request,
            level=logging.WARNING,
            user_id=user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.get("is_active", True):
        log_security_event(
            "auth_inactive_user",
            request,
            level=logging.WARNING,
            user_id=user["id"],
            username=user["username"],
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


def require_admin_user(
    user: asyncpg.Record, request: Request | None = None
) -> asyncpg.Record:
    """Require the authenticated user to have admin privileges."""
    if not user.get("is_admin", False):
        log_security_event(
            "admin_denied",
            request,
            level=logging.WARNING,
            user_id=user["id"],
            username=user["username"],
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user


async def get_current_admin_user_jwt(
    request: Request,
    user: asyncpg.Record = Depends(get_current_user_jwt),
) -> asyncpg.Record:
    """Dependency to require JWT authentication and admin privileges."""
    return require_admin_user(user, request)


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
    if not authorization:
        return None

    try:
        return await get_current_user_jwt(authorization, request, db)
    except HTTPException:
        return None


async def get_user_from_refresh_cookie(
    request: Request, db: asyncpg.Connection
) -> asyncpg.Record:
    """Authenticate via the refresh-token cookie.

    For requests that cannot carry an Authorization header: EventSource (SSE)
    connections and external OAuth callback redirects. The cookie is httponly
    and scoped to /api, so it never appears in URLs or proxy logs.
    """
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not refresh_token:
        log_security_event("auth_missing", request, level=logging.INFO)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    session = await get_refresh_session(db, hash_refresh_token(refresh_token))
    if not session:
        log_security_event("auth_invalid_token", request, level=logging.WARNING)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user = await get_user_by_id(db, session["user_id"])
    if not user or not user.get("is_active", True):
        log_security_event(
            "auth_inactive_user",
            request,
            level=logging.WARNING,
            user_id=session["user_id"],
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    return user


async def get_current_user_jwt_or_cookie(
    request: Request,
    authorization: Optional[str] = Header(None),
    db: asyncpg.Connection = Depends(get_db),
) -> asyncpg.Record:
    """Require auth via Bearer header, falling back to the refresh cookie.

    Only for endpoints that browsers must reach without custom headers (SSE).
    """
    if authorization:
        return await get_current_user_jwt(authorization, request, db)
    return await get_user_from_refresh_cookie(request, db)


async def get_current_admin_user_jwt_or_cookie(
    request: Request,
    user: asyncpg.Record = Depends(get_current_user_jwt_or_cookie),
) -> asyncpg.Record:
    """Require admin auth via Bearer header or refresh cookie (SSE endpoints)."""
    return require_admin_user(user, request)
