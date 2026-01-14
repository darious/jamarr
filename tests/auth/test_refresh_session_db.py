"""Integration tests for refresh session database operations."""
import pytest
from datetime import datetime, timedelta, timezone
import asyncpg


@pytest.fixture
async def test_user(db: asyncpg.Connection):
    """Create a test user for session tests."""
    user = await db.fetchrow(
        """
        INSERT INTO "user" (username, email, password_hash, display_name, created_at)
        VALUES ($1, $2, $3, $4, NOW())
        RETURNING *
        """,
        "testuser_session",
        "testsession@example.com",
        "hashed_password",
        "Test Session User",
    )
    yield user
    # Cleanup
    await db.execute('DELETE FROM "user" WHERE id = $1', user["id"])


@pytest.mark.asyncio
async def test_create_refresh_session(db: asyncpg.Connection, test_user):
    """Test creating a refresh session."""
    from app.auth import create_refresh_session
    from app.auth_tokens import hash_refresh_token
    
    token = "test-refresh-token-123"
    token_hash = hash_refresh_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=21)
    
    session_id = await create_refresh_session(
        db=db,
        user_id=test_user["id"],
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent="Mozilla/5.0 Test",
        ip="REDACTED_IP"
    )
    
    assert session_id is not None
    
    # Verify session was created
    session = await db.fetchrow(
        "SELECT * FROM auth_refresh_session WHERE id = $1",
        session_id
    )
    
    assert session is not None
    assert session["user_id"] == test_user["id"]
    assert session["token_hash"] == token_hash
    assert session["revoked_at"] is None
    assert session["user_agent"] == "Mozilla/5.0 Test"
    assert session["ip"] == "REDACTED_IP"


@pytest.mark.asyncio
async def test_get_refresh_session_valid(db: asyncpg.Connection, test_user):
    """Test retrieving a valid refresh session."""
    from app.auth import create_refresh_session, get_refresh_session
    from app.auth_tokens import hash_refresh_token
    
    token = "test-refresh-token-456"
    token_hash = hash_refresh_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=21)
    
    await create_refresh_session(
        db=db,
        user_id=test_user["id"],
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent="Test Agent",
        ip="REDACTED_IP"
    )
    
    # Retrieve session
    session = await get_refresh_session(db, token_hash)
    
    assert session is not None
    assert session["user_id"] == test_user["id"]
    assert session["username"] == test_user["username"]
    assert session["email"] == test_user["email"]
    assert session["revoked_at"] is None


@pytest.mark.asyncio
async def test_get_refresh_session_revoked(db: asyncpg.Connection, test_user):
    """Test that revoked sessions return None."""
    from app.auth import create_refresh_session, get_refresh_session, revoke_refresh_session
    from app.auth_tokens import hash_refresh_token
    
    token = "test-refresh-token-789"
    token_hash = hash_refresh_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=21)
    
    await create_refresh_session(
        db=db,
        user_id=test_user["id"],
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent=None,
        ip=None
    )
    
    # Revoke the session
    await revoke_refresh_session(db, token_hash)
    
    # Should return None for revoked session
    session = await get_refresh_session(db, token_hash)
    assert session is None


@pytest.mark.asyncio
async def test_get_refresh_session_expired(db: asyncpg.Connection, test_user):
    """Test that expired sessions return None."""
    from app.auth import create_refresh_session, get_refresh_session
    from app.auth_tokens import hash_refresh_token
    
    token = "test-refresh-token-expired"
    token_hash = hash_refresh_token(token)
    # Already expired
    expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    
    await create_refresh_session(
        db=db,
        user_id=test_user["id"],
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent=None,
        ip=None
    )
    
    # Should return None for expired session
    session = await get_refresh_session(db, token_hash)
    assert session is None


