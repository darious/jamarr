import pytest
from httpx import AsyncClient

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
async def test_player_state_initial(auth_client: AsyncClient, db):
    # Initial state should be empty/stopped
    response = await auth_client.get("/api/player/state", headers={"X-Jamarr-Client-Id": "test-client"})
    assert response.status_code == 200
    data = response.json()
    assert data["queue"] == []
    assert data["transport_state"] == "STOPPED"
    assert "local:test-client" in data["renderer"]

@pytest.mark.asyncio
async def test_set_queue(auth_client: AsyncClient, db, player_data):
    # Set queue
    track1 = {"id": 10, "title": "Song A", "artist": "Artist A", "path": "/music/t1.flac", "duration_seconds": 200, "album": "Album A"}
    track2 = {"id": 11, "title": "Song B", "artist": "Artist A", "path": "/music/t2.flac", "duration_seconds": 200, "album": "Album A"}
    
    response = await auth_client.post("/api/player/queue", 
        json={"queue": [track1, track2], "start_index": 0},
        headers={"X-Jamarr-Client-Id": "test-client"}
    )
    assert response.status_code == 200, response.text
    
    # Verify State
    response = await auth_client.get("/api/player/state", headers={"X-Jamarr-Client-Id": "test-client"})
    data = response.json()
    assert len(data["queue"]) == 2
    assert data["current_index"] == 0
    # Note: Without actual file on disk, play might fail in background or skip?
    # In test environment, files don't exist, so UPnP logic might fail. 
    # But database state should be updated initially.

@pytest.mark.asyncio
async def test_append_queue(auth_client: AsyncClient, db, player_data):
    # Setup initial queue
    track1 = {"id": 10, "title": "Song A", "artist": "Artist A", "path": "/music/t1.flac", "duration_seconds": 200, "album": "Album A"}
    await auth_client.post("/api/player/queue", 
        json={"queue": [track1], "start_index": 0},
        headers={"X-Jamarr-Client-Id": "test-client"}
    )
    
    # Append
    track3 = {"id": 12, "title": "Song C", "artist": "Artist B", "path": "/music/t3.flac", "duration_seconds": 300, "album": "Album B"}
    response = await auth_client.post("/api/player/queue/append",
        json={"tracks": [track3]},
        headers={"X-Jamarr-Client-Id": "test-client"}
    )
    assert response.status_code == 200
    
    # Verify
    response = await auth_client.get("/api/player/state", headers={"X-Jamarr-Client-Id": "test-client"})
    data = response.json()
    assert len(data["queue"]) == 2
    assert data["queue"][1]["title"] == "Song C"

@pytest.mark.asyncio
async def test_set_index(auth_client: AsyncClient, db, player_data):
    # Setup queue with multiple items
    track1 = {"id": 10, "title": "Song A", "artist": "Artist A", "path": "/music/t1.flac", "duration_seconds": 200, "album": "Album A"}
    track2 = {"id": 11, "title": "Song B", "artist": "Artist A", "path": "/music/t2.flac", "duration_seconds": 200, "album": "Album A"}
    await auth_client.post("/api/player/queue", 
        json={"queue": [track1, track2], "start_index": 0},
        headers={"X-Jamarr-Client-Id": "test-client"}
    )
    
    # Skip to next
    response = await auth_client.post("/api/player/index",
        json={"index": 1},
        headers={"X-Jamarr-Client-Id": "test-client"}
    )
    assert response.status_code == 200
    
    # Verify
    response = await auth_client.get("/api/player/state", headers={"X-Jamarr-Client-Id": "test-client"})
    data = response.json()
    assert data["current_index"] == 1

