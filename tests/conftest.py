import pytest
import asyncio
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
            TRUNCATE TABLE "user" RESTART IDENTITY CASCADE;
            TRUNCATE TABLE session RESTART IDENTITY CASCADE;
            TRUNCATE TABLE client_session RESTART IDENTITY CASCADE;
            TRUNCATE TABLE renderer_state RESTART IDENTITY CASCADE;
            TRUNCATE TABLE playback_history RESTART IDENTITY CASCADE;
            TRUNCATE TABLE track RESTART IDENTITY CASCADE;
            TRUNCATE TABLE artist RESTART IDENTITY CASCADE;
            TRUNCATE TABLE album RESTART IDENTITY CASCADE;
            TRUNCATE TABLE missing_album RESTART IDENTITY CASCADE;
        """)
        
        # Reset ScanManager
        from app.scanner.scan_manager import ScanManager
        try:
            await ScanManager.get_instance().stop_scan()
        except:
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
async def auth_token(client: AsyncClient) -> str:
    """Helper to create a user and log in, returning a session token."""
    # Create user directly via API or DB? API is safer to test full flow
    response = await client.post("/api/auth/signup", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "password123",
        "display_name": "Test User"
    })
    assert response.status_code == 200
    # Cookie is automatically handled by the client jar usually, 
    # but we can return the token string if needed manually.
    return response.cookies["jamarr_session"]
