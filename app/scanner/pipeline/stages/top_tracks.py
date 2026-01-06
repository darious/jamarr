"""
Top Tracks Stage - Fetch top tracks from Last.fm.
"""

from typing import List
from app.scanner.pipeline.base import EnrichmentStage
from app.scanner.pipeline.models import EnrichmentContext, StageResult
from app.scanner.services import lastfm
from app.scanner.stats import get_api_tracker
import logging

logger = logging.getLogger(__name__)


class TopTracksStage(EnrichmentStage):
    """
    Fetch artist's top tracks from Last.fm.
    
    Uses MBID-based lookup for accuracy.
    """
    
    @property
    def name(self) -> str:
        return "top_tracks"
    
    def dependencies(self) -> List[str]:
        # No dependencies - uses artist MBID directly
        return []
    
    def should_skip(self, context: EnrichmentContext) -> tuple[bool, str]:
        """Skip if missing_only and we already have top tracks."""
        if context.options.missing_only and context.artist.has_top_tracks:
            return True, "Artist already has top tracks"
        
        return False, ""
    
    async def execute(self, context: EnrichmentContext) -> StageResult:
        """Fetch top tracks from Last.fm."""
        mbid = context.artist.mbid
        name = context.artist.name or mbid
        
        # Fetch from Last.fm
        tracks = await lastfm.fetch_top_tracks(mbid, name, context.client)
        
        if not tracks:
            get_api_tracker().track_detailed("Top Tracks", "missing")
            return StageResult(
                stage_name=self.name,
                success=False,
                metrics={"api_calls": 1}
            )
        
        get_api_tracker().track_detailed("Top Tracks", "found")
        
        return StageResult.success(
            stage_name=self.name,
            data={"top_tracks": tracks},
            metrics={
                "api_calls": 1,
                "tracks_found": len(tracks),
            }
        )