@pytest.mark.asyncio
async def test_history(auth_client: AsyncClient, db, player_data):
    # Retrieve History (empty)
    response = await auth_client.get("/api/history/tracks")
    assert response.status_code == 200
    assert response.json() == []
    
    # Insert dummy history
    await db.execute("""
        INSERT INTO playback_history (track_id, client_ip, user_id, timestamp)
        VALUES (10, '127.0.0.1', NULL, NOW())
    """)
    await db.execute("REFRESH MATERIALIZED VIEW combined_playback_history_mat")
    
    response = await auth_client.get("/api/history/tracks")
    data = response.json()
    assert len(data) == 1
    assert data[0]["track"]["id"] == 10
    
    # Stats
    response = await auth_client.get("/api/history/stats")
    data = response.json()
    assert len(data["tracks"]) == 1
    assert data["tracks"][0]["plays"] == 1

@pytest.mark.asyncio
async def test_transport_controls(auth_client: AsyncClient, db, player_data):
    headers = {"X-Jamarr-Client-Id": "test-client"}
    
    # 1. Volume
    response = await auth_client.post("/api/player/volume", json={"percent": 50}, headers=headers)
    assert response.status_code == 200, response.text
    
    # 2. Seek
    response = await auth_client.post("/api/player/seek", json={"seconds": 30}, headers=headers)
    assert response.status_code == 200
    
    # 3. Pause
    response = await auth_client.post("/api/player/pause", headers=headers)
    assert response.status_code == 200
    
    # 4. Resume
    response = await auth_client.post("/api/player/resume", headers=headers)
    assert response.status_code == 200
    
    # 5. Play (requires queue)
    # Set queue first
    track1 = {"id": 10, "title": "Song A", "artist": "Artist A", "path": "/music/t1.flac", "duration_seconds": 200, "album": "Album A"}
    await auth_client.post("/api/player/queue", json={"queue": [track1], "start_index": 0}, headers=headers)
    
    response = await auth_client.post("/api/player/play", json={"track_id": 10}, headers=headers)
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_log_play_legacy(auth_client: AsyncClient, db, player_data):
    """Test legacy log-play endpoint (now a no-op but returns 200)."""
    response = await auth_client.post("/api/player/log-play", 
        json={"track_id": 10, "timestamp": "2023-01-01T12:00:00"},
        headers={"X-Jamarr-Client-Id": "test-client"}
    )
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_progress_logs_history(auth_client: AsyncClient, db, player_data):
    """Test that progress updates trigger history logging."""
    headers = {"X-Jamarr-Client-Id": "test-client"}
    
    # Setup Queue
    track1 = {"id": 10, "title": "Song A", "artist": "Artist A", "path": "/music/t1.flac", "duration_seconds": 200, "album": "Album A"}
    await auth_client.post("/api/player/queue", json={"queue": [track1], "start_index": 0}, headers=headers)
    
    # Send Progress update > threshold (threshold is min(30, 20% of 200 = 40)) -> 30s
    # Sending 35 seconds should trigger log
    response = await auth_client.post("/api/player/progress", 
        json={"position_seconds": 35, "is_playing": True},
        headers=headers
    )
    assert response.status_code == 200
    
    # Verify insertion
    rows = await db.fetch("SELECT * FROM playback_history WHERE track_id = 10")
    assert len(rows) == 1

    # Verify automatic materialized view refresh via API
    # The stats endpoint should now reflect the new play without manual refresh
    response = await auth_client.get("/api/history/stats")
    stats = response.json()
    assert len(stats["tracks"]) == 1
    assert stats["tracks"][0]["plays"] == 1

    # Verify state persistence (logged flag)
    response = await auth_client.get("/api/player/state", headers=headers)
    state = response.json()
    assert state['queue'][0]['logged'] is True

    # Send another progress update, should NOT log again
    response = await auth_client.post("/api/player/progress", 
        json={"position_seconds": 40, "is_playing": True},
        headers=headers
    )
    assert response.status_code == 200
    
    rows = await db.fetch("SELECT * FROM playback_history WHERE track_id = 10")
    assert len(rows) == 1

@pytest.mark.asyncio
async def test_renderers(auth_client: AsyncClient, db):
    response = await auth_client.get("/api/renderers")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # Checks structure of renderer items if any exist (local always exists?)
    for renderer in data:
        assert "udn" in renderer
        assert "name" in renderer
        assert "type" in renderer

