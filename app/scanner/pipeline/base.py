"""
Base class for all enrichment stages.

Each stage is responsible for fetching one type of metadata from
an external source and returning a structured result.
"""

from abc import ABC, abstractmethod
from typing import List
from app.scanner.pipeline.models import EnrichmentContext, StageResult
import logging

logger = logging.getLogger(__name__)


class EnrichmentStage(ABC):
    """
    Base class for all enrichment stages.
    
    Each stage:
    - Declares its dependencies (what data it needs from previous stages)
    - Executes independently to fetch one type of data
    - Returns a structured StageResult
    - Is fully testable in isolation
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this stage."""
        pass
    
    @abstractmethod
    def dependencies(self) -> List[str]:
        """
        List of stage names this stage depends on.
        
        The executor will ensure these stages complete before this one runs.
        Return empty list if no dependencies.
        """
        pass
    
    @abstractmethod
    async def execute(self, context: EnrichmentContext) -> StageResult:
        """
        Execute this enrichment stage.
        
        Args:
            context: Immutable context with artist data, HTTP client, and
                    results from previous stages
        
        Returns:
            StageResult with fetched data, success status, and metrics
        """
        pass
    
    def should_skip(self, context: EnrichmentContext) -> tuple[bool, str]:
        """
        Check if this stage should be skipped.
        
        Override this method to implement stage-specific skip logic.
        Default implementation never skips.
        
        Returns:
            (should_skip, reason) tuple
        """
        return False, ""
    
    async def safe_execute(self, context: EnrichmentContext) -> StageResult:
        """
        Execute with error handling and skip logic.
        
        This is the main entry point called by the executor.
        """
        # Check if should skip
        should_skip, reason = self.should_skip(context)
        if should_skip:
            logger.debug(f"[{self.name}] Skipping: {reason}")
            return StageResult.skip(self.name, reason)
        
        # Execute with error handling
        try:
            logger.debug(f"[{self.name}] Executing...")
            result = await self.execute(context)
            
            if result.success:
                logger.info(f"[{self.name}] Success: {result.metrics}")
            elif result.error:
                logger.warning(f"[{self.name}] Error: {result.error}")
            else:
                logger.debug(f"[{self.name}] No data found")
            
            return result
            
        except Exception as e:
            logger.exception(f"[{self.name}] Unexpected error")
            return StageResult.from_error(self.name, str(e))
