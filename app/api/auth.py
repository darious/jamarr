from typing import Optional
from datetime import datetime, timezone, timedelta
import os

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth import (
    hash_password,
    verify_password,
    get_user_by_username_or_email,
    create_refresh_session,
    get_refresh_session,
    revoke_refresh_session,
    revoke_all_user_sessions,
)
from app.auth_tokens import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    REFRESH_TOKEN_TTL_DAYS,
)
from app.api.deps import get_current_admin_user_jwt, get_current_user_jwt
from app.db import get_db

router = APIRouter()
ENV = os.getenv("ENV", "development").lower()
limiter = Limiter(
    key_func=get_remote_address,
    enabled=ENV == "production",
)

# Configuration
REFRESH_COOKIE_NAME = os.getenv("REFRESH_COOKIE_NAME", "jamarr_refresh")
if "REFRESH_COOKIE_SECURE" in os.environ:
    REFRESH_COOKIE_SECURE = os.getenv("REFRESH_COOKIE_SECURE", "false").lower() == "true"
else:
    REFRESH_COOKIE_SECURE = ENV == "production"


class CreateUserBody(BaseModel):
    username: str
    email: EmailStr
    password: str
    display_name: Optional[str] = None


class LoginBody(BaseModel):
    username: str
    password: str


class UpdateProfileBody(BaseModel):
    email: EmailStr
    display_name: Optional[str] = None


class UpdatePreferencesBody(BaseModel):
    accent_color: Optional[str] = None
    theme_mode: Optional[str] = None  # 'light' or 'dark'


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Set JWT refresh token cookie."""
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=REFRESH_TOKEN_TTL_DAYS * 86400,  # Convert days to seconds
        httponly=True,
        samesite="lax",
        secure=REFRESH_COOKIE_SECURE,
        path="/api",
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Clear JWT refresh token cookie."""
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value="",
        max_age=0,
        httponly=True,
        samesite="lax",
        secure=REFRESH_COOKIE_SECURE,
        path="/api",
    )


def _public_user_dict(row: asyncpg.Record) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "display_name": row["display_name"] or row["username"],
        "is_admin": bool(row.get("is_admin", False)),
        "accent_color": row.get("accent_color") or "#ff006e",
        "theme_mode": row.get("theme_mode") or "dark",
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "last_login": row["last_login_at"].isoformat()
        if row["last_login_at"]
        else None,
    }


def _validate_password(password: str) -> None:
    """Validate password meets minimum requirements."""
    if len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long.",
        )


@router.post("/api/auth/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: CreateUserBody,
    _current_user: asyncpg.Record = Depends(get_current_admin_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
):
    username = payload.username.strip()
    email = payload.email.strip()
    _validate_password(payload.password)

    existing = await db.fetchrow(
        'SELECT 1 FROM "user" WHERE username = $1 OR email = $2', username, email
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already taken.",
        )

    password_hash = hash_password(payload.password)

    user = await db.fetchrow(
        """
        INSERT INTO "user" (username, email, password_hash, display_name, created_at)
        VALUES ($1, $2, $3, $4, NOW())
        RETURNING *
        """,
        username,
        email,
        password_hash,
        payload.display_name.strip() if payload.display_name else None,
    )

    return _public_user_dict(user)


@router.post("/api/auth/login")
@limiter.limit("5/minute")
async def login(
    request: Request,
    payload: LoginBody,
    response: Response,
    db: asyncpg.Connection = Depends(get_db),
):
    """Login with username/password, returns JWT access token and sets refresh cookie."""
    
    username = payload.username.strip()

    # Get user by username or email
    user = await get_user_by_username_or_email(db, username)

    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials."
        )

    # Update last login timestamp
    await db.execute(
        'UPDATE "user" SET last_login_at = $1 WHERE id = $2',
        datetime.now(timezone.utc),
        user["id"],
    )

    # Create JWT access token
    access_token = create_access_token(user_id=user["id"])

    # Generate and store refresh token
    refresh_token = generate_refresh_token()
    refresh_token_hash = hash_refresh_token(refresh_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_TTL_DAYS)

    await create_refresh_session(
        db=db,
        user_id=user["id"],
        token_hash=refresh_token_hash,
        expires_at=expires_at,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )

    # Set refresh token cookie
    _set_refresh_cookie(response, refresh_token)

    # Return access token and user data
    user_data = _public_user_dict(user)
    return {
        **user_data,
        "access_token": access_token,
        "token_type": "bearer",
        "user": user_data,
    }


