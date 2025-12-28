import pytest
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
        # Clean relevant tables
        await conn.execute("""
            TRUNCATE TABLE 
                session,
                client_session,
                renderer_state,
                playback_history,
                track,
                artist,
                album,
                missing_album,
                artwork,
                renderer,
                top_track,
                similar_artist,
                artist_genre,
                external_link,
                image_map,
                track_artist,
                artist_album
            RESTART IDENTITY CASCADE;
        """)
        
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
    """Helper to create a user and log in, returning a session token."""
    user_data = {
        "username": "testuser",
        "email": "test@example.com",
        "password": "password123",
        "display_name": "Test User"
    }

    # 1. Try Signup
    response = await client.post("/api/auth/signup", json=user_data)
    
    if response.status_code == 200:
        return response.cookies["jamarr_session"]

    # 2. If Signup Failed (User Exists), Try Login
    response = await client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "password123"
    })
    
    if response.status_code == 200:
        return response.cookies["jamarr_session"]
        
    # 3. If Login Failed (Stale/Wrong Password), Force Delete and Retry
    # We must use the DB connection to nuke the user since we can't login
    print("Login failed for existing user. Deleting and recreating.")
    await db.execute("DELETE FROM \"user\" WHERE username = $1", "testuser")
    
    # Retry Signup
    response = await client.post("/api/auth/signup", json=user_data)
    assert response.status_code == 200, "Signup failed after user deletion"
    return response.cookies["jamarr_session"]
