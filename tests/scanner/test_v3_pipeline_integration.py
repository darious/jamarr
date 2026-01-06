"""
Integration tests for the complete pipeline flow.

These tests validate the entire enrichment process from start to finish,
using mocked HTTP responses to simulate real API calls.

Test naming convention: test_v3_integration_* for integration tests.
"""

import pytest
from app.scanner.pipeline import (
    ArtistState,
    ScanOptions,
    EnrichmentContext,
    EnrichmentPlanner,
    PipelineExecutor,
)
from unittest.mock import Mock, AsyncMock, patch
import httpx


@pytest.fixture
def mock_http_client():
    """Create a mock HTTP client with common responses."""
    client = Mock(spec=httpx.AsyncClient)
    return client


class TestPipelineIntegration:
    """Integration tests for complete pipeline flow."""
    
    @pytest.mark.asyncio
    async def test_v3_integration_full_enrichment(self, mock_http_client):
        """Test complete enrichment flow with all stages."""
        
        # Artist with no metadata
        artist = ArtistState(
            mbid="test-123",
            name="Test Artist"
        )
        
        # Enable all enrichment options
        options = ScanOptions(
            fetch_metadata=True,
            fetch_artwork=True,
            fetch_bio=True,
            fetch_top_tracks=True,
            fetch_similar_artists=True,
            fetch_singles=True,
        )
        
        # Mock API responses
        with patch("app.scanner.services.musicbrainz.fetch_core") as mock_mb_core, \
             patch("app.scanner.services.wikidata.fetch_external_links") as mock_wikidata, \
             patch("app.scanner.services.artwork.fetch_fanart_artist_images") as mock_fanart, \
             patch("app.scanner.services.wikipedia.fetch_bio") as mock_wiki_bio, \
             patch("app.scanner.services.lastfm.fetch_top_tracks") as mock_top_tracks, \
             patch("app.scanner.services.lastfm.fetch_similar_artists") as mock_similar, \
             patch("app.scanner.services.musicbrainz.fetch_release_groups") as mock_singles:
            
            # Setup mock returns
            mock_mb_core.return_value = {
                "name": "Test Artist",
                "sort_name": "Artist, Test",
                "wikidata_url": "http://wikidata.org/Q123",
                "wikipedia_url": "http://en.wikipedia.org/wiki/Test_Artist",
                "genres": [{"name": "rock", "count": 10}],
            }
            
            mock_wikidata.return_value = {
                "spotify_url": "http://spotify.com/artist/123",
                "qobuz_url": "http://qobuz.com/artist/123",
            }
            
            mock_fanart.return_value = {
                "image_url": "http://fanart.tv/thumb.jpg",
                "background": "http://fanart.tv/bg.jpg",
            }
            
            mock_wiki_bio.return_value = "Test Artist is a musician..."
            
            mock_top_tracks.return_value = [
                {"name": "Hit Song", "rank": 1, "mbid": "track-1"},
                {"name": "Another Hit", "rank": 2, "mbid": "track-2"},
            ]
            
            mock_similar.return_value = [
                {"name": "Similar Artist 1", "mbid": "artist-1"},
                {"name": "Similar Artist 2", "mbid": "artist-2"},
            ]
            
            mock_singles.return_value = [
                {"title": "Single 1", "mbid": "single-1", "date": "2020"},
            ]
            
            # Create context
            context = EnrichmentContext(artist, options, mock_http_client)
            
            # Create and execute plan
            planner = EnrichmentPlanner()
            plan = planner.create_plan(artist, options)
            
            executor = PipelineExecutor()
            result = await executor.execute(plan, context)
            
            # Verify execution
            assert result.success_count >= 6  # At least 6 stages should succeed
            assert result.error_count == 0
            
            # Verify data was collected
            merged = result.merge_data()
            assert merged["name"] == "Test Artist"
            assert merged["wikidata_url"] == "http://wikidata.org/Q123"
            assert merged["spotify_url"] == "http://spotify.com/artist/123"
            assert merged["image_url"] == "http://fanart.tv/thumb.jpg"
            assert merged["bio"] == "Test Artist is a musician..."
            assert len(merged["top_tracks"]) == 2
            assert len(merged["similar_artists"]) == 2
            assert len(merged["singles"]) == 1
    
    @pytest.mark.asyncio
    async def test_v3_integration_missing_only_skips(self, mock_http_client):
        """Test missing_only flag skips stages with existing data."""
        
        # Artist with existing metadata
        artist = ArtistState(
            mbid="test-123",
            name="Test Artist",
            bio="Existing bio",
            image_url="http://existing.jpg",
            image_source="fanart",
            has_top_tracks=True,
            external_links={
                "spotify": "http://spotify.com",
                "wikipedia": "http://wikipedia.org",
                "homepage": "http://example.com",
                "qobuz": "http://qobuz.com",
                "tidal": "http://tidal.com",
                "lastfm": "http://lastfm.com",
                "discogs": "http://discogs.com",
            }
        )
        
        # Enable all options with missing_only
        options = ScanOptions(
            fetch_metadata=True,
            fetch_artwork=True,
            fetch_bio=True,
            fetch_top_tracks=True,
            missing_only=True,
        )
        
        # Create context
        context = EnrichmentContext(artist, options, mock_http_client)
        
        # Create and execute plan
        planner = EnrichmentPlanner()
        plan = planner.create_plan(artist, options)
        
        executor = PipelineExecutor()
        result = await executor.execute(plan, context)
        
        # Most stages should be skipped
        assert result.skip_count >= 3  # Bio, artwork, top tracks, core metadata
        assert result.success_count <= 2  # Maybe external_links runs
    
    @pytest.mark.asyncio
    async def test_v3_integration_error_handling(self, mock_http_client):
        """Test pipeline handles API errors gracefully."""
        
        artist = ArtistState(mbid="test-123", name="Test Artist")
        options = ScanOptions(fetch_metadata=True, fetch_bio=True)
        
        # Mock API to fail
        with patch("app.scanner.services.musicbrainz.fetch_core") as mock_mb, \
             patch("app.scanner.services.wikipedia.fetch_bio") as mock_bio:
            
            # Core metadata succeeds
            mock_mb.return_value = {
                "name": "Test Artist",
                "wikipedia_url": "http://wikipedia.org/wiki/Test",
            }
            
            # Bio fails
            mock_bio.return_value = None
            
            context = EnrichmentContext(artist, options, mock_http_client)
            
            planner = EnrichmentPlanner()
            plan = planner.create_plan(artist, options)
            
            executor = PipelineExecutor()
            result = await executor.execute(plan, context)
            
            # Should have some successes and some failures
            assert result.success_count >= 1  # Core metadata
            # Bio stage returns success=False when no data found
            
            # Merged data should still have what succeeded
            merged = result.merge_data()
            assert "name" in merged
    
    @pytest.mark.asyncio
    async def test_v3_integration_dependency_chain(self, mock_http_client):
        """Test stages execute in correct dependency order."""
        
        artist = ArtistState(mbid="test-123")
        options = ScanOptions(fetch_metadata=True, fetch_bio=True)
        
        execution_order = []
        
        # Track execution order
        async def track_mb_core(*args, **kwargs):
            execution_order.append("core_metadata")
            return {"name": "Test", "wikidata_url": "http://wikidata.org/Q1"}
        
        async def track_wikidata(*args, **kwargs):
            execution_order.append("external_links")
            return {"wikipedia_url": "http://wikipedia.org/wiki/Test"}
        
        async def track_bio(*args, **kwargs):
            execution_order.append("wikipedia_bio")
            return "Bio text"
        
        with patch("app.scanner.services.musicbrainz.fetch_core", side_effect=track_mb_core), \
             patch("app.scanner.services.wikidata.fetch_external_links", side_effect=track_wikidata), \
             patch("app.scanner.services.wikipedia.fetch_bio", side_effect=track_bio):
            
            context = EnrichmentContext(artist, options, mock_http_client)
            
            planner = EnrichmentPlanner()
            plan = planner.create_plan(artist, options)
            
            executor = PipelineExecutor()
            await executor.execute(plan, context)
            
            # Verify order: core_metadata before external_links before bio
            assert execution_order.index("core_metadata") < execution_order.index("external_links")
            assert execution_order.index("external_links") < execution_order.index("wikipedia_bio")
    
    @pytest.mark.asyncio
    async def test_v3_integration_parallel_execution(self, mock_http_client):
        """Test independent stages execute in parallel."""
        
        artist = ArtistState(mbid="test-123", name="Test")
        options = ScanOptions(
            fetch_top_tracks=True,
            fetch_similar_artists=True,
            fetch_singles=True,
        )
        
        import time
        import asyncio
        
        # Mock with delays to test parallelism
        async def slow_top_tracks(*args, **kwargs):
            await asyncio.sleep(0.1)
            return [{"name": "Track 1"}]
        
        async def slow_similar(*args, **kwargs):
            await asyncio.sleep(0.1)
            return [{"name": "Artist 1"}]
        
        async def slow_singles(*args, **kwargs):
            await asyncio.sleep(0.1)
            return [{"title": "Single 1"}]
        
        with patch("app.scanner.services.lastfm.fetch_top_tracks", side_effect=slow_top_tracks), \
             patch("app.scanner.services.lastfm.fetch_similar_artists", side_effect=slow_similar), \
             patch("app.scanner.services.musicbrainz.fetch_release_groups", side_effect=slow_singles):
            
            context = EnrichmentContext(artist, options, mock_http_client)
            
            planner = EnrichmentPlanner()
            plan = planner.create_plan(artist, options)
            
            executor = PipelineExecutor()
            
            start = time.time()
            await executor.execute(plan, context)
            elapsed = time.time() - start
            
            # Should take ~0.1s (parallel) not ~0.3s (sequential)
            assert elapsed < 0.25, f"Took {elapsed}s, expected < 0.25s (parallel execution)"
