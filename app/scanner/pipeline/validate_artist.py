#!/usr/bin/env python3
"""
Manual validation script for the new pipeline.

This script allows you to test the pipeline with real API calls
without modifying the database. It shows exactly what data would
be saved for a given artist.

Usage:
    python -m app.scanner.pipeline.validate_artist <mbid> [options]

Examples:
    # Enrich The Beatles with all options
    python -m app.scanner.pipeline.validate_artist b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d --all

    # Fetch only missing metadata
    python -m app.scanner.pipeline.validate_artist b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d --missing-only

    # Fetch specific data types
    python -m app.scanner.pipeline.validate_artist b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d --metadata --artwork --bio
"""

import asyncio
import argparse
import json
import httpx
from typing import Dict, Any
from app.scanner.pipeline import (
    ArtistState,
    ScanOptions,
    EnrichmentContext,
    EnrichmentPlanner,
    PipelineExecutor,
)
from app.db import init_db, close_db


async def load_artist_from_db(mbid: str) -> Dict[str, Any]:
    """Load artist data from database."""
    from app.db import get_db
    
    async for conn in get_db():
        # Fetch artist with all metadata
        row = await conn.fetchrow(
            """
            SELECT 
                a.mbid,
                a.name,
                a.sort_name,
                a.bio,
                a.image_url,
                a.image_source,
                a.artwork_id,
                EXISTS(SELECT 1 FROM top_track tt WHERE tt.artist_mbid = a.mbid AND tt.type = 'top') AS has_top_tracks,
                EXISTS(SELECT 1 FROM top_track tt WHERE tt.artist_mbid = a.mbid AND tt.type = 'single') AS has_singles,
                EXISTS(SELECT 1 FROM similar_artist sa WHERE sa.artist_mbid = a.mbid) AS has_similar,
                EXISTS(SELECT 1 FROM artist_album aa WHERE aa.artist_mbid = a.mbid AND aa.type = 'primary') AS has_primary_album
            FROM artist a
            WHERE a.mbid = $1
            """,
            mbid
        )
        
        # If artist not in DB, create minimal state from scratch
        if not row:
            print(f"⚠️  Artist {mbid} not found in database")
            print("   Creating minimal state (no existing data)")
            return {
                'mbid': mbid,
                'name': None,
                'sort_name': None,
                'bio': None,
                'image_url': None,
                'image_source': None,
                'artwork_id': None,
                'has_top_tracks': False,
                'has_singles': False,
                'has_similar': False,
                'has_primary_album': False,
                'external_links': {},  # Empty dict, not list
                'local_release_groups': set()
            }
        
        artist_dict = dict(row)
        
        # Fetch external links and build dict
        links = await conn.fetch(
            "SELECT type, url FROM external_link WHERE entity_id = $1 AND entity_type = 'artist'",
            mbid
        )
        
        # Build all_links dict for ArtistState (from_db_row expects 'all_links' not 'external_links')
        all_links_dict = {}
        for link in links:
            all_links_dict[link['type']] = link['url']
            artist_dict[f"{link['type']}_url"] = link['url']
        
        artist_dict['all_links'] = all_links_dict
        
        # Fetch local release groups (need release_group_mbid, not album_mbid)
        release_groups = await conn.fetch(
            """
            SELECT DISTINCT a.release_group_mbid
            FROM artist_album aa
            JOIN album a ON aa.album_mbid = a.mbid
            WHERE aa.artist_mbid = $1 AND a.release_group_mbid IS NOT NULL
            """,
            mbid
        )
        
        artist_dict['local_release_groups'] = {rg['release_group_mbid'] for rg in release_groups}
        
        return artist_dict


