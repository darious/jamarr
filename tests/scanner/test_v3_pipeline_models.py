"""
Tests for pipeline data models.

Test naming convention: test_v3_pipeline_* for new pipeline tests.
"""

import pytest
from app.scanner.pipeline.models import (
    ArtistState,
    ScanOptions,
    StageResult,
    EnrichmentContext,
    EnrichmentPlan,
    PipelineResult,
)
from app.scanner.pipeline.base import EnrichmentStage
from unittest.mock import Mock
import httpx


class TestArtistState:
    """Test ArtistState model."""
    
    def test_v3_pipeline_artist_state_creation(self):
        """Test creating an ArtistState."""
        artist = ArtistState(
            mbid="123-456",
            name="The Beatles",
            external_links={"spotify": "https://spotify.com/artist/123"}
        )
        
        assert artist.mbid == "123-456"
        assert artist.name == "The Beatles"
        assert artist.has_name
        assert artist.has_link("spotify")
        assert artist.get_link("spotify") == "https://spotify.com/artist/123"
    
    def test_v3_pipeline_artist_state_immutable(self):
        """Test that ArtistState is immutable."""
        artist = ArtistState(mbid="123", name="Test")
        
        with pytest.raises(Exception):  # FrozenInstanceError
            artist.name = "Changed"
    
    def test_v3_pipeline_artist_state_properties(self):
        """Test ArtistState computed properties."""
        # No data
        artist = ArtistState(mbid="123")
        assert not artist.has_name
        assert not artist.has_bio
        assert not artist.has_artwork
        assert not artist.needs_artwork_upgrade
        
        # With data
        artist = ArtistState(
            mbid="123",
            name="Beatles",
            bio="British rock band",
            image_url="http://example.com/img.jpg",
            image_source="fanart"
        )
        assert artist.has_name
        assert artist.has_bio
        assert artist.has_artwork
        assert not artist.needs_artwork_upgrade
        
        # Spotify artwork (needs upgrade)
        artist = ArtistState(
            mbid="123",
            image_url="http://spotify.com/img.jpg",
            image_source="spotify"
        )
        assert artist.has_artwork
        assert artist.needs_artwork_upgrade
    
    def test_v3_pipeline_artist_state_from_db_row(self):
        """Test creating ArtistState from database row."""
        row = {
            "mbid": "123",
            "name": "Beatles",
            "bio": "Rock band",
            "image_url": "http://img.jpg",
            "image_source": "fanart",
            "spotify_url": "http://spotify.com",
            "wikipedia_url": "http://wikipedia.org",
            "has_top_tracks": True,
            "has_singles": False,
        }
        
        artist = ArtistState.from_db_row(row)
        
        assert artist.mbid == "123"
        assert artist.name == "Beatles"
        assert artist.has_link("spotify")
        assert artist.has_link("wikipedia")
        assert artist.has_top_tracks
        assert not artist.has_singles


class TestScanOptions:
    """Test ScanOptions model."""
    
    def test_v3_pipeline_scan_options_defaults(self):
        """Test default options."""
        opts = ScanOptions()
        
        assert not opts.fetch_metadata
        assert not opts.fetch_artwork
        assert not opts.missing_only
    
    def test_v3_pipeline_scan_options_backwards_compat(self):
        """Test backwards compatibility properties."""
        # Old-style options
        opts = ScanOptions(
            fetch_base_metadata=True,
            refresh_top_tracks=True,
            refresh_similar_artists=True,
            refresh_singles=True,
        )
        
        assert opts.effective_fetch_metadata
        assert opts.effective_fetch_top_tracks
        assert opts.effective_fetch_similar
        assert opts.effective_fetch_singles
        
        # New-style options
        opts = ScanOptions(
            fetch_metadata=True,
            fetch_top_tracks=True,
            fetch_similar_artists=True,
            fetch_singles=True,
        )
        
        assert opts.effective_fetch_metadata
        assert opts.effective_fetch_top_tracks
        assert opts.effective_fetch_similar
        assert opts.effective_fetch_singles


