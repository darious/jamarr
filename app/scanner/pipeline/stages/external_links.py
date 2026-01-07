"""
External Links Stage - Fetch missing external links from Wikidata.

This stage is a fallback for when MusicBrainz doesn't have all the links we need.
It depends on core_metadata to get the Wikidata URL.
"""

from typing import List
from app.scanner.pipeline.base import EnrichmentStage
from app.scanner.pipeline.models import EnrichmentContext, StageResult
from app.scanner.services import wikidata
import logging

logger = logging.getLogger(__name__)


class ExternalLinksStage(EnrichmentStage):
    """
    Fetch external links from Wikidata.
    
    This stage runs after core_metadata and fills in any missing links
    that MusicBrainz didn't have.
    """
    
    @property
    def name(self) -> str:
        return "external_links"
    
    def dependencies(self) -> List[str]:
        # Depends on core_metadata to get Wikidata URL
        return ["core_metadata"]
    
    def should_skip(self, context: EnrichmentContext) -> tuple[bool, str]:
        """Skip if we don't have a Wikidata URL or don't need links."""
        # Get Wikidata URL from core_metadata or artist state
        wikidata_url = context.get_data("core_metadata", "wikidata_url")
        if not wikidata_url:
            wikidata_url = context.artist.get_link("wikidata")
        
        if not wikidata_url:
            return True, "No Wikidata URL available"
        
        # If missing_only, check if we already have all links
        if context.options.missing_only:
            required_links = [
                "spotify", "wikipedia", "qobuz", "tidal",
                "lastfm", "discogs", "homepage"
            ]
            
            # Check existing links from artist state
            existing = {
                link_type: context.artist.get_link(link_type)
                for link_type in required_links
            }
            
            # Also check links from core_metadata stage
            core_result = context.get_result("core_metadata")
            if core_result and core_result.data:
                for link_type in required_links:
                    url_key = f"{link_type}_url"
                    if core_result.data.get(url_key):
                        existing[link_type] = core_result.data[url_key]
            
            if all(existing.values()):
                return True, "All external links already present"
        
        return False, ""
    
    async def execute(self, context: EnrichmentContext) -> StageResult:
        """Fetch external links from Wikidata."""
        # Get Wikidata URL
        wikidata_url = context.get_data("core_metadata", "wikidata_url")
        if not wikidata_url:
            wikidata_url = context.artist.get_link("wikidata")
        
        # Build existing links dict
        existing = {}
        for link_type in ["spotify", "tidal", "qobuz", "lastfm", "discogs", "homepage"]:
            url = context.artist.get_link(link_type)
            if url:
                existing[link_type] = url
        
        # Also include links from core_metadata
        core_result = context.get_result("core_metadata")
        if core_result and core_result.data:
            for key, value in core_result.data.items():
                if key.endswith("_url") and value:
                    link_type = key.replace("_url", "")
                    existing[link_type] = value
        
        # Fetch from Wikidata
        links = await wikidata.fetch_external_links(
            context.client,
            wikidata_url,
            existing
        )
        
        # If no Qobuz link found, try searching Qobuz directly
        if not links.get("qobuz_url") and not existing.get("qobuz"):
            from app.scanner.services.qobuz import QobuzClient
            
            artist_name = context.artist.name
            if artist_name:
                try:
                    qobuz_client = QobuzClient(client=context.client)
                    qobuz_url = await qobuz_client.search_artist(artist_name)
                    
                    if qobuz_url:
                        if not links:
                            links = {}
                        links["qobuz_url"] = qobuz_url
                        logger.info(f"Found Qobuz link via search: {qobuz_url}")
                except Exception as e:
                    logger.warning(f"Qobuz search failed for {artist_name}: {e}")
        
        if not links:
            # Return success with empty data - no links found is not an error
            return StageResult.success(
                stage_name=self.name,
                data={},
                metrics={"api_calls": 1, "searched": 1, "found": False, "links_found": 0}
            )
        
        return StageResult.success(
            stage_name=self.name,
            data=links,
            metrics={
                "api_calls": 1,
                "searched": 1,
                "found": True,
                "links_found": len(links),
            }
        )
