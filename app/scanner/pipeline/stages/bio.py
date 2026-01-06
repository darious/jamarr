"""
Wikipedia Biography Stage - Fetch artist biography from Wikipedia.

This stage depends on having a Wikipedia URL from core_metadata or external_links.
"""

from typing import List
from app.scanner.pipeline.base import EnrichmentStage
from app.scanner.pipeline.models import EnrichmentContext, StageResult
from app.scanner.services import wikipedia
import logging

logger = logging.getLogger(__name__)


class WikipediaBioStage(EnrichmentStage):
    """
    Fetch artist biography from Wikipedia.
    
    Requires a Wikipedia URL from previous stages.
    """
    
    @property
    def name(self) -> str:
        return "wikipedia_bio"
    
    def dependencies(self) -> List[str]:
        # Needs Wikipedia URL from core_metadata or external_links
        return ["core_metadata", "external_links"]
    
    def should_skip(self, context: EnrichmentContext) -> tuple[bool, str]:
        """Skip if missing_only and we already have a bio."""
        if context.options.missing_only and context.artist.has_bio:
            return True, "Artist already has biography"
        
        # Also skip if we don't have a Wikipedia URL
        wiki_url = self._get_wikipedia_url(context)
        if not wiki_url:
            return True, "No Wikipedia URL available"
        
        return False, ""
    
    async def execute(self, context: EnrichmentContext) -> StageResult:
        """Fetch biography from Wikipedia."""
        wiki_url = self._get_wikipedia_url(context)
        
        # If no Wikipedia URL, skip (don't report as success with empty bio)
        if not wiki_url:
            return StageResult.skip(
                self.name,
                "No Wikipedia URL available (may be rate limited)"
            )
        
        # Fetch bio
        bio = await wikipedia.fetch_bio(context.client, wiki_url)
        
        if not bio:
            # Return success with empty data - no bio found is not an error
            return StageResult.success(
                stage_name=self.name,
                data={},
                metrics={"api_calls": 1, "searched": 1, "found": False, "bio_length": 0}
            )
        
        return StageResult.success(
            stage_name=self.name,
            data={"bio": bio},
            metrics={
                "api_calls": 1,
                "searched": 1,
                "found": True,
                "bio_length": len(bio),
            }
        )
    
    def _get_wikipedia_url(self, context: EnrichmentContext) -> str:
        """Get Wikipedia URL from various sources."""
        # Check artist state
        wiki_url = context.artist.get_link("wikipedia")
        if wiki_url:
            return wiki_url
        
        # Check core_metadata result
        wiki_url = context.get_data("core_metadata", "wikipedia_url")
        if wiki_url:
            return wiki_url
        
        # Check external_links result
        wiki_url = context.get_data("external_links", "wikipedia_url")
        if wiki_url:
            return wiki_url
        
        return None
