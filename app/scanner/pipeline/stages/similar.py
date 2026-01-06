"""
Similar Artists Stage - Fetch similar artists from Last.fm.
"""

from typing import List
from app.scanner.pipeline.base import EnrichmentStage
from app.scanner.pipeline.models import EnrichmentContext, StageResult
from app.scanner.services import lastfm
import logging

logger = logging.getLogger(__name__)


class SimilarArtistsStage(EnrichmentStage):
    """
    Fetch similar artists from Last.fm.
    
    Uses MBID-based lookup for accuracy.
    """
    
    @property
    def name(self) -> str:
        return "similar_artists"
    
    def dependencies(self) -> List[str]:
        # No dependencies - uses artist MBID directly
        return []
    
    def should_skip(self, context: EnrichmentContext) -> tuple[bool, str]:
        """Skip if missing_only and we already have similar artists."""
        if context.options.missing_only and context.artist.has_similar:
            return True, "Artist already has similar artists"
        
        return False, ""
    
    async def execute(self, context: EnrichmentContext) -> StageResult:
        """Fetch similar artists from Last.fm."""
        mbid = context.artist.mbid
        name = context.artist.name or mbid
        
        # Fetch from Last.fm
        similar = await lastfm.fetch_similar_artists(mbid, name, context.client)
        
        if not similar:
            return StageResult(
                stage_name=self.name,
                success=False,
                metrics={"api_calls": 1, "searched": 1, "found": False}
            )
        
        return StageResult.success(
            stage_name=self.name,
            data={"similar_artists": similar},
            metrics={
                "api_calls": 1,
                "searched": 1,
                "found": True,
                "artists_found": len(similar),
            }
        )
