"""
Tests for PipelineExecutor.

Test naming convention: test_v3_executor_* for new pipeline tests.
"""

import pytest
from app.scanner.pipeline.executor import PipelineExecutor
from app.scanner.pipeline.models import (
    ArtistState,
    ScanOptions,
    EnrichmentContext,
    EnrichmentPlan,
    StageResult,
)
from app.scanner.pipeline.base import EnrichmentStage
from app.scanner.pipeline.stages import WikipediaBioStage
from unittest.mock import Mock
import httpx


class MockStage(EnrichmentStage):
    """Mock stage for testing."""
    
    def __init__(self, name, deps=None, result=None, delay=0):
        self._name = name
        self._deps = deps or []
        self._result = result or StageResult.success(name, {"data": name})
        self._delay = delay
        self.executed = False
    
    @property
    def name(self):
        return self._name
    
    def dependencies(self):
        return self._deps
    
    async def execute(self, context):
        self.executed = True
        if self._delay:
            import asyncio
            await asyncio.sleep(self._delay)
        return self._result


@pytest.fixture
def mock_context():
    """Create a mock enrichment context."""
    artist = ArtistState(mbid="test-123", name="Test Artist")
    options = ScanOptions()
    client = Mock(spec=httpx.AsyncClient)
    return EnrichmentContext(artist, options, client)


