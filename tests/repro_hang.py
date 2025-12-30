
import pytest
import asyncio
import logging
import sys
from unittest.mock import MagicMock, AsyncMock

from app.scanner.services.coordinator import MetadataCoordinator

# Configure Logging to show debug output in test runner
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')


# Mock DB Pool
class MockPool:
    def acquire(self):
        return MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())

# Mock HTTP Client handling Service logic
class MockClient:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def get(self, url, *args, **kwargs):
        # Simulate network delay to allow concurrency to happen
        await asyncio.sleep(0.01)
        resp = MagicMock()
        resp.status_code = 200
        
        # ROUTER: Return different JSON based on URL to support Real Services
        
        # 1. MusicBrainz Artist Core
        if "musicbrainz.org/ws/2/artist/" in url:
             if "king-id" in url: # We Are KING
                 resp.json.return_value = {
                     "name": "We Are KING",
                     "sort-name": "We Are KING",
                     "relations": [], # No Wikidata
                     "genres": []
                 }
             else:
                 resp.json.return_value = {
                     "name": "Artist X",
                     "sort-name": "Artist X",
                     "relations": [
                        {"type": "wikidata", "url": {"resource": "http://wd/123"}}
                     ],
                     "genres": []
                 }
        # 2. Fanart
        elif "webservice.fanart.tv" in url:
             resp.json.return_value = {}
        # 3. Last.fm
        elif "last.fm" in url or "audioscrobbler" in url:
             resp.json.return_value = {}
        # 4. Wikidata Entity
        elif "wikidata.org/wiki/Special:EntityData" in url:
             resp.json.return_value = {"entities": {"123": {"claims": {}}}}
        # 5. Wikipedia
        elif "wikipedia.org/api" in url:
             resp.json.return_value = {"extract": "Bio content"}
        # 6. Spotify Auth
        elif "spotify.com" in url:
             resp.json.return_value = {}
             
        else:
             resp.json.return_value = {}

        return resp

    async def post(self, url, *args, **kwargs):
        # Spotify Auth
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"access_token": "fake", "expires_in": 3600}
        return resp

@pytest.fixture
def mock_pool(monkeypatch):
    pool = MockPool()
    monkeypatch.setattr("app.scanner.services.coordinator.get_pool", lambda: pool)
    return pool

@pytest.fixture
def mock_get_client(monkeypatch):
    client = MockClient()
    # IMPORTANT: Mock get_client in utils to return our MockClient
    # This ensures musicbrainz.py, etc. use it.
    def _get_client(c=None):
        return client
    monkeypatch.setattr("app.scanner.services.utils.get_client", _get_client)
    # Also patch httpx.AsyncClient constructor just in case
    monkeypatch.setattr("httpx.AsyncClient", lambda **k: client)
    return client

@pytest.fixture
def real_rate_limiter(monkeypatch):
    # Ensure MusicBrainz and others use a fast rate limiter for test
    # but still use the REAL RateLimiter class logic.
    # We patch the rate limit config getter to return a safe value (e.g. 100 req/s)
    monkeypatch.setattr("app.config.get_musicbrainz_rate_limit", lambda: 100.0)
    # Re-init the mb_limiter in musicbrainz module?
    # It's a global var instantiated at import time. 
    # We might need to replace the global instance with a fresh one using new limit.
    from app.scanner.services.utils import RateLimiter
    new_limiter = RateLimiter(rate_limit=100.0, burst_limit=5)
    monkeypatch.setattr("app.scanner.services.musicbrainz.mb_limiter", new_limiter)

@pytest.mark.asyncio
async def test_empty_artist_list_no_hang(mock_pool, mock_get_client, real_rate_limiter):
    """
    Test the EXACT scenario from user's screenshot:
    - All artists are skipped (empty list passed to coordinator)
    - Verify it doesn't hang on queue.join()
    """
    
    coord = MetadataCoordinator()
    
    # EMPTY artist list (simulating all skipped due to missing_only)
    artists = []
        
    options = {
        "fetch_base_metadata": True,
        "fetch_artwork": False, 
        "fetch_links": True,
        "fetch_top_tracks": False,
        "fetch_similar_artists": False,
        "fetch_singles": False,
        "fetch_bio": True
    }
    
    print("Testing EMPTY artist list (all skipped)...")
    try:
        # Should complete instantly since no artists to process
        await asyncio.wait_for(coord.update_metadata(artists, options), timeout=2.0)
        print("Update finished successfully with empty list.")
    except asyncio.TimeoutError:
        pytest.fail("Coordinator hung on empty artist list! queue.join() deadlock detected.")
    except Exception as e:
        pytest.fail(f"Coordinator crashed: {e}")

@pytest.mark.asyncio
async def test_batch_processing_real_services(mock_pool, mock_get_client, real_rate_limiter):
    """
    Test using REAL service modules (musicbrainz, artwork, etc.)
    but mocked network.
    This exercises RateLimiter, Coordinator logic, and UnboundLocalError path.
    """
    
    coord = MetadataCoordinator()
    
    artists = []
    # Index 0: We Are KING (Trigger UnboundLocalError path via MockClient response)
    artists.append({"mbid": "king-id", "name": "We Are KING"})
    
    # 12 Normal artists
    for i in range(12):
        artists.append({"mbid": f"id-{i}", "name": f"Artist {i}"})
        
    options = {
        "fetch_base_metadata": True, # Must be True to trigger MusicBrainz call
        "fetch_artwork": False, 
        "fetch_links": True,
        "fetch_top_tracks": False,
        "fetch_similar_artists": False,
        "fetch_singles": False,
        "fetch_bio": True
    }
    
    print("Starting REAL SERVICES update simulation...")
    try:
        # 20 seconds timeout for 13 items mocked should be plenty.
        await asyncio.wait_for(coord.update_metadata(artists, options), timeout=20.0)
        print("Update finished successfully.")
    except asyncio.TimeoutError:
        pytest.fail("Coordinator timed out! Real logic hang detected.")
    except Exception as e:
        pytest.fail(f"Coordinator crashed: {e}")