@pytest.mark.asyncio
async def test_revoke_refresh_session(db: asyncpg.Connection, test_user):
    """Test revoking a refresh session."""
    from app.auth import create_refresh_session, revoke_refresh_session
    from app.auth_tokens import hash_refresh_token
    
    token = "test-refresh-token-revoke"
    token_hash = hash_refresh_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=21)
    
    session_id = await create_refresh_session(
        db=db,
        user_id=test_user["id"],
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent=None,
        ip=None
    )
    
    # Revoke the session
    await revoke_refresh_session(db, token_hash)
    
    # Verify revoked_at is set
    session = await db.fetchrow(
        "SELECT * FROM auth_refresh_session WHERE id = $1",
        session_id
    )
    
    assert session["revoked_at"] is not None
    assert isinstance(session["revoked_at"], datetime)


@pytest.mark.asyncio
async def test_revoke_all_user_sessions(db: asyncpg.Connection, test_user):
    """Test revoking all sessions for a user."""
    from app.auth import create_refresh_session, revoke_all_user_sessions
    from app.auth_tokens import hash_refresh_token, generate_refresh_token
    
    expires_at = datetime.now(timezone.utc) + timedelta(days=21)
    
    # Create multiple sessions
    session_ids = []
    for i in range(3):
        token = generate_refresh_token()
        token_hash = hash_refresh_token(token)
        session_id = await create_refresh_session(
            db=db,
            user_id=test_user["id"],
            token_hash=token_hash,
            expires_at=expires_at,
            user_agent=f"Agent {i}",
            ip=None
        )
        session_ids.append(session_id)
    
    # Revoke all sessions
    await revoke_all_user_sessions(db, test_user["id"])
    
    # Verify all sessions are revoked
    for session_id in session_ids:
        session = await db.fetchrow(
            "SELECT * FROM auth_refresh_session WHERE id = $1",
            session_id
        )
        assert session["revoked_at"] is not None


@pytest.mark.asyncio
async def test_purge_expired_refresh_sessions(db: asyncpg.Connection, test_user):
    """Test purging expired refresh sessions."""
    from app.auth import create_refresh_session, purge_expired_refresh_sessions
    from app.auth_tokens import hash_refresh_token, generate_refresh_token
    
    # Create expired session
    expired_token = generate_refresh_token()
    expired_hash = hash_refresh_token(expired_token)
    expired_at = datetime.now(timezone.utc) - timedelta(days=1)
    
    expired_id = await create_refresh_session(
        db=db,
        user_id=test_user["id"],
        token_hash=expired_hash,
        expires_at=expired_at,
        user_agent=None,
        ip=None
    )
    
    # Create valid session
    valid_token = generate_refresh_token()
    valid_hash = hash_refresh_token(valid_token)
    valid_expires = datetime.now(timezone.utc) + timedelta(days=21)
    
    valid_id = await create_refresh_session(
        db=db,
        user_id=test_user["id"],
        token_hash=valid_hash,
        expires_at=valid_expires,
        user_agent=None,
        ip=None
    )
    
    # Purge expired sessions
    await purge_expired_refresh_sessions(db)
    
    # Expired session should be deleted
    expired_session = await db.fetchrow(
        "SELECT * FROM auth_refresh_session WHERE id = $1",
        expired_id
    )
    assert expired_session is None
    
    # Valid session should still exist
    valid_session = await db.fetchrow(
        "SELECT * FROM auth_refresh_session WHERE id = $1",
        valid_id
    )
    assert valid_session is not None


@pytest.mark.asyncio
async def test_multiple_sessions_per_user(db: asyncpg.Connection, test_user):
    """Test that users can have multiple active sessions."""
    from app.auth import create_refresh_session, get_refresh_session
    from app.auth_tokens import hash_refresh_token, generate_refresh_token
    
    expires_at = datetime.now(timezone.utc) + timedelta(days=21)
    
    # Create multiple sessions for same user
    tokens = []
    for i in range(5):
        token = generate_refresh_token()
        token_hash = hash_refresh_token(token)
        await create_refresh_session(
            db=db,
            user_id=test_user["id"],
            token_hash=token_hash,
            expires_at=expires_at,
            user_agent=f"Device {i}",
            ip=None
        )
        tokens.append(token)
    
    # All sessions should be retrievable
    for token in tokens:
        token_hash = hash_refresh_token(token)
        session = await get_refresh_session(db, token_hash)
        assert session is not None
        assert session["user_id"] == test_user["id"]
