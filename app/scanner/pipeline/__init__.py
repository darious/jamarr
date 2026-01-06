"""
Scanner Pipeline Architecture

This package implements a modular pipeline pattern for metadata enrichment.
Each enrichment source is implemented as an independent stage that can be
tested, composed, and executed in isolation.
"""

from app.scanner.pipeline.models import (
    ArtistState,
    ScanOptions,
    EnrichmentContext,
    StageResult,
    EnrichmentPlan,
    PipelineResult,
)
from app.scanner.pipeline.base import EnrichmentStage
from app.scanner.pipeline.planner import EnrichmentPlanner
from app.scanner.pipeline.executor import PipelineExecutor

__all__ = [
    "ArtistState",
    "ScanOptions",
    "EnrichmentContext",
    "StageResult",
    "EnrichmentPlan",
    "PipelineResult",
    "EnrichmentStage",
    "EnrichmentPlanner",
    "PipelineExecutor",
]
