import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.scanner.services.coordinator import MetadataCoordinator

# Mock Services
@pytest.fixture
def mock_mb():
    with patch("app.scanner.services.coordinator.musicbrainz") as m:
        m.fetch_core = AsyncMock(return_value={"name": "Artist", "mbid": "123"})
        m.fetch_release_groups = AsyncMock(return_value=[])
        yield m

@pytest.fixture
def mock_lfm():
    with patch("app.scanner.services.coordinator.lastfm") as m:
        m.fetch_top_tracks = AsyncMock(return_value=[])
        m.fetch_artist_url = AsyncMock(return_value="http://lastfm")
        yield m

@pytest.fixture
def mock_art():
    with patch("app.scanner.services.coordinator.artwork") as m:
        m.fetch_fanart_artist_images = AsyncMock(return_value={"image_url": "http://img"})
        m.resolve_spotify_id = AsyncMock(return_value=(None, None))
        yield m

@pytest.fixture
def mock_db():
    # Mock db as a connection directly (not a pool)
    db = AsyncMock()
    
    # Configure transaction()
    tx_ctx = AsyncMock()
    tx_ctx.__aenter__.return_value = None
    tx_ctx.__aexit__.return_value = None
    db.transaction = MagicMock(return_value=tx_ctx)
    
    # Mock execute, fetch, etc.
    db.execute = AsyncMock()
    db.fetch = AsyncMock(return_value=[])
    db.fetchval = AsyncMock(return_value=None)
    db.fetchrow = AsyncMock(return_value=None)
    
    return db

