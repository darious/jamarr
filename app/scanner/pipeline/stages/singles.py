"""
Singles Stage - Fetch artist singles from MusicBrainz.
"""

from typing import List
from app.scanner.pipeline.base import EnrichmentStage
from app.scanner.pipeline.models import EnrichmentContext, StageResult
from app.scanner.services import musicbrainz
from app.scanner.stats import get_api_tracker
import logging

logger = logging.getLogger(__name__)


class SinglesStage(EnrichmentStage):
    """
    Fetch artist's singles from MusicBrainz.
    
    Singles are release groups of type 'single'.
    """
    
    @property
    def name(self) -> str:
        return "singles"
    
    def dependencies(self) -> List[str]:
        # No dependencies - uses artist MBID directly
        return []
    
    def should_skip(self, context: EnrichmentContext) -> tuple[bool, str]:
        """Skip if missing_only and we already have singles."""
        if context.options.missing_only and context.artist.has_singles:
            return True, "Artist already has singles"
        
        return False, ""
    
    async def execute(self, context: EnrichmentContext) -> StageResult:
        """Fetch singles from MusicBrainz."""
        mbid = context.artist.mbid
        name = context.artist.name or mbid
        
        # Fetch from MusicBrainz
        singles = await musicbrainz.fetch_release_groups(
            mbid,
            "single",
            context.client,
            artist_name=name
        )
        
        if not singles:
            get_api_tracker().track_detailed("Singles", "missing")
            return StageResult(
                stage_name=self.name,
                success=False,
                metrics={"api_calls": 1}
            )
        
        get_api_tracker().track_detailed("Singles", "found")
        
        return StageResult.success(
            stage_name=self.name,
            data={"singles": singles},
            metrics={
                "api_calls": 1,
                "singles_found": len(singles),
            }
        )
