"""
Core Metadata Stage - Fetch artist metadata from MusicBrainz.

This stage fetches:
- Artist name, sort name
- Genres/tags
- External link URLs (Spotify, Wikipedia, Wikidata, etc.)
"""

from typing import List
from app.scanner.pipeline.base import EnrichmentStage
from app.scanner.pipeline.models import EnrichmentContext, StageResult
from app.scanner.services import musicbrainz
import logging

logger = logging.getLogger(__name__)


class CoreMetadataStage(EnrichmentStage):
    """
    Fetch core artist metadata from MusicBrainz.
    
    This is typically the first stage in the pipeline as it provides
    foundational data (name, links) that other stages depend on.
    """
    
    @property
    def name(self) -> str:
        return "core_metadata"
    
    def dependencies(self) -> List[str]:
        # No dependencies - this is usually first
        return []
    
    def should_skip(self, context: EnrichmentContext) -> tuple[bool, str]:
        """Skip if missing_only is enabled and we have all core data."""
        if not context.options.missing_only:
            return False, ""
        
        artist = context.artist
        
        # Check if we have name
        has_core = artist.has_name
        
        # Check if we have all link types
        required_links = [
            "homepage", "spotify", "wikipedia", "qobuz",
            "tidal", "lastfm", "discogs"
        ]
        has_all_links = all(artist.has_link(link) for link in required_links)
        
        if has_core and has_all_links:
            return True, "Artist has core metadata and all links"
        
        return False, ""
    
    async def execute(self, context: EnrichmentContext) -> StageResult:
        """Fetch core metadata from MusicBrainz."""
        mbid = context.artist.mbid
        name = context.artist.name or mbid
        
        # Fetch from MusicBrainz
        data = await musicbrainz.fetch_core(mbid, context.client, artist_name=name)
        
        if not data:
            return StageResult(
                stage_name=self.name,
                success=False,
                metrics={"api_calls": 1, "searched": 1, "found": False}
            )
        
        # Extract useful info for logging
        link_count = sum(1 for k in data.keys() if k.endswith("_url"))
        genre_count = len(data.get("genres", []))
        
        return StageResult.success(
            stage_name=self.name,
            data=data,
            metrics={
                "api_calls": 1,
                "searched": 1,
                "found": True,
                "links_found": link_count,
                "genres_found": genre_count,
            }
        )