@pytest.mark.asyncio
async def test_queue_artwork(auth_client: AsyncClient, db):
    # Insert artwork
    await db.execute("INSERT INTO artwork (id, sha1, path_on_disk) VALUES (900, '999999', '/tmp/art.jpg')")
    # Insert track with artwork
    await db.execute("""
        INSERT INTO track (id, path, title, artist, album, duration_seconds, artwork_id)
        VALUES (20, '/music/art.flac', 'Art Song', 'Art Artist', 'Art Album', 100, 900)
    """)
    
    track = {"id": 20, "title": "Art Song", "artist": "Art Artist", "path": "/music/art.flac", "duration_seconds": 100, "album": "Art Album", "art_sha1": "999999"}
    
    # Set Queue
    await auth_client.post("/api/player/queue", 
        json={"queue": [track], "start_index": 0},
        headers={"X-Jamarr-Client-Id": "test-client"}
    )
    
    # Check State
    response = await auth_client.get("/api/player/state", headers={"X-Jamarr-Client-Id": "test-client"})
    data = response.json()
    q_track = data["queue"][0]
    assert q_track["art_sha1"] == "999999"

@pytest.mark.asyncio
async def test_clear_queue_stops_playback(auth_client: AsyncClient, db, player_data):
    headers = {"X-Jamarr-Client-Id": "test-client"}
    track1 = {"id": 10, "title": "Song A", "artist": "Artist A", "path": "/music/t1.flac", "duration_seconds": 200, "album": "Album A"}
    track2 = {"id": 11, "title": "Song B", "artist": "Artist A", "path": "/music/t2.flac", "duration_seconds": 200, "album": "Album A"}

    await auth_client.post("/api/player/queue", json={"queue": [track1, track2], "start_index": 0}, headers=headers)

    resp = await auth_client.post("/api/player/queue/clear", headers=headers)
    assert resp.status_code == 200, resp.text
    cleared = resp.json()["state"]
    assert cleared["queue"] == []
    assert cleared["current_index"] == -1
    assert cleared["is_playing"] is False
    assert cleared["transport_state"] == "STOPPED"

    # Verify persisted state
    state_resp = await auth_client.get("/api/player/state", headers=headers)
    state = state_resp.json()
    assert state["queue"] == []
    assert state["current_index"] == -1
    assert state["is_playing"] is False
    assert state["transport_state"] == "STOPPED"