@router.post("/api/auth/logout")
async def logout(
    request: Request, response: Response, db: asyncpg.Connection = Depends(get_db)
):
    """Logout by revoking refresh session and clearing cookie."""
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if refresh_token:
        token_hash = hash_refresh_token(refresh_token)
        await revoke_refresh_session(db, token_hash)
    
    _clear_refresh_cookie(response)
    return {"ok": True}


@router.post("/api/auth/refresh")
async def refresh(
    request: Request, response: Response, db: asyncpg.Connection = Depends(get_db)
):
    """Refresh access token using refresh token cookie (with rotation)."""
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
        )
    
    # Lookup refresh session
    token_hash = hash_refresh_token(refresh_token)
    session = await get_refresh_session(db, token_hash)
    
    if not session:
        # Token is either revoked, expired, or doesn't exist
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    
    user_id = session["user_id"]
    
    # Rotate refresh token (revoke old, create new)
    await revoke_refresh_session(db, token_hash)
    
    # Generate new refresh token
    new_refresh_token = generate_refresh_token()
    new_token_hash = hash_refresh_token(new_refresh_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_TTL_DAYS)
    
    await create_refresh_session(
        db=db,
        user_id=user_id,
        token_hash=new_token_hash,
        expires_at=expires_at,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    
    # Set new refresh cookie
    _set_refresh_cookie(response, new_refresh_token)
    
    # Create new access token
    access_token = create_access_token(user_id=user_id)
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


@router.post("/api/auth/logout-all")
async def logout_all(
    user: asyncpg.Record = Depends(get_current_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
):
    """Logout from all devices by revoking all refresh sessions."""
    # Count sessions before revoking
    count = await db.fetchval(
        "SELECT COUNT(*) FROM auth_refresh_session WHERE user_id = $1 AND revoked_at IS NULL",
        user["id"],
    )
    
    # Revoke all sessions
    await revoke_all_user_sessions(db, user["id"])
    
    return {
        "ok": True,
        "sessions_revoked": count,
    }


@router.get("/api/auth/me")
async def me(
    user: asyncpg.Record = Depends(get_current_user_jwt),
):
    """Get current user profile using JWT authentication."""
    return _public_user_dict(user)


@router.put("/api/auth/profile")
async def update_profile(
    payload: UpdateProfileBody,
    user: asyncpg.Record = Depends(get_current_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
):
    email = payload.email.strip()
    display_name = (
        payload.display_name.strip() if payload.display_name else user["display_name"]
    )

    existing = await db.fetchrow(
        'SELECT 1 FROM "user" WHERE email = $1 AND id != $2',
        email,
        user["id"],
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already in use.",
        )

    await db.execute(
        'UPDATE "user" SET email = $1, display_name = $2 WHERE id = $3',
        email,
        display_name,
        user["id"],
    )
    updated_user = await db.fetchrow(
        'SELECT * FROM "user" WHERE id = $1',
        user["id"],
    )
    return _public_user_dict(updated_user or user)


@router.post("/api/auth/password")
async def change_password(
    payload: ChangePasswordBody,
    response: Response,
    user: asyncpg.Record = Depends(get_current_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
):
    _validate_password(payload.new_password)

    if not verify_password(payload.current_password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    new_hash = hash_password(payload.new_password)
    await db.execute(
        'UPDATE "user" SET password_hash = $1 WHERE id = $2',
        new_hash,
        user["id"],
    )
    # Invalidate other sessions but keep current one
    await db.execute(
        "DELETE FROM auth_refresh_session WHERE user_id = $1 AND revoked_at IS NULL",
        user["id"],
    )
    _clear_refresh_cookie(response)
    return {"ok": True}


@router.patch("/api/auth/preferences")
async def update_preferences(
    payload: UpdatePreferencesBody,
    user: asyncpg.Record = Depends(get_current_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
):
    """Update user preferences (accent color, theme mode)"""
    
    updates = []
    values = []
    
    # Validate accent color if provided
    if payload.accent_color:
        import re
        if not re.match(r'^#[0-9A-Fa-f]{6}$', payload.accent_color):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid color format. Must be hex color like #ff006e",
            )
        updates.append(f"accent_color = ${len(values) + 1}")
        values.append(payload.accent_color)
        
    if payload.theme_mode:
        if payload.theme_mode not in ['dark', 'light']:
             raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid theme mode. Must be 'dark' or 'light'",
            )
        updates.append(f"theme_mode = ${len(values) + 1}")
        values.append(payload.theme_mode)
        
    if updates:
        values.append(user["id"])
        await db.execute(
            f'UPDATE "user" SET {", ".join(updates)} WHERE id = ${len(values)}',
            *values
        )
    updated_user = await db.fetchrow(
        'SELECT * FROM "user" WHERE id = $1',
        user["id"],
    )
    return _public_user_dict(updated_user or user)
