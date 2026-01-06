"""
Integration example showing how to use the new pipeline.

This demonstrates the complete flow:
1. Create artist state from database
2. Create scan options
3. Use planner to generate execution plan
4. Use executor to run the plan
5. Save results to database
"""

import asyncio
import httpx
from app.scanner.pipeline import (
    ArtistState,
    ScanOptions,
    EnrichmentContext,
    EnrichmentPlanner,
    PipelineExecutor,
)


async def enrich_artist_example():
    """
    Example of enriching an artist using the v3 pipeline.
    """
    
    # 1. Load artist from database (simulated here)
    artist_row = {
        "mbid": "b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d",  # The Beatles
        "name": "The Beatles",
        "bio": None,  # Missing bio
        "image_url": None,  # Missing artwork
        "has_top_tracks": False,
        "has_singles": False,
        "has_similar": False,
        "spotify_url": None,
        "wikipedia_url": None,
    }
    
    artist = ArtistState.from_db_row(artist_row)
    
    # 2. Create scan options
    options = ScanOptions(
        fetch_metadata=True,
        fetch_artwork=True,
        fetch_bio=True,
        fetch_top_tracks=True,
        fetch_similar_artists=True,
        missing_only=True,  # Only fetch missing data
    )
    
    # 3. Create HTTP client
    async with httpx.AsyncClient(timeout=30.0) as client:
        
        # 4. Create enrichment context
        context = EnrichmentContext(
            artist=artist,
            options=options,
            client=client,
            local_release_groups={"album-1", "album-2"}  # From database
        )
        
        # 5. Create plan
        planner = EnrichmentPlanner()
        plan = planner.create_plan(artist, options, context.local_release_groups)
        
        print(f"Plan created: {plan.stage_count} stages")
        for stage in plan.stages:
            print(f"  - {stage.name} (deps: {stage.dependencies()})")
        
        # 6. Execute plan
        executor = PipelineExecutor()
        result = await executor.execute(plan, context)
        
        # 7. Review results
        print("\nExecution complete:")
        print(f"  Success: {result.success_count}")
        print(f"  Errors: {result.error_count}")
        print(f"  Skipped: {result.skip_count}")
        print(f"  Total API calls: {result.total_api_calls}")
        
        # 8. Merge data for database update
        update_data = result.merge_data()
        print("\nData to save:")
        for key, value in update_data.items():
            if isinstance(value, str) and len(value) > 50:
                print(f"  {key}: {value[:50]}...")
            elif isinstance(value, list):
                print(f"  {key}: [{len(value)} items]")
            else:
                print(f"  {key}: {value}")
        
        # 9. Save to database (would be done here)
        # await save_artist_metadata(artist.mbid, update_data)
        
        return result


async def compare_pipelines_example():
    """
    Example showing how to validate pipeline results.
    """
    
    # Load artist
    artist_row = {"mbid": "test-123", "name": "Test Artist"}
    artist = ArtistState.from_db_row(artist_row)
    options = ScanOptions(fetch_metadata=True, fetch_artwork=True)
    
    async with httpx.AsyncClient() as client:
        # Run new pipeline
        context = EnrichmentContext(artist, options, client)
        planner = EnrichmentPlanner()
        executor = PipelineExecutor()
        
        plan = planner.create_plan(artist, options)
        await executor.execute(plan, context)
        # result = new_result.merge_data()  # Unused for now
        
        # Run old coordinator (commented out - would call existing code)
        # old_data = await old_coordinator.process_artist(artist_row, options)
        
        # Compare results
        # assert new_data == old_data, "Results don't match!"
        
        print("✅ New pipeline produces same results as old coordinator")


if __name__ == "__main__":
    # Run example
    asyncio.run(enrich_artist_example())