class TestStageResult:
    """Test StageResult model."""
    
    def test_v3_pipeline_stage_result_success(self):
        """Test creating a success result."""
        result = StageResult.success(
            "test_stage",
            {"key": "value"},
            {"api_calls": 1}
        )
        
        assert result.stage_name == "test_stage"
        assert result.success
        assert result.data == {"key": "value"}
        assert result.metrics == {"api_calls": 1}
        assert not result.skipped
        assert not result.error
    
    def test_v3_pipeline_stage_result_skip(self):
        """Test creating a skip result."""
        result = StageResult.skip("test_stage", "No data needed")
        
        assert result.stage_name == "test_stage"
        assert not result.success
        assert result.skipped
        assert result.skip_reason == "No data needed"
    
    def test_v3_pipeline_stage_result_error(self):
        """Test creating an error result."""
        result = StageResult.from_error("test_stage", "API failed")
        
        assert result.stage_name == "test_stage"
        assert not result.success
        assert result.error == "API failed"


class TestEnrichmentContext:
    """Test EnrichmentContext model."""
    
    def test_v3_pipeline_context_creation(self):
        """Test creating an EnrichmentContext."""
        artist = ArtistState(mbid="123", name="Beatles")
        options = ScanOptions(fetch_metadata=True)
        client = Mock(spec=httpx.AsyncClient)
        
        ctx = EnrichmentContext(artist, options, client)
        
        assert ctx.artist == artist
        assert ctx.options == options
        assert ctx.client == client
    
    def test_v3_pipeline_context_results(self):
        """Test managing stage results in context."""
        ctx = EnrichmentContext(
            ArtistState(mbid="123"),
            ScanOptions(),
            Mock()
        )
        
        # No results initially
        assert not ctx.has_result("test_stage")
        assert ctx.get_result("test_stage") is None
        
        # Add result
        result = StageResult.success("test_stage", {"key": "value"})
        ctx.add_result(result)
        
        assert ctx.has_result("test_stage")
        assert ctx.get_result("test_stage") == result
        assert ctx.get_data("test_stage", "key") == "value"
        assert ctx.get_data("test_stage", "missing", "default") == "default"
    
    def test_v3_pipeline_context_with_results(self):
        """Test creating new context with results."""
        ctx1 = EnrichmentContext(
            ArtistState(mbid="123"),
            ScanOptions(),
            Mock()
        )
        
        results = {
            "stage1": StageResult.success("stage1", {"a": 1}),
            "stage2": StageResult.success("stage2", {"b": 2}),
        }
        
        ctx2 = ctx1.with_results(results)
        
        # Original context unchanged
        assert not ctx1.has_result("stage1")
        
        # New context has results
        assert ctx2.has_result("stage1")
        assert ctx2.has_result("stage2")


class TestEnrichmentPlan:
    """Test EnrichmentPlan model."""
    
    def test_v3_pipeline_plan_creation(self):
        """Test creating an enrichment plan."""
        plan = EnrichmentPlan()
        
        assert plan.stage_count == 0
        assert not plan.stages
    
    def test_v3_pipeline_plan_add_stages(self):
        """Test adding stages to plan."""
        plan = EnrichmentPlan()
        
        stage1 = Mock(spec=EnrichmentStage)
        stage2 = Mock(spec=EnrichmentStage)
        
        plan.add_stage(stage1)
        plan.add_stage(stage2)
        
        assert plan.stage_count == 2
        assert stage1 in plan.stages
        assert stage2 in plan.stages


class TestPipelineResult:
    """Test PipelineResult model."""
    
    def test_v3_pipeline_result_metrics(self):
        """Test pipeline result metrics."""
        result = PipelineResult(results={
            "stage1": StageResult.success("stage1", {"a": 1}, {"api_calls": 2}),
            "stage2": StageResult.skip("stage2", "skipped"),
            "stage3": StageResult.from_error("stage3", "failed"),
        })
        
        assert result.success_count == 1
        assert result.skip_count == 1
        assert result.error_count == 1
        assert result.total_api_calls == 2
    
    def test_v3_pipeline_result_merge_data(self):
        """Test merging data from all successful stages."""
        result = PipelineResult(results={
            "stage1": StageResult.success("stage1", {"name": "Beatles", "bio": "Band"}),
            "stage2": StageResult.success("stage2", {"image_url": "http://img.jpg"}),
            "stage3": StageResult.from_error("stage3", "failed"),
        })
        
        merged = result.merge_data()
        
        assert merged == {
            "name": "Beatles",
            "bio": "Band",
            "image_url": "http://img.jpg",
        }
