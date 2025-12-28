import pytest
from httpx import AsyncClient
import json

@pytest.fixture
async def player_data(db):
    """Insert tracks for player tests."""
    await db.execute("""
        INSERT INTO track (id, path, title, artist, album, duration_seconds)
        VALUES 
            (10, '/music/t1.flac', 'Song A', 'Artist A', 'Album A', 200),
            (11, '/music/t2.flac', 'Song B', 'Artist A', 'Album A', 200),
            (12, '/music/t3.flac', 'Song C', 'Artist B', 'Album B', 300)
    """)

@pytest.mark.asyncio
async def test_player_state_initial(client: AsyncClient, db):
    # Initial state should be empty/stopped
    response = await client.get("/api/player/state", headers={"X-Jamarr-Client-Id": "test-client"})
    assert response.status_code == 200
    data = response.json()
    assert data["queue"] == []
    assert data["transport_state"] == "STOPPED"
    assert "local:test-client" in data["renderer"]

@pytest.mark.asyncio
async def test_set_queue(client: AsyncClient, db, player_data):
    # Set queue
    track1 = {"id": 10, "title": "Song A", "artist": "Artist A", "path": "/music/t1.flac", "duration_seconds": 200, "album": "Album A"}
    track2 = {"id": 11, "title": "Song B", "artist": "Artist A", "path": "/music/t2.flac", "duration_seconds": 200, "album": "Album A"}
    
    response = await client.post("/api/player/queue", 
        json={"queue": [track1, track2], "start_index": 0},
        headers={"X-Jamarr-Client-Id": "test-client"}
    )
    assert response.status_code == 200, response.text
    
    # Verify State
    response = await client.get("/api/player/state", headers={"X-Jamarr-Client-Id": "test-client"})
    data = response.json()
    assert len(data["queue"]) == 2
    assert data["current_index"] == 0
    # Note: Without actual file on disk, play might fail in background or skip?
    # In test environment, files don't exist, so UPnP logic might fail. 
    # But database state should be updated initially.

@pytest.mark.asyncio
async def test_append_queue(client: AsyncClient, db, player_data):
    # Setup initial queue
    track1 = {"id": 10, "title": "Song A", "artist": "Artist A", "path": "/music/t1.flac", "duration_seconds": 200, "album": "Album A"}
    await client.post("/api/player/queue", 
        json={"queue": [track1], "start_index": 0},
        headers={"X-Jamarr-Client-Id": "test-client"}
    )
    
    # Append
    track3 = {"id": 12, "title": "Song C", "artist": "Artist B", "path": "/music/t3.flac", "duration_seconds": 300, "album": "Album B"}
    response = await client.post("/api/player/queue/append",
        json={"tracks": [track3]},
        headers={"X-Jamarr-Client-Id": "test-client"}
    )
    assert response.status_code == 200
    
    # Verify
    response = await client.get("/api/player/state", headers={"X-Jamarr-Client-Id": "test-client"})
    data = response.json()
    assert len(data["queue"]) == 2
    assert data["queue"][1]["title"] == "Song C"

@pytest.mark.asyncio
async def test_set_index(client: AsyncClient, db, player_data):
    # Setup queue with multiple items
    track1 = {"id": 10, "title": "Song A", "artist": "Artist A", "path": "/music/t1.flac", "duration_seconds": 200, "album": "Album A"}
    track2 = {"id": 11, "title": "Song B", "artist": "Artist A", "path": "/music/t2.flac", "duration_seconds": 200, "album": "Album A"}
    await client.post("/api/player/queue", 
        json={"queue": [track1, track2], "start_index": 0},
        headers={"X-Jamarr-Client-Id": "test-client"}
    )
    
    # Skip to next
    response = await client.post("/api/player/index",
        json={"index": 1},
        headers={"X-Jamarr-Client-Id": "test-client"}
    )
    assert response.status_code == 200
    
    # Verify
    response = await client.get("/api/player/state", headers={"X-Jamarr-Client-Id": "test-client"})
    data = response.json()
    assert data["current_index"] == 1

