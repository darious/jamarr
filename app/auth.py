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
    """Dependency to require an authenticated user.
    
    DEPRECATED: This uses legacy session cookies. Will be replaced with JWT auth.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user, token_value = await get_session_user(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user, token_value or token


# ============================================================================
# Refresh Session Operations (JWT Authentication)
# ============================================================================


async def create_refresh_session(
    db: asyncpg.Connection,
    user_id: int,
    token_hash: str,
    expires_at: datetime,
    user_agent: Optional[str],
    ip: Optional[str],
) -> int:
    """Create a new refresh session and return the session ID.
    
    Args:
        db: Database connection
        user_id: User ID
        token_hash: SHA-256 hash of the refresh token (never store raw tokens)
        expires_at: Expiration timestamp
        user_agent: Optional user agent string
        ip: Optional IP address
        
    Returns:
        Session ID
    """
    session_id = await db.fetchval(
        """
        INSERT INTO auth_refresh_session 
        (user_id, token_hash, created_at, expires_at, last_used_at, user_agent, ip)
        VALUES ($1, $2, NOW(), $3, NOW(), $4, $5)
        RETURNING id
        """,
        user_id,
        token_hash,
        expires_at,
        user_agent,
        ip,
    )
    return session_id


async def get_refresh_session(
    db: asyncpg.Connection, token_hash: str
) -> Optional[asyncpg.Record]:
    """Get refresh session by token hash, joined with user data.
    
    Returns None if:
    - Session doesn't exist
    - Session is revoked (revoked_at is not NULL)
    - Session is expired (expires_at < NOW())
    
    Args:
        db: Database connection
        token_hash: SHA-256 hash of the refresh token
        
    Returns:
        Session record with user data, or None
    """
    row = await db.fetchrow(
        """
        SELECT 
            s.*,
            u.username,
            u.email,
            u.display_name,
            u.is_active
        FROM auth_refresh_session s
        JOIN "user" u ON u.id = s.user_id
        WHERE s.token_hash = $1
          AND s.revoked_at IS NULL
          AND s.expires_at > NOW()
        LIMIT 1
        """,
        token_hash,
    )
    return row


async def revoke_refresh_session(db: asyncpg.Connection, token_hash: str) -> None:
    """Revoke a refresh session by setting revoked_at timestamp.
    
    Args:
        db: Database connection
        token_hash: SHA-256 hash of the refresh token
    """
    await db.execute(
        """
        UPDATE auth_refresh_session
        SET revoked_at = NOW()
        WHERE token_hash = $1
        """,
        token_hash,
    )


async def revoke_all_user_sessions(db: asyncpg.Connection, user_id: int) -> None:
    """Revoke all refresh sessions for a user.
    
    Used for:
    - User-initiated "logout all devices"
    - Admin-initiated session revocation
    - Password change (optional)
    
    Args:
        db: Database connection
        user_id: User ID
    """
    await db.execute(
        """
        UPDATE auth_refresh_session
        SET revoked_at = NOW()
        WHERE user_id = $1 AND revoked_at IS NULL
        """,
        user_id,
    )


async def purge_expired_refresh_sessions(db: asyncpg.Connection) -> None:
    """Delete expired refresh sessions.
    
    This should be run periodically (e.g., daily) to clean up old sessions.
    
    Args:
        db: Database connection
    """
    await db.execute(
        """
        DELETE FROM auth_refresh_session
        WHERE expires_at < NOW()
        """
    )
