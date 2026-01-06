"""
Pipeline stages package.

Each module contains one enrichment stage implementation.
"""

from app.scanner.pipeline.stages.core_metadata import CoreMetadataStage
from app.scanner.pipeline.stages.external_links import ExternalLinksStage
from app.scanner.pipeline.stages.artwork import ArtworkStage
from app.scanner.pipeline.stages.bio import WikipediaBioStage
from app.scanner.pipeline.stages.top_tracks import TopTracksStage
from app.scanner.pipeline.stages.similar import SimilarArtistsStage
from app.scanner.pipeline.stages.singles import SinglesStage
from app.scanner.pipeline.stages.albums import AlbumMetadataStage

__all__ = [
    "CoreMetadataStage",
    "ExternalLinksStage",
    "ArtworkStage",
    "WikipediaBioStage",
    "TopTracksStage",
    "SimilarArtistsStage",
    "SinglesStage",
    "AlbumMetadataStage",
]