@pytest.mark.asyncio
async def test_history(client: AsyncClient, db, player_data):
    # Retrieve History (empty)
    response = await client.get("/api/player/history")
    assert response.status_code == 200
    assert response.json() == []
    
    # Insert dummy history
    await db.execute("""
        INSERT INTO playback_history (track_id, client_ip, user_id, timestamp)
        VALUES (10, '127.0.0.1', NULL, NOW())
    """)
    
    response = await client.get("/api/player/history")
    data = response.json()
    assert len(data) == 1
    assert data[0]["track"]["id"] == 10
    
    # Stats
    response = await client.get("/api/player/history/stats")
    data = response.json()
    assert len(data["tracks"]) == 1
    assert data["tracks"][0]["plays"] == 1

@pytest.mark.asyncio
async def test_transport_controls(client: AsyncClient, db, player_data):
    headers = {"X-Jamarr-Client-Id": "test-client"}
    
    # 1. Volume
    response = await client.post("/api/player/volume", json={"percent": 50}, headers=headers)
    assert response.status_code == 200, response.text
    
    # 2. Seek
    response = await client.post("/api/player/seek", json={"seconds": 30}, headers=headers)
    assert response.status_code == 200
    
    # 3. Pause
    response = await client.post("/api/player/pause", headers=headers)
    assert response.status_code == 200
    
    # 4. Resume
    response = await client.post("/api/player/resume", headers=headers)
    assert response.status_code == 200
    
    # 5. Play (requires queue)
    # Set queue first
    track1 = {"id": 10, "title": "Song A", "artist": "Artist A", "path": "/music/t1.flac", "duration_seconds": 200, "album": "Album A"}
    await client.post("/api/player/queue", json={"queue": [track1], "start_index": 0}, headers=headers)
    
    response = await client.post("/api/player/play", json={"track_id": 10}, headers=headers)
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_log_play_legacy(client: AsyncClient, db, player_data):
    """Test legacy log-play endpoint (now a no-op but returns 200)."""
    response = await client.post("/api/player/log-play", 
        json={"track_id": 10, "timestamp": "2023-01-01T12:00:00"},
        headers={"X-Jamarr-Client-Id": "test-client"}
    )
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_progress_logs_history(client: AsyncClient, db, player_data):
    """Test that progress updates trigger history logging."""
    headers = {"X-Jamarr-Client-Id": "test-client"}
    
    # Setup Queue
    track1 = {"id": 10, "title": "Song A", "artist": "Artist A", "path": "/music/t1.flac", "duration_seconds": 200, "album": "Album A"}
    await client.post("/api/player/queue", json={"queue": [track1], "start_index": 0}, headers=headers)
    
    # Send Progress update > threshold (threshold is min(30, 20% of 200 = 40)) -> 30s
    # Sending 35 seconds should trigger log
    response = await client.post("/api/player/progress", 
        json={"position_seconds": 35, "is_playing": True},
        headers=headers
    )
    assert response.status_code == 200
    
    # Verify insertion
    # Allow small delay for async db ops if any (though here it's awaited)
    rows = await db.fetch("SELECT * FROM playback_history WHERE track_id = 10")
    assert len(rows) > 0

@pytest.mark.asyncio
async def test_renderers(client: AsyncClient, db):
    response = await client.get("/api/renderers")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # Checks structure of renderer items if any exist (local always exists?)
    for renderer in data:
        assert "udn" in renderer
        assert "name" in renderer
        assert "type" in renderer

@pytest.mark.asyncio
async def test_queue_artwork(client: AsyncClient, db):
    # Insert artwork
    await db.execute("INSERT INTO artwork (id, sha1, path_on_disk) VALUES (900, '999999', '/tmp/art.jpg')")
    # Insert track with artwork
    await db.execute("""
        INSERT INTO track (id, path, title, artist, album, duration_seconds, artwork_id)
        VALUES (20, '/music/art.flac', 'Art Song', 'Art Artist', 'Art Album', 100, 900)
    """)
    
    track = {"id": 20, "title": "Art Song", "artist": "Art Artist", "path": "/music/art.flac", "duration_seconds": 100, "album": "Art Album", "art_id": 900, "art_sha1": "999999"}
    
    # Set Queue
    await client.post("/api/player/queue", 
        json={"queue": [track], "start_index": 0},
        headers={"X-Jamarr-Client-Id": "test-client"}
    )
    
    # Check State
    response = await client.get("/api/player/state", headers={"X-Jamarr-Client-Id": "test-client"})
    data = response.json()
    q_track = data["queue"][0]
    assert q_track["art_id"] == 900
    assert q_track["art_sha1"] == "999999"
