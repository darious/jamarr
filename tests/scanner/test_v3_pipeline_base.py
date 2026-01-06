"""
Tests for pipeline base stage class.

Test naming convention: test_v3_pipeline_* for new pipeline tests.
"""

import pytest
from app.scanner.pipeline.base import EnrichmentStage
from app.scanner.pipeline.models import EnrichmentContext, StageResult, ArtistState, ScanOptions
from unittest.mock import Mock, AsyncMock
import httpx


class MockStage(EnrichmentStage):
    """Mock stage for testing."""
    
    def __init__(self, name="mock_stage", deps=None, should_skip=False, skip_reason="", execute_result=None):
        self._name = name
        self._deps = deps or []
        self._should_skip = should_skip
        self._skip_reason = skip_reason
        self._execute_result = execute_result or StageResult.success(name, {"data": "test"})
        self.execute_called = False
    
    @property
    def name(self) -> str:
        return self._name
    
    def dependencies(self):
        return self._deps
    
    def should_skip(self, context):
        return self._should_skip, self._skip_reason
    
    async def execute(self, context):
        self.execute_called = True
        return self._execute_result


class TestEnrichmentStageBase:
    """Test EnrichmentStage base class."""
    
    @pytest.mark.asyncio
    async def test_v3_pipeline_stage_safe_execute_success(self):
        """Test safe_execute with successful execution."""
        stage = MockStage(
            execute_result=StageResult.success("test", {"key": "value"}, {"api_calls": 1})
        )
        
        ctx = EnrichmentContext(
            ArtistState(mbid="123"),
            ScanOptions(),
            Mock(spec=httpx.AsyncClient)
        )
        
        result = await stage.safe_execute(ctx)
        
        assert result.success
        assert result.data == {"key": "value"}
        assert result.metrics == {"api_calls": 1}
        assert stage.execute_called
    
    @pytest.mark.asyncio
    async def test_v3_pipeline_stage_safe_execute_skip(self):
        """Test safe_execute with skip logic."""
        stage = MockStage(should_skip=True, skip_reason="Not needed")
        
        ctx = EnrichmentContext(
            ArtistState(mbid="123"),
            ScanOptions(),
            Mock(spec=httpx.AsyncClient)
        )
        
        result = await stage.safe_execute(ctx)
        
        assert result.skipped
        assert result.skip_reason == "Not needed"
        assert not stage.execute_called  # Should not execute
    
    @pytest.mark.asyncio
    async def test_v3_pipeline_stage_safe_execute_error_handling(self):
        """Test safe_execute handles exceptions."""
        async def failing_execute(ctx):
            raise ValueError("Test error")
        
        stage = MockStage()
        stage.execute = failing_execute
        
        ctx = EnrichmentContext(
            ArtistState(mbid="123"),
            ScanOptions(),
            Mock(spec=httpx.AsyncClient)
        )
        
        result = await stage.safe_execute(ctx)
        
        assert not result.success
        assert result.error == "Test error"
    
    def test_v3_pipeline_stage_dependencies(self):
        """Test stage dependency declaration."""
        stage = MockStage(deps=["stage1", "stage2"])
        
        assert stage.dependencies() == ["stage1", "stage2"]
    
    def test_v3_pipeline_stage_default_no_skip(self):
        """Test default should_skip returns False."""
        stage = MockStage()
        ctx = EnrichmentContext(
            ArtistState(mbid="123"),
            ScanOptions(),
            Mock()
        )
        
        should_skip, reason = stage.should_skip(ctx)
        
        assert not should_skip
        assert reason == ""
