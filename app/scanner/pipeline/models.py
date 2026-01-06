"""
Data models for the scanner pipeline.

All models are immutable (frozen dataclasses) to prevent bugs from mutation.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set
import httpx


@dataclass(frozen=True)
class ArtistState:
    """
    Immutable snapshot of artist state from database.
    
    This represents what we currently know about an artist.
    Used by the planner to determine what enrichment is needed.
    """
    
    mbid: str
    name: Optional[str] = None
    sort_name: Optional[str] = None
    bio: Optional[str] = None
    image_url: Optional[str] = None
    image_source: Optional[str] = None
    artwork_id: Optional[int] = None
    
    # External links (type -> url)
    external_links: Dict[str, str] = field(default_factory=dict)
    
    # Presence flags for optimization
    has_top_tracks: bool = False
    has_singles: bool = False
    has_similar: bool = False
    has_primary_album: bool = False
    
    @property
    def has_name(self) -> bool:
        """Check if artist has a name."""
        return bool(self.name)
    
    @property
    def has_bio(self) -> bool:
        """Check if artist has a biography."""
        return bool(self.bio)
    
    @property
    def has_artwork(self) -> bool:
        """Check if artist has any artwork."""
        return bool(self.image_url)
    
    @property
    def needs_artwork_upgrade(self) -> bool:
        """Check if artwork needs upgrade (Spotify -> Fanart)."""
        return self.image_source == "spotify"
    
    def has_link(self, link_type: str) -> bool:
        """Check if artist has a specific external link."""
        return link_type in self.external_links
    
    def get_link(self, link_type: str) -> Optional[str]:
        """Get a specific external link URL."""
        return self.external_links.get(link_type)
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'ArtistState':
        """
        Create ArtistState from database row.
        
        Handles unpacking external_links JSON and flattening the structure.
        """
        external_links = {}
        
        # Handle external links from various formats
        if "all_links" in row and row["all_links"]:
            external_links = row["all_links"]
        else:
            # Build from individual link fields
            link_fields = [
                "spotify_url", "homepage", "wikipedia_url", "wikidata_url",
                "qobuz_url", "tidal_url", "lastfm_url", "discogs_url"
            ]
            for field in link_fields:
                if row.get(field):
                    link_type = field.replace("_url", "")
                    external_links[link_type] = row[field]
        
        return cls(
            mbid=row["mbid"],
            name=row.get("name"),
            sort_name=row.get("sort_name"),
            bio=row.get("bio"),
            image_url=row.get("image_url"),
            image_source=row.get("image_source"),
            artwork_id=row.get("artwork_id"),
            external_links=external_links,
            has_top_tracks=row.get("has_top_tracks", False),
            has_singles=row.get("has_singles", False),
            has_similar=row.get("has_similar", False),
            has_primary_album=row.get("has_primary_album", False),
        )


@dataclass(frozen=True)
class ScanOptions:
    """
    User-provided scan options.
    
    These control what enrichment operations to perform.
    """
    
    # Core metadata and links
    fetch_metadata: bool = False
    fetch_base_metadata: bool = False  # Backwards compat
    fetch_links: bool = False
    
    # Artwork
    fetch_artwork: bool = False
    fetch_spotify_artwork: bool = False
    
    # Enrichment data
    fetch_bio: bool = False
    fetch_top_tracks: bool = False
    refresh_top_tracks: bool = False  # Backwards compat
    fetch_similar_artists: bool = False
    refresh_similar_artists: bool = False  # Backwards compat
    fetch_singles: bool = False
    refresh_singles: bool = False  # Backwards compat
    
    # Album metadata
    fetch_album_metadata: bool = False
    
    # Optimization flags
    missing_only: bool = False
    links_only: bool = False
    
    @property
    def effective_fetch_metadata(self) -> bool:
        """Get effective metadata fetch flag (handles backwards compat)."""
        return self.fetch_metadata or self.fetch_base_metadata
    
    @property
    def effective_fetch_top_tracks(self) -> bool:
        """Get effective top tracks flag (handles backwards compat)."""
        return self.fetch_top_tracks or self.refresh_top_tracks
    
    @property
    def effective_fetch_similar(self) -> bool:
        """Get effective similar artists flag (handles backwards compat)."""
        return self.fetch_similar_artists or self.refresh_similar_artists
    
    @property
    def effective_fetch_singles(self) -> bool:
        """Get effective singles flag (handles backwards compat)."""
        return self.fetch_singles or self.refresh_singles


@dataclass
class StageResult:
    """
    Result from a single enrichment stage.
    
    Contains the fetched data, success status, metrics, and any errors.
    """
    
    stage_name: str
    success: bool
    data: Optional[Dict[str, Any]] = None
    metrics: Dict[str, int] = field(default_factory=dict)
    error: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None
    
    @classmethod
    def skip(cls, stage_name: str, reason: str) -> 'StageResult':
        """Create a skipped result."""
        return cls(
            stage_name=stage_name,
            success=False,
            skipped=True,
            skip_reason=reason,
            metrics={}
        )
    
    @classmethod
    def from_error(cls, stage_name: str, error_msg: str) -> 'StageResult':
        """Create an error result."""
        return cls(
            stage_name=stage_name,
            success=False,
            error=error_msg,
            metrics={}
        )
    
    @classmethod
    def success(cls, stage_name: str, data: Dict[str, Any], metrics: Optional[Dict[str, int]] = None) -> 'StageResult':
        """Create a success result."""
        return cls(
            stage_name=stage_name,
            success=True,
            data=data,
            metrics=metrics or {}
        )


@dataclass
class EnrichmentContext:
    """
    Context passed to each enrichment stage.
    
    Contains the artist state, options, HTTP client, and results from
    previous stages. Immutable except for the results dictionary which
    is updated as stages complete.
    """
    
    artist: ArtistState
    options: ScanOptions
    client: httpx.AsyncClient
    local_release_groups: Set[str] = field(default_factory=set)
    _results: Dict[str, StageResult] = field(default_factory=dict)
    
    def get_result(self, stage_name: str) -> Optional[StageResult]:
        """Get result from a previous stage."""
        return self._results.get(stage_name)
    
    def has_result(self, stage_name: str) -> bool:
        """Check if a stage has completed."""
        return stage_name in self._results
    
    def get_data(self, stage_name: str, key: str, default: Any = None) -> Any:
        """Get a specific data value from a previous stage result."""
        result = self.get_result(stage_name)
        if result and result.data:
            return result.data.get(key, default)
        return default
    
    def with_results(self, results: Dict[str, StageResult]) -> 'EnrichmentContext':
        """Return new context with updated results."""
        ctx = EnrichmentContext(
            artist=self.artist,
            options=self.options,
            client=self.client,
            local_release_groups=self.local_release_groups
        )
        ctx._results = {**self._results, **results}
        return ctx
    
    def add_result(self, result: StageResult) -> None:
        """Add a result to this context (mutates in place)."""
        self._results[result.stage_name] = result


@dataclass
class EnrichmentPlan:
    """
    Plan for enriching an artist.
    
    Contains the list of stages to execute, determined by the planner
    based on artist state and user options.
    """
    
    stages: List['EnrichmentStage'] = field(default_factory=list)
    
    def add_stage(self, stage: 'EnrichmentStage') -> None:
        """Add a stage to the plan."""
        self.stages.append(stage)
    
    def has_stage(self, stage_type: type) -> bool:
        """Check if plan includes a specific stage type."""
        return any(isinstance(s, stage_type) for s in self.stages)
    
    @property
    def stage_count(self) -> int:
        """Get number of stages in plan."""
        return len(self.stages)


@dataclass
class PipelineResult:
    """
    Result from executing a complete pipeline.
    
    Contains all stage results and aggregate metrics.
    """
    
    results: Dict[str, StageResult] = field(default_factory=dict)
    
    def get(self, stage_name: str) -> Optional[StageResult]:
        """Get result for a specific stage."""
        return self.results.get(stage_name)
    
    @property
    def success_count(self) -> int:
        """Count successful stages."""
        return sum(1 for r in self.results.values() if r.success)
    
    @property
    def error_count(self) -> int:
        """Count failed stages."""
        return sum(1 for r in self.results.values() if r.error)
    
    @property
    def skip_count(self) -> int:
        """Count skipped stages."""
        return sum(1 for r in self.results.values() if r.skipped)
    
    @property
    def total_api_calls(self) -> int:
        """Sum API calls across all stages."""
        return sum(
            r.metrics.get("api_calls", 0)
            for r in self.results.values()
        )
    
    def merge_data(self) -> Dict[str, Any]:
        """
        Merge all successful stage data into a single update dictionary.
        
        This is used to create the final database update payload.
        """
        merged = {}
        for result in self.results.values():
            if result.success and result.data:
                merged.update(result.data)
        return merged
