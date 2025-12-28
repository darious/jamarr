import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import asyncpg
from argon2 import PasswordHasher, exceptions as argon2_exceptions
from fastapi import Depends, HTTPException, Request

from app.db import get_db

SESSION_COOKIE_NAME = "jamarr_session"
SESSION_TTL_SECONDS = int(
    os.getenv("SESSION_TTL_SECONDS", str(60 * 60 * 24 * 30))
)  # 30 days default
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
    db: asyncpg.Connection, username_or_email: str
) -> Optional[asyncpg.Record]:
    """Get user by username or email (case-insensitive via citext)."""
    query = """
        SELECT *
        FROM "user"
        WHERE username = $1 OR email = $1
        LIMIT 1
    """
    return await db.fetchrow(query, username_or_email)


async def get_user_by_id(
    db: asyncpg.Connection, user_id: int
) -> Optional[asyncpg.Record]:
    """Get user by ID."""
    return await db.fetchrow('SELECT * FROM "user" WHERE id = $1', user_id)


async def purge_expired_sessions(db: asyncpg.Connection) -> None:
    """Delete expired sessions."""
    await db.execute("DELETE FROM session WHERE expires_at <= NOW()")


async def create_session(
    db: asyncpg.Connection, user_id: int, user_agent: Optional[str], ip: Optional[str]
) -> str:
    """Create a new session and return the token."""
    await purge_expired_sessions(db)
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=SESSION_TTL_SECONDS)

    await db.execute(
        """
        INSERT INTO session (user_id, token, expires_at, user_agent, ip)
        VALUES ($1, $2, $3, $4, $5)
        """,
        user_id,
        token,
        expires_at,
        user_agent,
        ip,
    )
    return token


async def destroy_session(db: asyncpg.Connection, token: str) -> None:
    """Delete a session by token."""
    await db.execute("DELETE FROM session WHERE token = $1", token)


async def get_session_user(
    db: asyncpg.Connection, token: Optional[str]
) -> Tuple[Optional[asyncpg.Record], Optional[str]]:
    """Get user from session token, with sliding expiration."""
    if not token:
        return None, None

    row = await db.fetchrow(
        """
        SELECT u.*, s.expires_at
        FROM session s
        JOIN "user" u ON u.id = s.user_id
        WHERE s.token = $1
        LIMIT 1
        """,
        token,
    )

    if not row:
        return None, token

    now = datetime.now(timezone.utc)
    expires_at = row["expires_at"]
    if expires_at is not None and expires_at < now:
        await destroy_session(db, token)
        return None, token

    # Sliding expiration to keep users logged in
    new_expiration = now + timedelta(seconds=SESSION_TTL_SECONDS)
    await db.execute(
        "UPDATE session SET expires_at = $1 WHERE token = $2", new_expiration, token
    )
    return row, token


async def require_current_user(
    request: Request, db: asyncpg.Connection = Depends(get_db)
) -> Tuple[asyncpg.Record, str]:
    """Dependency to require an authenticated user."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user, token_value = await get_session_user(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user, token_value or token
