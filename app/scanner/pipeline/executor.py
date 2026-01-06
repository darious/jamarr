"""
Pipeline Executor - Executes enrichment stages with dependency resolution.

This orchestrates the execution of stages, respecting their dependencies
and enabling parallel execution of independent stages.
"""

from typing import Dict, Set, List
from app.scanner.pipeline.models import (
    EnrichmentContext,
    EnrichmentPlan,
    PipelineResult,
    StageResult,
)
from app.scanner.pipeline.base import EnrichmentStage
import asyncio
import logging

logger = logging.getLogger(__name__)


class PipelineExecutor:
    """
    Executes an enrichment plan with dependency resolution.
    
    Stages are executed in dependency order, with independent stages
    running in parallel for performance.
    """
    
    async def execute(
        self,
        plan: EnrichmentPlan,
        context: EnrichmentContext
    ) -> PipelineResult:
        """
        Execute an enrichment plan.
        
        Args:
            plan: The enrichment plan to execute
            context: Context with artist state, options, and HTTP client
        
        Returns:
            PipelineResult with all stage results
        """
        if plan.stage_count == 0:
            logger.info("Empty plan, nothing to execute")
            return PipelineResult()
        
        # Build dependency graph
        dep_graph = self._build_dependency_graph(plan.stages)
        
        # Execute stages in dependency order
        completed: Dict[str, StageResult] = {}
        remaining = set(s.name for s in plan.stages)
        
        while remaining:
            # Find stages ready to execute (all dependencies met)
            ready = self._find_ready_stages(plan.stages, dep_graph, completed, remaining)
            
            if not ready:
                # Circular dependency or missing dependency
                logger.error(f"No stages ready to execute. Remaining: {remaining}")
                break
            
            # Execute ready stages in parallel
            logger.debug(f"Executing {len(ready)} stages in parallel: {[s.name for s in ready]}")
            results = await self._execute_parallel(ready, context)
            
            # Update completed and remaining
            for result in results:
                completed[result.stage_name] = result
                context.add_result(result)
                remaining.discard(result.stage_name)
        
        return PipelineResult(results=completed)
    
    def _build_dependency_graph(
        self,
        stages: List[EnrichmentStage]
    ) -> Dict[str, Set[str]]:
        """
        Build a dependency graph from stages.
        
        Returns:
            Dict mapping stage name to set of dependency names
        """
        graph = {}
        for stage in stages:
            graph[stage.name] = set(stage.dependencies())
        return graph
    
    def _find_ready_stages(
        self,
        stages: List[EnrichmentStage],
        dep_graph: Dict[str, Set[str]],
        completed: Dict[str, StageResult],
        remaining: Set[str]
    ) -> List[EnrichmentStage]:
        """
        Find stages that are ready to execute.
        
        A stage is ready if all its dependencies have completed.
        """
        ready = []
        for stage in stages:
            if stage.name not in remaining:
                continue
            
            deps = dep_graph.get(stage.name, set())
            if all(dep in completed for dep in deps):
                ready.append(stage)
        
        return ready
    
    async def _execute_parallel(
        self,
        stages: List[EnrichmentStage],
        context: EnrichmentContext
    ) -> List[StageResult]:
        """
        Execute multiple stages in parallel.
        
        Uses asyncio.gather to run stages concurrently.
        """
        tasks = [stage.safe_execute(context) for stage in stages]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results
