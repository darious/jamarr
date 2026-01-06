"""
Enrichment Planner - Determines which stages to execute.

This centralizes all the "missing only" logic that was previously
scattered throughout the coordinator. The planner analyzes the artist
state and scan options to generate an execution plan.
"""

from app.scanner.pipeline.models import ArtistState, ScanOptions, EnrichmentPlan
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
import logging

logger = logging.getLogger(__name__)


class EnrichmentPlanner:
    """
    Determines which enrichment stages to execute.
    
    This is a pure function that takes artist state and options,
    and returns a plan containing the stages to run.
    """
    
    def create_plan(
        self,
        artist: ArtistState,
        options: ScanOptions,
        local_release_groups: set = None
    ) -> EnrichmentPlan:
        """
        Create an enrichment plan for an artist.
        
        Args:
            artist: Current state of the artist from database
            options: User-provided scan options
            local_release_groups: Set of release group MBIDs for this artist
        
        Returns:
            EnrichmentPlan with stages to execute
        """
        plan = EnrichmentPlan()
        local_release_groups = local_release_groups or set()
        
        # Core metadata and links
        if options.effective_fetch_metadata or options.fetch_links:
            plan.add_stage(CoreMetadataStage())
            plan.add_stage(ExternalLinksStage())
        
        # Artwork
        if options.fetch_artwork or options.fetch_spotify_artwork:
            plan.add_stage(ArtworkStage())
        
        # Biography
        if options.fetch_bio:
            plan.add_stage(WikipediaBioStage())
        
        # Top tracks
        if options.effective_fetch_top_tracks:
            plan.add_stage(TopTracksStage())
        
        # Similar artists
        if options.effective_fetch_similar:
            plan.add_stage(SimilarArtistsStage())
        
        # Singles
        if options.effective_fetch_singles:
            plan.add_stage(SinglesStage())
        
        # Album metadata
        if options.fetch_album_metadata and local_release_groups:
            plan.add_stage(AlbumMetadataStage())
        
        logger.info(
            f"Created plan for {artist.name or artist.mbid}: "
            f"{plan.stage_count} stages, missing_only={options.missing_only}"
        )
        
        return plan
