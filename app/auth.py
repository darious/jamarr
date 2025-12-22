import os
import secrets
import time
from typing import Optional, Tuple

import aiosqlite
from argon2 import PasswordHasher, exceptions as argon2_exceptions
from fastapi import Depends, HTTPException, Request

from app.db import get_db

SESSION_COOKIE_NAME = "jamarr_session"
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(60 * 60 * 24 * 30)))  # 30 days default
COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except argon2_exceptions.VerifyMismatchError:
        return False
    except Exception:
        return False


async def get_user_by_username_or_email(
    db: aiosqlite.Connection, username_or_email: str
) -> Optional[aiosqlite.Row]:
    query = """
        SELECT *
        FROM users
        WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)
        LIMIT 1
    """
    async with db.execute(query, (username_or_email, username_or_email)) as cursor:
        return await cursor.fetchone()


async def get_user_by_id(db: aiosqlite.Connection, user_id: int) -> Optional[aiosqlite.Row]:
    async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cursor:
        return await cursor.fetchone()


async def purge_expired_sessions(db: aiosqlite.Connection) -> None:
    await db.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))


async def create_session(
    db: aiosqlite.Connection, user_id: int, user_agent: Optional[str], ip: Optional[str]
) -> str:
    await purge_expired_sessions(db)
    token = secrets.token_urlsafe(32)
    expires_at = time.time() + SESSION_TTL_SECONDS
    await db.execute(
        """
        INSERT INTO sessions (user_id, token, expires_at, user_agent, ip)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, token, expires_at, user_agent, ip),
    )
    return token


async def destroy_session(db: aiosqlite.Connection, token: str) -> None:
    await db.execute("DELETE FROM sessions WHERE token = ?", (token,))
    await db.commit()


async def get_session_user(
    db: aiosqlite.Connection, token: Optional[str]
) -> Tuple[Optional[aiosqlite.Row], Optional[str]]:
    if not token:
        return None, None

    async with db.execute(
        """
        SELECT users.*, sessions.expires_at
        FROM sessions
        JOIN users ON users.id = sessions.user_id
        WHERE sessions.token = ?
        LIMIT 1
        """,
        (token,),
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        return None, token

    now_ts = time.time()
    expires_at = row["expires_at"]
    if expires_at is not None and expires_at < now_ts:
        await destroy_session(db, token)
        await db.commit()
        return None, token

    # Sliding expiration to keep users logged in
    new_expiration = now_ts + SESSION_TTL_SECONDS
    await db.execute("UPDATE sessions SET expires_at = ? WHERE token = ?", (new_expiration, token))
    await db.commit()
    return row, token


async def require_current_user(
    request: Request, db: aiosqlite.Connection = Depends(get_db)
) -> Tuple[aiosqlite.Row, str]:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user, token_value = await get_session_user(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user, token_value or token