class TestPipelineExecutor:
    """Test PipelineExecutor."""
    
    @pytest.mark.asyncio
    async def test_v3_executor_empty_plan(self, mock_context):
        """Test executor with empty plan."""
        executor = PipelineExecutor()
        plan = EnrichmentPlan()
        
        result = await executor.execute(plan, mock_context)
        
        assert result.success_count == 0
        assert result.error_count == 0
    
    @pytest.mark.asyncio
    async def test_v3_executor_single_stage(self, mock_context):
        """Test executor with single stage."""
        executor = PipelineExecutor()
        plan = EnrichmentPlan()
        
        stage = MockStage("test_stage")
        plan.add_stage(stage)
        
        result = await executor.execute(plan, mock_context)
        
        assert result.success_count == 1
        assert stage.executed
        assert "test_stage" in result.results
    
    @pytest.mark.asyncio
    async def test_v3_executor_independent_stages_parallel(self, mock_context):
        """Test executor runs independent stages in parallel."""
        executor = PipelineExecutor()
        plan = EnrichmentPlan()
        
        # Three independent stages
        stage1 = MockStage("stage1", delay=0.1)
        stage2 = MockStage("stage2", delay=0.1)
        stage3 = MockStage("stage3", delay=0.1)
        
        plan.add_stage(stage1)
        plan.add_stage(stage2)
        plan.add_stage(stage3)
        
        import time
        start = time.time()
        result = await executor.execute(plan, mock_context)
        elapsed = time.time() - start
        
        # Should take ~0.1s (parallel) not ~0.3s (sequential)
        assert elapsed < 0.25  # Allow some overhead
        assert result.success_count == 3
        assert stage1.executed
        assert stage2.executed
        assert stage3.executed
    
    @pytest.mark.asyncio
    async def test_v3_executor_dependency_order(self, mock_context):
        """Test executor respects dependency order."""
        executor = PipelineExecutor()
        plan = EnrichmentPlan()
        
        # stage2 depends on stage1
        stage1 = MockStage("stage1")
        stage2 = MockStage("stage2", deps=["stage1"])
        
        plan.add_stage(stage1)
        plan.add_stage(stage2)
        
        result = await executor.execute(plan, mock_context)
        
        assert result.success_count == 2
        assert stage1.executed
        assert stage2.executed
        
        # stage1 should complete before stage2
        assert "stage1" in result.results
        assert "stage2" in result.results
    
    @pytest.mark.asyncio
    async def test_v3_executor_complex_dependencies(self, mock_context):
        """Test executor with complex dependency graph."""
        executor = PipelineExecutor()
        plan = EnrichmentPlan()
        
        # Dependency graph:
        #   stage1 (no deps)
        #   stage2 (no deps)
        #   stage3 depends on stage1
        #   stage4 depends on stage1, stage2
        #   stage5 depends on stage3, stage4
        
        stage1 = MockStage("stage1")
        stage2 = MockStage("stage2")
        stage3 = MockStage("stage3", deps=["stage1"])
        stage4 = MockStage("stage4", deps=["stage1", "stage2"])
        stage5 = MockStage("stage5", deps=["stage3", "stage4"])
        
        plan.add_stage(stage1)
        plan.add_stage(stage2)
        plan.add_stage(stage3)
        plan.add_stage(stage4)
        plan.add_stage(stage5)
        
        result = await executor.execute(plan, mock_context)
        
        assert result.success_count == 5
        assert all(s.executed for s in [stage1, stage2, stage3, stage4, stage5])
    
    @pytest.mark.asyncio
    async def test_v3_executor_stage_failure(self, mock_context):
        """Test executor handles stage failures gracefully."""
        executor = PipelineExecutor()
        plan = EnrichmentPlan()
        
        # stage1 succeeds, stage2 fails, stage3 depends on stage2
        stage1 = MockStage("stage1")
        stage2 = MockStage("stage2", result=StageResult.from_error("stage2", "Failed"))
        stage3 = MockStage("stage3", deps=["stage2"])
        
        plan.add_stage(stage1)
        plan.add_stage(stage2)
        plan.add_stage(stage3)
        
        result = await executor.execute(plan, mock_context)
        
        # All stages execute (dependencies don't block execution)
        assert result.success_count == 2  # stage1 and stage3
        assert result.error_count == 1  # stage2
        assert stage1.executed
        assert stage2.executed
        assert stage3.executed  # Still executes even if dependency failed
    
    @pytest.mark.asyncio
    async def test_v3_executor_context_updates(self, mock_context):
        """Test executor updates context with results."""
        executor = PipelineExecutor()
        plan = EnrichmentPlan()
        
        stage1 = MockStage("stage1", result=StageResult.success("stage1", {"key": "value"}))
        stage2 = MockStage("stage2", deps=["stage1"])
        
        plan.add_stage(stage1)
        plan.add_stage(stage2)
        
        await executor.execute(plan, mock_context)
        
        # Context should have both results
        assert mock_context.has_result("stage1")
        assert mock_context.has_result("stage2")
        assert mock_context.get_data("stage1", "key") == "value"
    
    @pytest.mark.asyncio
    async def test_v3_executor_skip_stage(self, mock_context):
        """Test executor handles skipped stages."""
        executor = PipelineExecutor()
        plan = EnrichmentPlan()
        
        stage = MockStage("stage", result=StageResult.skip("stage", "Not needed"))
        plan.add_stage(stage)
        
        result = await executor.execute(plan, mock_context)
        
        assert result.skip_count == 1
        assert result.success_count == 0
        assert stage.executed
    
    @pytest.mark.asyncio
    async def test_v3_executor_unplanned_dependency_does_not_block(self, mock_context):
        """A dependency the plan never included must not stall the stage."""
        executor = PipelineExecutor()
        plan = EnrichmentPlan()
        
        # stage2 depends on a stage that is not in the plan at all
        stage1 = MockStage("stage1")
        stage2 = MockStage("stage2", deps=["stage1", "never_planned"])
        
        plan.add_stage(stage1)
        plan.add_stage(stage2)
        
        result = await executor.execute(plan, mock_context)
        
        assert result.success_count == 2
        assert stage1.executed
        assert stage2.executed
    
    @pytest.mark.asyncio
    async def test_v3_executor_only_unplanned_dependencies(self, mock_context):
        """A stage whose every dependency is unplanned still runs."""
        executor = PipelineExecutor()
        plan = EnrichmentPlan()
        
        stage = MockStage("stage", deps=["missing_a", "missing_b"])
        plan.add_stage(stage)
        
        result = await executor.execute(plan, mock_context)
        
        assert result.success_count == 1
        assert stage.executed
    
    @pytest.mark.asyncio
    async def test_v3_executor_unknown_dependency_logged(self, mock_context, caplog):
        """A dependency naming no real stage is an error, not a planning choice."""
        executor = PipelineExecutor()
        plan = EnrichmentPlan()
        plan.add_stage(MockStage("stage", deps=["not_a_stage"]))
        
        with caplog.at_level("ERROR", logger="app.scanner.pipeline.executor"):
            await executor.execute(plan, mock_context)
        
        assert "not a known stage" in caplog.text
        assert "not_a_stage" in caplog.text
    
    @pytest.mark.asyncio
    async def test_v3_executor_known_dependency_left_out_is_not_an_error(
        self, mock_context, caplog
    ):
        """Leaving a real stage out of the plan is deliberate, so it stays quiet."""
        executor = PipelineExecutor()
        plan = EnrichmentPlan()
        plan.add_stage(WikipediaBioStage())
        
        with caplog.at_level("ERROR", logger="app.scanner.pipeline.executor"):
            await executor.execute(plan, mock_context)
        
        assert caplog.text == ""
    
    @pytest.mark.asyncio
    async def test_v3_executor_circular_dependency_still_reported(
        self, mock_context, caplog
    ):
        """A real cycle between planned stages must still surface and stop."""
        executor = PipelineExecutor()
        plan = EnrichmentPlan()
        
        stage1 = MockStage("stage1", deps=["stage2"])
        stage2 = MockStage("stage2", deps=["stage1"])
        
        plan.add_stage(stage1)
        plan.add_stage(stage2)
        
        with caplog.at_level("ERROR", logger="app.scanner.pipeline.executor"):
            result = await executor.execute(plan, mock_context)
        
        assert "Circular dependency" in caplog.text
        assert result.success_count == 0
        assert not stage1.executed
        assert not stage2.executed


