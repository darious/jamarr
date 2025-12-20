from fastapi.testclient import TestClient
from app.main import app as fastapi_app
from app.db import get_db

import aiosqlite
import os
import asyncio

# Override DB to use a test database
TEST_DB = "test_jamarr.db"

async def override_get_db():
    async with aiosqlite.connect(TEST_DB) as db:
        yield db

# Patch get_db in app.api.player since it's called directly
import app.api.player
app.api.player.get_db = override_get_db

# Patch UPnPManager
from unittest.mock import MagicMock
app.api.player.upnp = MagicMock()
app.api.player.upnp.active_renderer = None # Simulate local playback
app.api.player.upnp.local_ip = "127.0.0.1"

client = TestClient(fastapi_app)

def test_player_persistence():
    # 1. Initial State
    resp = client.get("/api/player/state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["queue"] == []
    assert data["current_index"] == 0

    # 2. Set Queue
    queue = [
        {"id": 1, "title": "Track 1", "artist": "Artist 1", "album": "Album 1", "duration_seconds": 180},
        {"id": 2, "title": "Track 2", "artist": "Artist 1", "album": "Album 1", "duration_seconds": 200}
    ]
    resp = client.post("/api/player/queue", json={"queue": queue, "start_index": 0})
    assert resp.status_code == 200

    # 3. Verify State
    resp = client.get("/api/player/state")
    data = resp.json()
    assert len(data["queue"]) == 2
    assert data["queue"][0]["title"] == "Track 1"
    assert data["current_index"] == 0
    assert data["is_playing"] == True

    # 4. Change Index
    resp = client.post("/api/player/index", json={"index": 1})
    assert resp.status_code == 200

    # 5. Verify Index Change
    resp = client.get("/api/player/state")
    data = resp.json()
    assert data["current_index"] == 1

    # 6. Append Queue
    new_tracks = [
        {"id": 3, "title": "Track 3", "artist": "Artist 2", "album": "Album 2", "duration_seconds": 210}
    ]
    resp = client.post("/api/player/queue/append", json={"tracks": new_tracks})
    assert resp.status_code == 200

    # 7. Verify Append
    resp = client.get("/api/player/state")
    data = resp.json()
    assert len(data["queue"]) == 3
    assert data["queue"][2]["title"] == "Track 3"

    # 8. Update Progress
    resp = client.post("/api/player/progress", json={"position_seconds": 10.5, "is_playing": True})
    assert resp.status_code == 200

    # 9. Verify Progress
    resp = client.get("/api/player/state")
    data = resp.json()
    assert data["position_seconds"] == 10.5

    # 10. Test Play Endpoint (Local)
    # We need to insert the track into the DB first because play_track checks for existence
    # The init_test_db creates the table but doesn't insert tracks.
    # But wait, set_queue uses tracks from the request, it doesn't validate against DB?
    # No, set_queue stores what we send.
    # But play_track does: async with db.execute("SELECT ... FROM tracks WHERE id = ?", (track_id,))
    
    # So we must insert a track.
    async def insert_track():
        async with aiosqlite.connect(TEST_DB) as db:
            await db.execute("INSERT INTO tracks (id, title, path) VALUES (1, 'Track 1', '/tmp/track1.mp3')")
            await db.commit()
    
    asyncio.run(insert_track())

    resp = client.post("/api/player/play", json={"track_id": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "local_playback"

    print("All tests passed!")

if __name__ == "__main__":
    # Remove test DB if exists
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    
    # Initialize DB (we need to run the init_db logic or manually create tables)
    # Since we are using a fresh DB file, we need to create tables.
    # We can use the app's startup event or manually execute SQL.
    # For simplicity, let's just run the test and let the app handle it if possible,
    # but app.lifespan is async.
    
    # Actually, TestClient calls lifespan events.
    # But our lifespan calls `init_db` which uses `app.db.DB_PATH`.
    # We overrode `get_db` but `init_db` uses the global constant or environment variable.
    # Let's manually initialize the test DB schema.
    
    async def init_test_db():
        async with aiosqlite.connect(TEST_DB) as db:
            # Create tables from db.py (simplified for test)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tracks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE,
                    title TEXT,
                    artist TEXT,
                    album TEXT,
                    art_id TEXT,
                    duration_seconds REAL,
                    track_number INTEGER,
                    disc_number INTEGER,
                    genre TEXT,
                    date TEXT,
                    bitrate INTEGER,
                    sample_rate_hz INTEGER,
                    bit_depth INTEGER,
                    codec TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS playback_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    queue TEXT DEFAULT '[]',
                    current_index INTEGER DEFAULT 0,
                    position_seconds REAL DEFAULT 0,
                    is_playing BOOLEAN DEFAULT 0
                )
            """)
            await db.execute("INSERT OR IGNORE INTO playback_state (id) VALUES (1)")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS playback_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    track_id INTEGER NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    client_ip TEXT
                )
            """)
            await db.commit()

    asyncio.run(init_test_db())
    
    try:
        test_player_persistence()
    finally:
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
