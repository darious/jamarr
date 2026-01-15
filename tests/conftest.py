import pytest
import warnings
import os
import asyncpg
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db import init_db, close_db, get_db

# Use the same DB settings as in docker-compose.yml
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "8110"))
DB_USER = os.getenv("DB_USER", "jamarr")
DB_PASS = os.getenv("DB_PASS", "jamarr")
DB_NAME = os.getenv("DB_NAME", "jamarr")

warnings.filterwarnings(
    "ignore",
    message=".*iscoroutinefunction.*",
    category=DeprecationWarning,
    module=r"slowapi\..*",
)


@pytest.fixture(scope="function", autouse=True)
async def setup_db():
    """Initialize DB pool before tests run."""
    # Ensure env vars
    os.environ["DB_HOST"] = DB_HOST
    os.environ["DB_PORT"] = str(DB_PORT)
    os.environ["DB_USER"] = DB_USER
    os.environ["DB_PASS"] = DB_PASS
    os.environ["DB_NAME"] = DB_NAME
    
    await init_db()
    
    # Patch app.db.init_db/close_db to do nothing during lifespan
    from unittest.mock import AsyncMock
    import app.main
    import app.db
    
    orig_init = app.db.init_db
    orig_close = app.db.close_db
    
    app.db.init_db = AsyncMock()
    app.db.close_db = AsyncMock()
    # Also patch the one imported in app.main if it was imported directly
    # app.main uses 'from app.db import init_db, close_db'
    # Use re-import or patch 'app.main.init_db'
    app.main.init_db = AsyncMock()
    app.main.close_db = AsyncMock()

    yield
    
    # Restore
    app.db.init_db = orig_init
    app.db.close_db = orig_close
    await close_db()

@pytest.fixture
async def db() -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Yield a database connection.
    We truncate tables to ensure a clean state for each test.
    """
    async for conn in get_db():
        # Clean relevant tables (only if they exist)
        table_rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        existing = {row["tablename"] for row in table_rows}
        tables = [
            "session",
            "auth_refresh_session",
            "client_session",
            "renderer_state",
            "playback_history",
            "track",
            "artist",
            "album",
            "missing_album",
            "artwork",
            "renderer",
            "top_track",
            "similar_artist",
            "artist_genre",
            "external_link",
            "image_map",
            "lastfm_scrobble",
            "lastfm_scrobble_match",
            "lastfm_skip_artist",
            "track_artist",
            "artist_album",
        ]
        truncate = [t for t in tables if t in existing]
        if truncate:
            await conn.execute(
                f"TRUNCATE TABLE {', '.join(truncate)} RESTART IDENTITY CASCADE;"
            )
        
        # Reset ScanManager
        from app.scanner.scan_manager import ScanManager
        try:
            await ScanManager.get_instance().stop_scan()
        except Exception:
            pass
            
        yield conn

@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """
    Yield an async client for the app.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.fixture
async def auth_token(client: AsyncClient, db: asyncpg.Connection) -> str:
    """Helper to create a user and log in, returning an access token."""
    user_data = {
        "username": "testuser",
        "email": "test@example.com",
        "password": "password123",
        "display_name": "Test User"
    }

    # 1. Try Signup
    response = await client.post("/api/auth/signup", json=user_data)
    
    if response.status_code == 200:
        return response.json()["access_token"]

    # 2. If Signup Failed (User Exists), Try Login
    response = await client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "password123"
    })
    
    if response.status_code == 200:
        return response.json()["access_token"]
        
    # 3. If Login Failed (Stale/Wrong Password), Force Delete and Retry
    # We must use the DB connection to nuke the user since we can't login
    print("Login failed for existing user. Deleting and recreating.")
    await db.execute("DELETE FROM \"user\" WHERE username = $1", "testuser")
    
    # Retry Signup
    response = await client.post("/api/auth/signup", json=user_data)
    assert response.status_code == 200, "Signup failed after user deletion"
    return response.json()["access_token"]


@pytest.fixture
async def auth_headers(auth_token: str) -> dict:
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
async def auth_client(client: AsyncClient, auth_headers: dict) -> AsyncGenerator[AsyncClient, None]:
    client.headers.update(auth_headers)
    yield client
    for key in auth_headers:
        client.headers.pop(key, None)


@pytest.fixture
async def test_user(db: asyncpg.Connection):
    """Create a test user for JWT authentication tests."""
    from app.auth import hash_password
    
    # Delete existing test user if it exists (for test isolation)
    await db.execute('DELETE FROM "user" WHERE username = $1', "testuser_jwt")
    
    user = await db.fetchrow(
        """
        INSERT INTO "user" (username, email, password_hash, display_name, created_at)
        VALUES ($1, $2, $3, $4, NOW())
        RETURNING *
        """,
        "testuser_jwt",
        "testjwt@example.com",
        hash_password("password123"),
        "Test JWT User",
    )
    yield user
    # Cleanup handled by db fixture truncation