@pytest.mark.asyncio
async def test_reorder_queue_preserves_current_track(auth_client: AsyncClient, db, player_data):
    headers = {"X-Jamarr-Client-Id": "test-client"}
    track1 = {"id": 10, "title": "Song A", "artist": "Artist A", "path": "/music/t1.flac", "duration_seconds": 200, "album": "Album A"}
    track2 = {"id": 11, "title": "Song B", "artist": "Artist A", "path": "/music/t2.flac", "duration_seconds": 200, "album": "Album A"}
    track3 = {"id": 12, "title": "Song C", "artist": "Artist B", "path": "/music/t3.flac", "duration_seconds": 300, "album": "Album B"}

    # set queue and play second track
    await auth_client.post("/api/player/queue", json={"queue": [track1, track2, track3], "start_index": 1}, headers=headers)

    # reorder: move last to front
    resp = await auth_client.post("/api/player/queue/reorder", json={"queue": [track3, track1, track2]}, headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["state"]
    assert [t["id"] for t in data["queue"]] == [12, 10, 11]
    # current track (id 11) should now be at index 2
    assert data["current_index"] == 2

    # persisted state
    state_resp = await auth_client.get("/api/player/state", headers=headers)
    state = state_resp.json()
    assert [t["id"] for t in state["queue"]] == [12, 10, 11]
    assert state["current_index"] == 2


@pytest.mark.asyncio
async def test_set_renderer_persists_session(auth_client: AsyncClient, db):
    """Ensure renderer selection succeeds and stores auth_client session mapping."""
    headers = {"X-Jamarr-Client-Id": "renderer-test"}
    udn = "uuid:6be59c1-eebb-41d6-9f70-b25a08e60797"

    resp = await auth_client.post("/api/player/renderer", json={"udn": udn}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["active"] == udn
    row = await db.fetchrow("SELECT active_renderer_udn FROM client_session WHERE client_id=$1", "renderer-test")
    assert row and row["active_renderer_udn"] == udn

@pytest.mark.asyncio
async def test_history_grouping(auth_client: AsyncClient, db, auth_token):
    # Create artist first
    import uuid
    artist_mbid = str(uuid.uuid4())
    await db.execute("""
        INSERT INTO artist (mbid, name)
        VALUES ($1, 'Main')
    """, artist_mbid)
    
    # Insert Album Artist = "Main", Artist = "Main"
    await db.execute("""
        INSERT INTO track (id, title, artist, album_artist, album, duration_seconds, track_no, path, artist_mbid)
        VALUES (101, 'Solo', 'Main', 'Main', 'AlbumX', 200, 1, '/music/solo.flac', $1)
    """, artist_mbid)
    
    # Insert Album Artist = "Main", Artist = "Main & Feat"
    await db.execute("""
        INSERT INTO track (id, title, artist, album_artist, album, duration_seconds, track_no, path, artist_mbid)
        VALUES (102, 'Feat', 'Main & Feat', 'Main', 'AlbumX', 200, 2, '/music/feat.flac', $1)
    """, artist_mbid)
    
    # Create track_artist entries (required for canonical join)
    await db.execute("""
        INSERT INTO track_artist (track_id, artist_mbid)
        VALUES (101, $1), (102, $1)
    """, artist_mbid)
    
    # Log plays for both
    for tid in [101, 102]:
        await db.execute(
            "INSERT INTO playback_history (track_id, timestamp, client_ip) VALUES ($1, NOW(), '127.0.0.1')",
            tid
        )
    await db.execute("REFRESH MATERIALIZED VIEW combined_playback_history_mat")
        
    response = await auth_client.get("/api/history/stats")
    stats = response.json()
    
    # Expect 1 Artist entry ("Main") with 2 plays
    artists = stats["artists"]
    assert len(artists) == 1
    assert artists[0]["artist"] == "Main"
    assert artists[0]["plays"] == 2
    
    # Expect 1 Album entry ("AlbumX") with 2 plays
    albums = stats["albums"]
    assert len(albums) == 1
    assert albums[0]["album"] == "AlbumX"
    assert albums[0]["plays"] == 2

@pytest.mark.asyncio
async def test_history_stats_mine_scope(auth_client: AsyncClient, db, player_data, auth_token):
    # Get user id from generated token
    user = await db.fetchrow("SELECT id FROM \"user\" WHERE username = $1", "testuser")
    assert user is not None
    user_id = user["id"]

    # Insert history for this user
    await db.execute("""
        INSERT INTO playback_history (track_id, client_ip, user_id, timestamp)
        VALUES (10, '127.0.0.1', $1, NOW())
    """, user_id)
    await db.execute("REFRESH MATERIALIZED VIEW combined_playback_history_mat")
    
    # Request with scope=mine
    response = await auth_client.get("/api/history/stats?scope=mine")
    assert response.status_code == 200
    data = response.json()
    assert len(data["tracks"]) >= 1
    assert data["tracks"][0]["plays"] == 1


@pytest.mark.asyncio
async def test_scrobble_triggers_on_history_log(auth_client: AsyncClient, db, player_data, auth_token):
    """Test that logging history triggers Last.fm scrobble for enabled users."""
    from unittest.mock import patch, AsyncMock
    
    # Get user id
    user = await db.fetchrow('SELECT id FROM "user" WHERE username = $1', "testuser")
    user_id = user["id"]
    
    # Setup Last.fm credentials for user
    await db.execute(
        """
        UPDATE "user"
        SET lastfm_username = $1,
            lastfm_session_key = $2,
            lastfm_enabled = $3
        WHERE id = $4
        """,
        "testuser_lastfm",
        "test_session_key",
        True,
        user_id
    )
    
    # Mock Last.fm scrobble function
    with patch('app.lastfm.scrobble_track', new_callable=AsyncMock) as mock_scrobble:
        # Setup queue and trigger progress to log history
        headers = {"X-Jamarr-Client-Id": "test-client"}
        
        track1 = {
            "id": 10,
            "title": "Song A",
            "artist": "Artist A",
            "path": "/music/t1.flac",
            "duration_seconds": 200,
            "album": "Album A",
            "user_id": user_id
        }
        
        await auth_client.post("/api/player/queue", json={"queue": [track1], "start_index": 0}, headers=headers)
        
        # Send progress to trigger history log (and scrobble)
        await auth_client.post("/api/player/progress", 
            json={"position_seconds": 35, "is_playing": True},
            headers=headers
        )
        
        # Give async task time to execute
        import asyncio
        await asyncio.sleep(0.1)
        
        # Verify scrobble was called
        assert mock_scrobble.called
        call_args = mock_scrobble.call_args
        assert call_args[1]["session_key"] == "test_session_key"
        assert call_args[1]["track_info"]["track"] == "Song A"
        assert call_args[1]["track_info"]["artist"] == "Artist A"


@pytest.mark.asyncio
async def test_scrobble_skipped_when_disabled(auth_client: AsyncClient, db, player_data, auth_token):
    """Test that scrobbling is skipped when Last.fm is disabled."""
    from unittest.mock import patch, AsyncMock
    
    # Get user id
    user = await db.fetchrow('SELECT id FROM "user" WHERE username = $1', "testuser")
    user_id = user["id"]
    
    # Setup Last.fm credentials but disabled
    await db.execute(
        """
        UPDATE "user"
        SET lastfm_username = $1,
            lastfm_session_key = $2,
            lastfm_enabled = $3
        WHERE id = $4
        """,
        "testuser_lastfm",
        "test_session_key",
        False,  # Disabled
        user_id
    )
    
    # Mock Last.fm scrobble function
    with patch('app.lastfm.scrobble_track', new_callable=AsyncMock) as mock_scrobble:
        headers = {"X-Jamarr-Client-Id": "test-client"}
        
        track1 = {
            "id": 10,
            "title": "Song A",
            "artist": "Artist A",
            "path": "/music/t1.flac",
            "duration_seconds": 200,
            "album": "Album A",
            "user_id": user_id
        }
        
        await auth_client.post("/api/player/queue", json={"queue": [track1], "start_index": 0}, headers=headers)
        await auth_client.post("/api/player/progress", 
            json={"position_seconds": 35, "is_playing": True},
            headers=headers
        )
        
        import asyncio
        await asyncio.sleep(0.1)
        
        # Verify scrobble was NOT called
        assert not mock_scrobble.called


@pytest.mark.asyncio
async def test_scrobble_skipped_without_session_key(auth_client: AsyncClient, db, player_data, auth_token):
    """Test that scrobbling is skipped when user has no session key."""
    from unittest.mock import patch, AsyncMock
    
    # Get user id
    user = await db.fetchrow('SELECT id FROM "user" WHERE username = $1', "testuser")
    user_id = user["id"]
    
    # No Last.fm setup for user (default state)
    
    # Mock Last.fm scrobble function
    with patch('app.lastfm.scrobble_track', new_callable=AsyncMock) as mock_scrobble:
        headers = {"X-Jamarr-Client-Id": "test-client"}
        
        track1 = {
            "id": 10,
            "title": "Song A",
            "artist": "Artist A",
            "path": "/music/t1.flac",
            "duration_seconds": 200,
            "album": "Album A",
            "user_id": user_id
        }
        
        await auth_client.post("/api/player/queue", json={"queue": [track1], "start_index": 0}, headers=headers)
        await auth_client.post("/api/player/progress", 
            json={"position_seconds": 35, "is_playing": True},
            headers=headers
        )
        
        import asyncio
        await asyncio.sleep(0.1)
        
        # Verify scrobble was NOT called
        assert not mock_scrobble.called
