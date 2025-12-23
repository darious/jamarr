from typing import Optional

import aiosqlite
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


def _public_user_dict(row: aiosqlite.Row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "display_name": row["display_name"] or row["username"],
        "created_at": row["created_at"],
        "last_login": row["last_login"],
    }


def _validate_password(password: str) -> None:
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
    db: aiosqlite.Connection = Depends(get_db),
):
    username = payload.username.strip()
    email = payload.email.strip()
    _validate_password(payload.password)

    async with db.execute(
        "SELECT 1 FROM users WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)",
        (username, email),
    ) as cursor:
        if await cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username or email already in use.",
            )

    password_hash = hash_password(payload.password)
    display_name = payload.display_name.strip() if payload.display_name else username

    cursor = await db.execute(
        """
        INSERT INTO users (username, email, password_hash, display_name)
        VALUES (?, ?, ?, ?)
        """,
        (username, email, password_hash, display_name),
    )
    user_id = cursor.lastrowid

    token = await create_session(
        db,
        user_id=user_id,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    await db.commit()

    _set_session_cookie(response, token)
    async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cursor:
        saved_user = await cursor.fetchone()

    return _public_user_dict(saved_user)


@router.post("/api/auth/login")
async def login(
    payload: LoginBody,
    request: Request,
    response: Response,
    db: aiosqlite.Connection = Depends(get_db),
):
    username = payload.username.strip()

    async with db.execute(
        """
        SELECT *
        FROM users
        WHERE LOWER(username) = LOWER(?)
        LIMIT 1
        """,
        (username,),
    ) as cursor:
        user = await cursor.fetchone()

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
        "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (user["id"],)
    )
    await db.commit()
    _set_session_cookie(response, token)
    return _public_user_dict(user)


@router.post("/api/auth/logout")
async def logout(
    request: Request, response: Response, db: aiosqlite.Connection = Depends(get_db)
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
    request: Request, response: Response, db: aiosqlite.Connection = Depends(get_db)
):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user, token_value = await get_session_user(db, token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")

    # Refresh cookie to keep session alive
    _set_session_cookie(response, token_value or token)
    return _public_user_dict(user)


@router.put("/api/auth/profile")
async def update_profile(
    payload: UpdateProfileBody,
    request: Request,
    response: Response,
    db: aiosqlite.Connection = Depends(get_db),
):
    user, token = await require_current_user(request, db)
    email = payload.email.strip()
    display_name = payload.display_name.strip() if payload.display_name else user["display_name"]

    async with db.execute(
        "SELECT 1 FROM users WHERE LOWER(email) = LOWER(?) AND id != ?",
        (email, user["id"]),
    ) as cursor:
        if await cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use.",
            )

    await db.execute(
        "UPDATE users SET email = ?, display_name = ? WHERE id = ?",
        (email, display_name, user["id"]),
    )
    await db.commit()
    _set_session_cookie(response, token)
    updated_user = await db.execute(
        "SELECT * FROM users WHERE id = ?", (user["id"],)
    )
    row = await updated_user.fetchone()
    return _public_user_dict(row or user)


@router.post("/api/auth/password")
async def change_password(
    payload: ChangePasswordBody,
    request: Request,
    response: Response,
    db: aiosqlite.Connection = Depends(get_db),
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
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (new_hash, user["id"]),
    )
    # Invalidate other sessions but keep current one
    await db.execute(
        "DELETE FROM sessions WHERE user_id = ? AND token != ?", (user["id"], token)
    )
    await db.commit()
    _set_session_cookie(response, token)
    return {"ok": True}
