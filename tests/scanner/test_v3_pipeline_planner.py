"""
Tests for EnrichmentPlanner.

Test naming convention: test_v3_planner_* for new pipeline tests.
"""

from app.scanner.pipeline.planner import EnrichmentPlanner
from app.scanner.pipeline.models import ArtistState, ScanOptions
from app.scanner.pipeline.stages import (
    CoreMetadataStage,
    ExternalLinksStage,
    ArtworkStage,
    WikipediaBioStage,
    TopTracksStage,
    SimilarArtistsStage,
    SinglesStage,
    AlbumMetadataStage,
)


class TestEnrichmentPlanner:
    """Test EnrichmentPlanner."""
    
    def test_v3_planner_empty_options(self):
        """Test planner with no options returns empty plan."""
        planner = EnrichmentPlanner()
        artist = ArtistState(mbid="123", name="Beatles")
        options = ScanOptions()
        
        plan = planner.create_plan(artist, options)
        
        assert plan.stage_count == 0
    
    def test_v3_planner_fetch_metadata(self):
        """Test planner includes core metadata and links stages."""
        planner = EnrichmentPlanner()
        artist = ArtistState(mbid="123")
        options = ScanOptions(fetch_metadata=True)
        
        plan = planner.create_plan(artist, options)
        
        assert plan.stage_count == 2
        assert plan.has_stage(CoreMetadataStage)
        assert plan.has_stage(ExternalLinksStage)
    
    def test_v3_planner_fetch_artwork(self):
        """Test planner includes artwork stage."""
        planner = EnrichmentPlanner()
        artist = ArtistState(mbid="123")
        options = ScanOptions(fetch_artwork=True)
        
        plan = planner.create_plan(artist, options)
        
        assert plan.stage_count == 1
        assert plan.has_stage(ArtworkStage)
    
    def test_v3_planner_fetch_bio(self):
        """Test planner includes bio stage."""
        planner = EnrichmentPlanner()
        artist = ArtistState(mbid="123")
        options = ScanOptions(fetch_bio=True)
        
        plan = planner.create_plan(artist, options)
        
        assert plan.stage_count == 1
        assert plan.has_stage(WikipediaBioStage)
    
    def test_v3_planner_fetch_top_tracks(self):
        """Test planner includes top tracks stage."""
        planner = EnrichmentPlanner()
        artist = ArtistState(mbid="123")
        options = ScanOptions(fetch_top_tracks=True)
        
        plan = planner.create_plan(artist, options)
        
        assert plan.stage_count == 1
        assert plan.has_stage(TopTracksStage)
    
    def test_v3_planner_fetch_similar(self):
        """Test planner includes similar artists stage."""
        planner = EnrichmentPlanner()
        artist = ArtistState(mbid="123")
        options = ScanOptions(fetch_similar_artists=True)
        
        plan = planner.create_plan(artist, options)
        
        assert plan.stage_count == 1
        assert plan.has_stage(SimilarArtistsStage)
    
    def test_v3_planner_fetch_singles(self):
        """Test planner includes singles stage."""
        planner = EnrichmentPlanner()
        artist = ArtistState(mbid="123")
        options = ScanOptions(fetch_singles=True)
        
        plan = planner.create_plan(artist, options)
        
        assert plan.stage_count == 1
        assert plan.has_stage(SinglesStage)
    
    def test_v3_planner_fetch_albums_no_local(self):
        """Test planner skips albums stage when no local albums."""
        planner = EnrichmentPlanner()
        artist = ArtistState(mbid="123")
        options = ScanOptions(fetch_album_metadata=True)
        
        plan = planner.create_plan(artist, options, local_release_groups=set())
        
        assert plan.stage_count == 0
    
    def test_v3_planner_fetch_albums_with_local(self):
        """Test planner includes albums stage when local albums exist."""
        planner = EnrichmentPlanner()
        artist = ArtistState(mbid="123")
        options = ScanOptions(fetch_album_metadata=True)
        
        plan = planner.create_plan(
            artist,
            options,
            local_release_groups={"album-1", "album-2"}
        )
        
        assert plan.stage_count == 1
        assert plan.has_stage(AlbumMetadataStage)
    
    def test_v3_planner_all_options(self):
        """Test planner with all options enabled."""
        planner = EnrichmentPlanner()
        artist = ArtistState(mbid="123")
        options = ScanOptions(
            fetch_metadata=True,
            fetch_artwork=True,
            fetch_bio=True,
            fetch_top_tracks=True,
            fetch_similar_artists=True,
            fetch_singles=True,
            fetch_album_metadata=True,
        )
        
        plan = planner.create_plan(
            artist,
            options,
            local_release_groups={"album-1"}
        )
        
        # Should have all 8 stages
        assert plan.stage_count == 8
        assert plan.has_stage(CoreMetadataStage)
        assert plan.has_stage(ExternalLinksStage)
        assert plan.has_stage(ArtworkStage)
        assert plan.has_stage(WikipediaBioStage)
        assert plan.has_stage(TopTracksStage)
        assert plan.has_stage(SimilarArtistsStage)
        assert plan.has_stage(SinglesStage)
        assert plan.has_stage(AlbumMetadataStage)
    
    def test_v3_planner_backwards_compat_options(self):
        """Test planner handles backwards compatible option names."""
        planner = EnrichmentPlanner()
        artist = ArtistState(mbid="123")
        
        # Old-style option names
        options = ScanOptions(
            fetch_base_metadata=True,
            refresh_top_tracks=True,
            refresh_similar_artists=True,
            refresh_singles=True,
        )
        
        plan = planner.create_plan(artist, options)
        
        # Should include stages based on effective_* properties
        assert plan.has_stage(CoreMetadataStage)
        assert plan.has_stage(TopTracksStage)
        assert plan.has_stage(SimilarArtistsStage)
        assert plan.has_stage(SinglesStage)