class TestDependencyGraphIsUnchangedForCompletePlans:
    """Pruning must be invisible to any plan that includes all its dependencies.
    
    The full library scan plans every stage, so its dependency graph has to
    come out byte-identical to the pre-pruning behaviour. Anything else means
    the fix changed a path that was already working.
    """
    
    @staticmethod
    def _graph_without_pruning(stages):
        """The graph the executor built before unplanned deps were pruned."""
        return {s.name: set(s.dependencies()) for s in stages}
    
    @pytest.mark.parametrize("label,options", [
        (
            "scheduler full scan",
            ScanOptions(
                fetch_metadata=True, fetch_bio=True, fetch_artwork=True,
                fetch_spotify_artwork=True, fetch_links=True,
                refresh_top_tracks=True, refresh_singles=True,
                fetch_similar_artists=True, fetch_album_metadata=True,
                missing_only=True,
            ),
        ),
        (
            "metadata and links only",
            ScanOptions(fetch_metadata=True, fetch_links=True),
        ),
        (
            "bio with its dependencies planned",
            ScanOptions(fetch_metadata=True, fetch_bio=True),
        ),
        (
            "stages that declare no dependencies",
            ScanOptions(
                fetch_top_tracks=True, fetch_similar_artists=True,
                fetch_singles=True,
            ),
        ),
    ])
    def test_v3_executor_complete_plan_graph_unchanged(self, label, options):
        from app.scanner.pipeline.planner import EnrichmentPlanner
        
        artist = ArtistState(mbid="test-123", name="Test Artist")
        plan = EnrichmentPlanner().create_plan(artist, options, {"rg-1"})
        
        assert plan.stage_count > 0, label
        assert PipelineExecutor()._build_dependency_graph(plan.stages) == \
            self._graph_without_pruning(plan.stages), label