@pytest.mark.asyncio
async def test_coordinator_process_artist_basic(mock_db, mock_mb, mock_lfm, mock_art):
    coord = MetadataCoordinator()
    
    artist = {"mbid": "123", "name": "Test", "spotify_url": "https://open.spotify.com/artist/sp123"}
    options = {
        "fetch_metadata": True,
        "fetch_artwork": True,
        "fetch_bio": False
    }
    
    with patch("app.scanner.services.coordinator.get_client") as mock_client:
        mock_client.return_value.__aenter__.return_value = AsyncMock()
        
        # Don't try to mock download_and_save_artwork here unless we verified it works.
        # It's imported in the module.
        with patch("app.scanner.services.coordinator.download_and_save_artwork", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = {"sha1": "abc", "meta": {}}
            
            payload = await coord.process_artist(artist, options, set(), fetch_only=True)
            assert payload is not None

            # Verify calls
            mock_mb.fetch_core.assert_called()
            mock_art.fetch_fanart_artist_images.assert_called()

            updates, art_res = payload
            await coord.save_artist_metadata(mock_db, artist["mbid"], updates, art_res)
            assert mock_db.execute.called or any("UPDATE artist" in str(c) for c in mock_db.execute.mock_calls)

@pytest.mark.asyncio
async def test_coordinator_missing_only_skip(mock_db, mock_mb, mock_art):
    coord = MetadataCoordinator(mock_db)
    
    # Artist has bio and image
    artist = {"mbid": "123", "name": "Test", "bio": "Some Bio", "image_url": "http://existing"}
    
    options = {
        "missing_only": True,
        "fetch_bio": True,
        "fetch_artwork": True
    }
    
    with patch("app.scanner.services.coordinator.get_client") as mock_client:
        mock_client.return_value.__aenter__.return_value = AsyncMock()
        
        task = coord.process_artist(artist, options, set())
        await task
        
        # Should NOT fetch bio (implied by coordinator logic if we implemented strict check)
        # However, verifying calls:
        
        # In my logic, I added:
        # if fetch_bio and artist.get("bio"): fetch_bio = False
        
        # So we expect NO bio fetch call if services logic respects the flag passed to it.
        # Wait, process_artist calls services based on LOCALLY computed 'fetch_bio' var.
        # But 'process_artist' logic I wrote (step 98/104/etc) calls specific services.
        # E.g.
        # if fetch_bio or fetch_base_metadata:
        #     mb_task = ...
        #     if fetch_bio:
        #          wiki_task = ...
        
        # Wait, if `fetch_bio` set to False by missing_only logic, then wiki task skipped?
        # Yes.
        
        # We need to verify that Wikipedia service was NOT called.
        with patch("app.scanner.services.coordinator.wikipedia") as mock_wiki:
             # process_artist calls wikipedia.fetch_bio logic?
             # Actually `musicbrainz.fetch_core` returns bio too?
             # No, `wikipedia.fetch_bio` is separate.
             
             await coord.process_artist(artist, options, set())
             mock_wiki.fetch_bio.assert_not_called()
             
             # Also artwork:
             mock_art.fetch_fanart_artist_images.assert_not_called()

@pytest.mark.asyncio
async def test_coordinator_db_save(mock_db, mock_mb, mock_art):
    with patch("app.scanner.services.coordinator.get_pool") as mock_pool:
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def acquire():
            yield mock_db
        pool = MagicMock()
        pool.acquire = acquire
        mock_pool.return_value = pool

        coord = MetadataCoordinator()
    
        artists = [{"mbid": "123", "name": "A"}]
        options = {"fetch_metadata": True}
        
        with patch("app.scanner.services.coordinator.get_client"):
            with patch("app.scanner.services.coordinator.download_and_save_artwork", new_callable=AsyncMock) as mock_dl:
                 mock_dl.return_value = None
                 await coord.update_metadata(artists, options)
    
        # DB calls - now db is used directly
        assert any("UPDATE artist" in str(call) for call in mock_db.execute.mock_calls)


@pytest.mark.asyncio
async def test_coordinator_skips_mb_core_when_only_toptracks_similar_singles(mock_db):
    # Only top tracks / similar / singles selected, with links already present -> no MB core fetch needed
    artist = {
        "mbid": "123",
        "name": "Test",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Test",
        "spotify_url": "https://open.spotify.com/artist/abc",
    }
    options = {
        "fetch_metadata": False,
        "fetch_links": False,
        "fetch_bio": False,
        "fetch_artwork": False,
        "fetch_spotify_artwork": False,
        "refresh_top_tracks": True,
        "refresh_singles": True,
        "refresh_similar_artists": True,
        "missing_only": False,
    }

    with patch("app.scanner.services.coordinator.musicbrainz.fetch_core", new_callable=AsyncMock) as mock_core, \
         patch("app.scanner.services.coordinator.musicbrainz.fetch_release_groups", new_callable=AsyncMock, return_value=[]) as mock_rg, \
         patch("app.scanner.services.coordinator.lastfm.fetch_top_tracks", new_callable=AsyncMock, return_value=[]) as mock_top, \
         patch("app.scanner.services.coordinator.lastfm.fetch_similar_artists", new_callable=AsyncMock, return_value=[]) as mock_sim, \
         patch("app.scanner.services.coordinator.lastfm.fetch_artist_url", new_callable=AsyncMock, return_value=None) as mock_url, \
         patch("app.scanner.services.coordinator.artwork.fetch_fanart_artist_images", new_callable=AsyncMock, return_value={}) as mock_fanart, \
         patch("app.scanner.services.coordinator.get_client") as mock_client:
        mock_client.return_value.__aenter__.return_value = AsyncMock()

        coord = MetadataCoordinator(mock_db)
        res = await coord.process_artist(artist, options, set())
        assert res is True

        mock_core.assert_not_awaited()
        mock_url.assert_not_awaited()
        mock_fanart.assert_not_awaited()
        mock_top.assert_awaited()
        mock_sim.assert_awaited()
        mock_rg.assert_awaited()


@pytest.mark.asyncio
async def test_missing_only_skips_toptracks_when_present(mock_db):
    artist = {
        "mbid": "123",
        "name": "Test",
        "has_top_tracks": True,
    }
    options = {
        "missing_only": True,
        "refresh_top_tracks": True,
    }

    with patch("app.scanner.services.coordinator.musicbrainz.fetch_core", new_callable=AsyncMock) as mock_core, \
         patch("app.scanner.services.coordinator.lastfm.fetch_top_tracks", new_callable=AsyncMock, return_value=[]) as mock_top, \
         patch("app.scanner.services.coordinator.get_client") as mock_client:
        mock_client.return_value.__aenter__.return_value = AsyncMock()

        coord = MetadataCoordinator()
        res = await coord.process_artist(artist, options, set(), fetch_only=True)
        # Should skip top tracks when already present
        assert mock_top.await_count == 0
        assert mock_core.await_count == 0

        # If skipped, process_artist returns True (no payload)
        assert res is True


@pytest.mark.asyncio
async def test_spotify_fallback_only_when_fanart_empty(mock_db):
    artist = {"mbid": "123", "name": "Test", "spotify_url": "https://open.spotify.com/artist/sp123"}
    options = {"fetch_artwork": False, "fetch_spotify_artwork": True}

    with patch("app.scanner.services.coordinator.get_client") as mock_client, \
         patch("app.scanner.services.coordinator.artwork.fetch_fanart_artist_images", new_callable=AsyncMock, return_value={"image_url": "http://fanart"}), \
         patch("app.scanner.services.coordinator.artwork.fetch_spotify_artist_images", new_callable=AsyncMock, return_value="http://spotify") as mock_spotify:
        mock_client.return_value.__aenter__.return_value = AsyncMock()

        coord = MetadataCoordinator()
        payload = await coord.process_artist(artist, options, set(), fetch_only=True)
        updates, _ = payload
        assert updates.get("image_url") == "http://fanart"
        mock_spotify.assert_not_awaited()

    with patch("app.scanner.services.coordinator.get_client") as mock_client, \
         patch("app.scanner.services.coordinator.artwork.fetch_fanart_artist_images", new_callable=AsyncMock, return_value={}), \
         patch("app.scanner.services.coordinator.artwork.fetch_spotify_artist_images", new_callable=AsyncMock, return_value="http://spotify") as mock_spotify:
        mock_client.return_value.__aenter__.return_value = AsyncMock()

        coord = MetadataCoordinator()
        payload = await coord.process_artist(artist, options, set(), fetch_only=True)
        updates, _ = payload
        assert updates.get("image_url") == "http://spotify"
        mock_spotify.assert_awaited()


@pytest.mark.asyncio
async def test_fanart_background_saved_and_mapped(mock_db):
    artist = {"mbid": "123", "name": "Test"}
    options = {"fetch_artwork": True}

    with patch("app.scanner.services.coordinator.get_client") as mock_client, \
         patch("app.scanner.services.coordinator.artwork.fetch_fanart_artist_images", new_callable=AsyncMock, return_value={"thumb": "http://thumb", "background": "http://bg"}), \
         patch("app.scanner.services.coordinator.download_and_save_artwork", new_callable=AsyncMock, side_effect=[{"sha1": "thumbsha", "meta": {}}, {"sha1": "bgsha", "meta": {}}]), \
         patch("app.scanner.services.coordinator.upsert_artwork_record", new_callable=AsyncMock, side_effect=[11, 22]) as mock_upsert_art, \
         patch("app.scanner.services.coordinator.upsert_image_mapping", new_callable=AsyncMock) as mock_map:
        mock_client.return_value.__aenter__.return_value = AsyncMock()

        coord = MetadataCoordinator()
        updates, art_res = await coord.process_artist(artist, options, set(), fetch_only=True)

        # Thumb and background should be captured
        assert updates.get("image_url") == "http://thumb"
        assert updates.get("background_url") == "http://bg"
        assert art_res["thumb"]["sha1"] == "thumbsha"
        assert art_res["background"]["sha1"] == "bgsha"

        await coord.save_artist_metadata(mock_db, artist["mbid"], updates, art_res)

        # Thumb mapping
        mock_upsert_art.assert_any_await(mock_db, "thumbsha", meta={}, source="fanart", source_url="http://thumb")
        mock_map.assert_any_await(mock_db, 11, "artist", artist["mbid"], "artistthumb")

        # Background mapping
        mock_upsert_art.assert_any_await(mock_db, "bgsha", meta={}, source="fanart", source_url="http://bg")
        mock_map.assert_any_await(mock_db, 22, "artist", artist["mbid"], "artistbackground")
