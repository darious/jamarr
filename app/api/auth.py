from typing import Optional
from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr

from app.auth import (
    COOKIE_SECURE,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    create_session,
    destroy_session,
    get_session_user,
    hash_password,
    require_current_user,
    verify_password,
)
from app.db import get_db

router = APIRouter()


class SignupBody(BaseModel):
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


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )


def _public_user_dict(row: asyncpg.Record) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "display_name": row["display_name"] or row["username"],
        "accent_color": row.get("accent_color") or "#ff006e",
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


@router.post("/api/auth/signup")
async def signup(
    payload: SignupBody,
    request: Request,
    response: Response,
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

    # Insert new user
    user = await db.fetchrow(
        """
        INSERT INTO "user" (username, email, password_hash, display_name, created_at, last_login_at)
        VALUES ($1, $2, $3, $4, NOW(), NOW())
        RETURNING *
        """,
        username,
        email,
        password_hash,
        payload.display_name.strip() if payload.display_name else None,
    )

    token = await create_session(
        db,
        user_id=user["id"],
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    _set_session_cookie(response, token)
    return _public_user_dict(user)


@router.post("/api/auth/login")
async def login(
    payload: LoginBody,
    request: Request,
    response: Response,
    db: asyncpg.Connection = Depends(get_db),
):
    username = payload.username.strip()

    user = await db.fetchrow(
        """
        SELECT *
        FROM "user"
        WHERE username = $1
        LIMIT 1
        """,
        username,
    )

    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials."
        )

    token = await create_session(
        db,
        user_id=user["id"],
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    await db.execute(
        'UPDATE "user" SET last_login_at = $1 WHERE id = $2',
        datetime.now(timezone.utc),
        user["id"],
    )
    _set_session_cookie(response, token)
    return _public_user_dict(user)


@router.post("/api/auth/logout")
async def logout(
    request: Request, response: Response, db: asyncpg.Connection = Depends(get_db)
):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        await destroy_session(db, token)
    response.delete_cookie(
        SESSION_COOKIE_NAME, path="/", samesite="lax", secure=COOKIE_SECURE
    )
    return {"ok": True}


@router.get("/api/auth/me")
async def me(
    request: Request, response: Response, db: asyncpg.Connection = Depends(get_db)
):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user, token_value = await get_session_user(db, token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated."
        )

    # Refresh cookie to keep session alive
    _set_session_cookie(response, token_value or token)
    return _public_user_dict(user)


@router.put("/api/auth/profile")
async def update_profile(
    payload: UpdateProfileBody,
    request: Request,
    response: Response,
    db: asyncpg.Connection = Depends(get_db),
):
    user, token = await require_current_user(request, db)
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
    _set_session_cookie(response, token)
    updated_user = await db.fetchrow(
        'SELECT * FROM "user" WHERE id = $1',
        user["id"],
    )
    return _public_user_dict(updated_user or user)


@router.post("/api/auth/password")
async def change_password(
    payload: ChangePasswordBody,
    request: Request,
    response: Response,
    db: asyncpg.Connection = Depends(get_db),
):
    user, token = await require_current_user(request, db)
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
        "DELETE FROM session WHERE user_id = $1 AND token != $2", user["id"], token
    )
    _set_session_cookie(response, token)
    return {"ok": True}


@router.patch("/api/auth/preferences")
async def update_preferences(
    payload: UpdatePreferencesBody,
    request: Request,
    response: Response,
    db: asyncpg.Connection = Depends(get_db),
):
    """Update user preferences (accent color, etc.)"""
    user, token = await require_current_user(request, db)
    
    # Validate accent color if provided
    if payload.accent_color:
        import re
        if not re.match(r'^#[0-9A-Fa-f]{6}$', payload.accent_color):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid color format. Must be hex color like #ff006e",
            )
        
        await db.execute(
            'UPDATE "user" SET accent_color = $1 WHERE id = $2',
            payload.accent_color,
            user["id"],
        )
    
    _set_session_cookie(response, token)
    updated_user = await db.fetchrow(
        'SELECT * FROM "user" WHERE id = $1',
        user["id"],
    )
    return _public_user_dict(updated_user or user)
