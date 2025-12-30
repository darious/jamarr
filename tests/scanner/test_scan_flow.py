
import pytest
from app.scanner.scan_manager import ScanManager
from app.scanner.services.coordinator import MetadataCoordinator

@pytest.mark.asyncio
async def test_full_metadata_scan_flow(db, monkeypatch):
    """
    End-to-End Test: Triggers a full metadata scan against a live test database.
    Verifies that:
    1. The scanner initializes and connects to the DB.
    2. Artists with external links are correctly fetched (covering the SQL fix).
    3. The MetadataCoordinator is invoked.
    4. The process completes without runtime exceptions (like UndefinedColumnError).
    """

    # 1. Setup Data in Real DB
    conn = db
    # Insert a test artist
    await conn.execute("""
        INSERT INTO artist (mbid, name) 
        VALUES ('test-mbid-1', 'Test Artist')
        ON CONFLICT (mbid) DO NOTHING
    """)
    # Insert external links for that artist
    await conn.execute("""
        INSERT INTO external_link (entity_type, entity_id, type, url)
        VALUES 
            ('artist', 'test-mbid-1', 'spotify', 'https://open.spotify.com/artist/123'),
            ('artist', 'test-mbid-1', 'wikipedia', 'https://en.wikipedia.org/wiki/Test_Artist')
        ON CONFLICT DO NOTHING
    """)

    # 2. Initialize ScanManager
    manager = ScanManager()
    
    # Mock the heavy API calls in Coordinator to keep test fast, 
    # but let the ScanManager <-> DB interaction run for real.
    # We want to verify the SQL query works, not hit MusicBrainz.

    async def mock_update_metadata(self, artists):
        # Verify the data passed from Scan Manager -> Coordinator
        # This confirms the SQL query correctly populated the artist dict
        assert len(artists) > 0
        artist = next(a for a in artists if a['mbid'] == 'test-mbid-1')
        
        # KEY ASSERTION: Verify external links were flattened correctly
        # This proves the join and json_object_agg logic works
        assert artist['spotify_url'] == 'https://open.spotify.com/artist/123'
        assert artist['wiki_url'] == 'https://en.wikipedia.org/wiki/Test_Artist'
        
        # Return dummy stats
        return {'updated': 1, 'errors': 0}

    # Patch the coordinator's actual API work method
    monkeypatch.setattr(MetadataCoordinator, "update_metadata", mock_update_metadata)
    
    # 3. Trigger the Scan
    # The method returns a task that we MUST await to ensure it finishes
    # before the test tears down the DB connection.
    task = await manager.start_metadata_update()
    await task

    # If we get here without an exception, the SQL query worked!
    assert manager._status != "Error"