async def validate_artist(mbid: str, options: ScanOptions) -> None:
    """
    Validate pipeline for a specific artist.
    
    This runs the full enrichment pipeline and shows what data
    would be saved, without actually modifying the database.
    """
    
    print(f"\n{'='*80}")
    print(f"Pipeline Validation for Artist: {mbid}")
    print(f"{'='*80}\n")
    
    # Initialize database
    await init_db()
    
    try:
        # Load artist from database
        print("📥 Loading artist from database...")
        artist_dict = await load_artist_from_db(mbid)
        
        local_release_groups = artist_dict.pop('local_release_groups', set())
        artist = ArtistState.from_db_row(artist_dict)
        
        # Display artist info
        if artist.name:
            print(f"✅ Loaded: {artist.name}")
        else:
            print(f"✅ Created from scratch (MBID: {mbid})")
        print(f"   Bio: {'✓' if artist.has_bio else '✗'}")
        artwork_status = '✓' if artist.has_artwork else '✗'
        artwork_source = f" (source: {artist.image_source})" if artist.has_artwork and artist.image_source else ""
        print(f"   Artwork: {artwork_status}{artwork_source}")
        print(f"   Top Tracks: {'✓' if artist.has_top_tracks else '✗'}")
        print(f"   Singles: {'✓' if artist.has_singles else '✗'}")
        print(f"   Similar Artists: {'✓' if artist.has_similar else '✗'}")
        print(f"   External Links: {len(artist.external_links)}")
        if artist.external_links:
            print(f"   Link types: {', '.join(sorted(artist.external_links.keys()))}")
        print(f"   Local Albums: {len(local_release_groups)}")
        
        # Create HTTP client
        print("\n🔄 Creating enrichment plan...")
        async with httpx.AsyncClient(timeout=30.0) as client:
            
            # Create context
            context = EnrichmentContext(
                artist=artist,
                options=options,
                client=client,
                local_release_groups=local_release_groups
            )
            
            # Create plan
            planner = EnrichmentPlanner()
            plan = planner.create_plan(artist, options, local_release_groups)
            
            print(f"✅ Plan created: {plan.stage_count} stages")
            for stage in plan.stages:
                deps = stage.dependencies()
                deps_str = f" (depends on: {', '.join(deps)})" if deps else ""
                print(f"   • {stage.name}{deps_str}")
            
            if plan.stage_count == 0:
                print("\n⚠️  No stages to execute (all data already present or no options enabled)")
                return
            
            # Execute plan
            print("\n🚀 Executing pipeline...")
            executor = PipelineExecutor()
            result = await executor.execute(plan, context)
            
            # Show results
            print(f"\n{'='*80}")
            print("Execution Results")
            print(f"{'='*80}\n")
            
            print(f"✅ Success: {result.success_count}")
            print(f"❌ Errors: {result.error_count}")
            print(f"⏭️  Skipped: {result.skip_count}")
            print(f"📞 Total API Calls: {result.total_api_calls}")
            
            # Show individual stage results
            print("\n📊 Stage Results:")
            for stage_name, stage_result in result.results.items():
                if stage_result.success:
                    icon = "✅"
                    status = "SUCCESS"
                elif stage_result.skipped:
                    icon = "⏭️ "
                    status = f"SKIPPED ({stage_result.skip_reason})"
                else:
                    icon = "❌"
                    error_msg = stage_result.error or "Unknown error"
                    status = f"ERROR ({error_msg})"
                
                metrics_str = ", ".join(f"{k}={v}" for k, v in stage_result.metrics.items())
                print(f"   {icon} {stage_name}: {status}")
                if metrics_str:
                    print(f"      Metrics: {metrics_str}")
            
            # Show data that would be saved
            merged = result.merge_data()
            
            if merged:
                print(f"\n{'='*80}")
                print("Data to Save (would be written to database)")
                print(f"{'='*80}\n")
                
                for key, value in sorted(merged.items()):
                    if isinstance(value, str):
                        if len(value) > 100:
                            print(f"   {key}: {value[:100]}... ({len(value)} chars)")
                        else:
                            print(f"   {key}: {value}")
                    elif isinstance(value, list):
                        print(f"   {key}: [{len(value)} items]")
                        if value and len(value) <= 5:
                            for i, item in enumerate(value, 1):
                                if isinstance(item, dict):
                                    name = item.get('name') or item.get('title') or str(item)[:50]
                                    print(f"      {i}. {name}")
                                else:
                                    print(f"      {i}. {item}")
                    elif isinstance(value, dict):
                        print(f"   {key}: {json.dumps(value, indent=6)}")
                    else:
                        print(f"   {key}: {value}")
            else:
                print("\n⚠️  No data to save")
    
    finally:
        await close_db()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate pipeline for a specific artist",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Enrich The Beatles with all options
  python -m app.scanner.pipeline.validate_artist b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d --all

  # Fetch only missing metadata
  python -m app.scanner.pipeline.validate_artist b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d --missing-only

  # Fetch specific data types
  python -m app.scanner.pipeline.validate_artist b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d --metadata --artwork --bio
  
  # Production mode: auto-fetch dependencies (bio needs metadata for Wikipedia URL)
  python -m app.scanner.pipeline.validate_artist b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d --bio --prod-scan
        """
    )
    
    parser.add_argument("mbid", help="Artist MBID to validate")
    
    # Option groups
    parser.add_argument("--all", action="store_true", help="Enable all enrichment options")
    parser.add_argument("--missing-only", action="store_true", help="Only fetch missing data")
    parser.add_argument("--prod-scan", action="store_true", help="Production mode: auto-fetch dependencies when needed")
    
    # Individual options
    parser.add_argument("--metadata", action="store_true", help="Fetch core metadata and links")
    parser.add_argument("--artwork", action="store_true", help="Fetch artwork")
    parser.add_argument("--bio", action="store_true", help="Fetch biography")
    parser.add_argument("--top-tracks", action="store_true", help="Fetch top tracks")
    parser.add_argument("--similar", action="store_true", help="Fetch similar artists")
    parser.add_argument("--singles", action="store_true", help="Fetch singles")
    parser.add_argument("--albums", action="store_true", help="Fetch album metadata")
    
    args = parser.parse_args()
    
    # Build options
    if args.all:
        options = ScanOptions(
            fetch_metadata=True,
            fetch_artwork=True,
            fetch_spotify_artwork=True,
            fetch_bio=True,
            fetch_top_tracks=True,
            fetch_similar_artists=True,
            fetch_singles=True,
            fetch_album_metadata=True,
            missing_only=args.missing_only,
        )
    else:
        # Start with user-specified options
        fetch_metadata = args.metadata
        fetch_artwork = args.artwork
        fetch_bio = args.bio
        
        # In prod-scan mode, auto-enable dependencies
        if args.prod_scan:
            # If requesting bio or artwork, need metadata for links
            if args.bio or args.artwork:
                fetch_metadata = True
        
        options = ScanOptions(
            fetch_metadata=fetch_metadata,
            fetch_artwork=fetch_artwork,
            fetch_spotify_artwork=fetch_artwork,
            fetch_bio=fetch_bio,
            fetch_top_tracks=args.top_tracks,
            fetch_similar_artists=args.similar,
            fetch_singles=args.singles,
            fetch_album_metadata=args.albums,
            missing_only=args.missing_only,
        )
    
    # Run validation
    asyncio.run(validate_artist(args.mbid, options))


if __name__ == "__main__":
    main()
