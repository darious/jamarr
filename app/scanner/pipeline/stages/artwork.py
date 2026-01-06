"""
Artwork Stage - Fetch artist artwork from Fanart.tv and Spotify.

This stage implements the Fanart-first, Spotify-fallback strategy.
"""

from typing import List
from app.scanner.pipeline.base import EnrichmentStage
from app.scanner.pipeline.models import EnrichmentContext, StageResult
from app.scanner.services import artwork
from app.scanner.stats import get_api_tracker
import logging

logger = logging.getLogger(__name__)


class ArtworkStage(EnrichmentStage):
    """
    Fetch artist artwork with Fanart.tv priority, Spotify fallback.
    
    Strategy:
    1. Try Fanart.tv first (higher quality)
    2. If no Fanart, try Spotify (requires Spotify URL)
    3. Resolve Spotify URL from core_metadata or external_links if needed
    """
    
    @property
    def name(self) -> str:
        return "artwork"
    
    def dependencies(self) -> List[str]:
        # May need Spotify URL from core_metadata or external_links
        return ["core_metadata", "external_links"]
    
    def should_skip(self, context: EnrichmentContext) -> tuple[bool, str]:
        """Skip if missing_only and we have non-Spotify artwork."""
        if not context.options.missing_only:
            return False, ""
        
        artist = context.artist
        
        # Skip if we have artwork and it's not from Spotify
        # (Spotify artwork can be upgraded to Fanart)
        if artist.has_artwork and not artist.needs_artwork_upgrade:
            return True, "Artist has high-quality artwork"
        
        return False, ""
    
    async def execute(self, context: EnrichmentContext) -> StageResult:
        """Fetch artwork from Fanart.tv, fallback to Spotify."""
        mbid = context.artist.mbid
        data = {}
        api_calls = 0
        
        # Try Fanart.tv first
        fanart_res = await artwork.fetch_fanart_artist_images(mbid, context.client)
        api_calls += 1
        
        thumb_url = None
        bg_url = None
        source = None
        
        if fanart_res:
            thumb_url = fanart_res.get("image_url") or fanart_res.get("thumb")
            bg_url = fanart_res.get("background")
            
            if thumb_url:
                data["image_url"] = thumb_url
                data["image_source"] = "fanart"
                source = "fanart"
            if bg_url:
                data["background_url"] = bg_url
            
            get_api_tracker().track_detailed("Fanart", "found" if thumb_url or bg_url else "missing")
        else:
            get_api_tracker().track_detailed("Fanart", "missing")
        
        # If no Fanart thumb, try Spotify
        if not thumb_url and context.options.fetch_spotify_artwork:
            spotify_url = self._get_spotify_url(context)
            
            if spotify_url:
                # Extract Spotify ID from URL
                sp_id = spotify_url.split("/")[-1].split("?")[0]
                
                # Check if we have candidates for resolution
                core_result = context.get_result("core_metadata")
                spotify_candidates = []
                if core_result and core_result.data:
                    spotify_candidates = core_result.data.get("_spotify_candidates", [])
                
                # Resolve ID if we have candidates
                if spotify_candidates and not sp_id:
                    sp_id, resolved_url = await artwork.resolve_spotify_id(
                        spotify_candidates,
                        context.artist.name or mbid,
                        context.client
                    )
                    if resolved_url:
                        data["spotify_url"] = resolved_url
                        spotify_url = resolved_url
                    api_calls += 1
                
                # Fetch image
                if sp_id:
                    img = await artwork.fetch_spotify_artist_images(sp_id, context.client)
                    api_calls += 1
                    
                    if img:
                        data["image_url"] = img
                        data["image_source"] = "spotify"
                        source = "spotify"
                        get_api_tracker().track_detailed("Spotify Art", "found")
                    else:
                        get_api_tracker().track_detailed("Spotify Art", "missing")
            else:
                get_api_tracker().track_detailed("Spotify Art", "missing")
        
        if not data:
            return StageResult(
                stage_name=self.name,
                success=False,
                metrics={"api_calls": api_calls}
            )
        
        return StageResult.success(
            stage_name=self.name,
            data=data,
            metrics={
                "api_calls": api_calls,
                "source": source,
                "has_thumb": bool(data.get("image_url")),
                "has_background": bool(data.get("background_url")),
            }
        )
    
    def _get_spotify_url(self, context: EnrichmentContext) -> str:
        """Get Spotify URL from various sources."""
        # Check artist state
        spotify_url = context.artist.get_link("spotify")
        if spotify_url:
            return spotify_url
        
        # Check core_metadata result
        spotify_url = context.get_data("core_metadata", "spotify_url")
        if spotify_url:
            return spotify_url
        
        # Check external_links result
        spotify_url = context.get_data("external_links", "spotify_url")
        if spotify_url:
            return spotify_url
        
        return None
