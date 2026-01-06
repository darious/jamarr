"""
Album Metadata Stage - Fetch metadata for artist's albums.

This stage fetches descriptions and chart positions for albums
from MusicBrainz and Wikipedia.
"""

from typing import List
from app.scanner.pipeline.base import EnrichmentStage
from app.scanner.pipeline.models import EnrichmentContext, StageResult
from app.scanner.services import album
import asyncio
import logging

logger = logging.getLogger(__name__)


class AlbumMetadataStage(EnrichmentStage):
    """
    Fetch metadata for artist's local albums.
    
    For each album (release group), fetches:
    - Description from Wikipedia
    - Peak chart position
    - External links
    """
    
    @property
    def name(self) -> str:
        return "album_metadata"
    
    def dependencies(self) -> List[str]:
        # No dependencies - uses local release groups from context
        return []
    
    def should_skip(self, context: EnrichmentContext) -> tuple[bool, str]:
        """Skip if no local albums to process."""
        if not context.local_release_groups:
            return True, "No local albums for this artist"
        
        return False, ""
    
    async def execute(self, context: EnrichmentContext) -> StageResult:
        """Fetch metadata for all local albums."""
        album_ids = list(context.local_release_groups)
        
        # If missing_only, filter to albums without descriptions
        if context.options.missing_only:
            album_ids = await self._filter_missing_albums(context, album_ids)
            
            if not album_ids:
                return StageResult.skip(
                    self.name,
                    f"All {len(context.local_release_groups)} albums already have metadata"
                )
        
        # Fetch all albums in parallel
        # Use global DNS semaphore from coordinator to prevent DNS overload
        from app.scanner.services.coordinator import _dns_semaphore
        
        tasks = [
            album.fetch_album_metadata(rg_id, context.client, _dns_semaphore)
            for rg_id in album_ids
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        albums_metadata = {}
        success_count = 0
        error_count = 0
        
        for i, result in enumerate(results):
            rg_id = album_ids[i]
            
            if isinstance(result, Exception):
                logger.warning(f"Album metadata fetch failed for {rg_id}: {result}")
                error_count += 1
                continue
            
            if isinstance(result, dict):
                albums_metadata[rg_id] = result
                success_count += 1
        
        if not albums_metadata:
            return StageResult(
                stage_name=self.name,
                success=False,
                metrics={
                    "api_calls": len(tasks),
                    "searched": len(tasks),
                    "found": False,
                    "albums_processed": 0,
                    "errors": error_count,
                }
            )
        
        return StageResult.success(
            stage_name=self.name,
            data={"albums_metadata": albums_metadata},
            metrics={
                "api_calls": len(tasks),
                "searched": len(tasks),
                "found": bool(albums_metadata),
                "albums_processed": success_count,
                "albums_with_data": sum(
                    1 for a in albums_metadata.values()
                    if a.get("description") or a.get("peak_chart_position")
                ),
                "errors": error_count,
            }
        )
    
    async def _filter_missing_albums(
        self,
        context: EnrichmentContext,
        album_ids: List[str]
    ) -> List[str]:
        """Filter to only albums missing descriptions."""
        from app.db import get_pool
        
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT release_group_mbid 
                FROM album 
                WHERE release_group_mbid = ANY($1) 
                AND description IS NOT NULL
                """,
                album_ids
            )
            
            albums_with_desc = {row["release_group_mbid"] for row in rows}
            return [aid for aid in album_ids if aid not in albums_with_desc]
