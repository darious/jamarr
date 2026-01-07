"""
Pipeline Adapter - Bridge between old coordinator interface and new v3 pipeline.

This adapter allows the new pipeline to be used as a drop-in replacement
for the old MetadataCoordinator without changing scan_manager.py.
"""

import asyncio
import logging
from typing import Optional, Callable
from app.db import get_pool
from app.scanner.pipeline import (
    ArtistState,
    ScanOptions,
    EnrichmentPlanner,
    PipelineExecutor,
    EnrichmentContext,
)
from app.scanner.core import get_shared_client
from app.scanner.stats import get_api_tracker

logger = logging.getLogger("scanner.pipeline.adapter")


class PipelineAdapter:
    """
    Adapter to use v3 pipeline with existing scan_manager.
    
    Matches the old MetadataCoordinator interface for seamless integration.
    """
    
    def __init__(self, progress_cb: Optional[Callable] = None):
        """
        Initialize adapter.
        
        Args:
            progress_cb: Optional callback(current, total, message) for progress updates
        """
        self.progress_cb = progress_cb
        self.pool = get_pool()
        self.pipeline_results = []  # Store PipelineResult objects for metric aggregation
    
    async def update_metadata(
        self,
        artists: list,
        options: dict,
        local_release_group_ids_map: dict = None
    ):
        """
        Main entry point for batch metadata update.
        
        Args:
            artists: List of artist dicts from DB
            options: Dict of flags (fetch_metadata, fetch_artwork, etc.)
            local_release_group_ids_map: Pre-fetched release group IDs per artist
        """
        if not artists:
            return
        
        logger.info(f"Starting v3 pipeline for {len(artists)} artists...")
        
        # Pre-fetch release groups if needed and not provided
        if local_release_group_ids_map is None:
            local_release_group_ids_map = {}
            if options.get("fetch_album_metadata", False):
                mbids = [a["mbid"] for a in artists if a.get("mbid")]
                if mbids:
                    try:
                        async with self.pool.acquire() as db:
                            rows = await db.fetch(
                                """
                                SELECT aa.artist_mbid, array_agg(DISTINCT al.release_group_mbid) as rgs
                                FROM artist_album aa
                                JOIN album al ON aa.album_mbid = al.mbid
                                WHERE aa.artist_mbid = ANY($1::text[])
                                GROUP BY aa.artist_mbid
                                """,
                                mbids
                            )
                            for r in rows:
                                local_release_group_ids_map[r["artist_mbid"]] = set(r["rgs"])
                    except Exception as e:
                        logger.error(f"Failed to fetch local RGs: {e}")
        
        total_artists = len(artists)
        processed_count = 0
        results = []
        self.pipeline_results = []  # Reset for this batch
        
        # Process artists with concurrency control
        fetch_workers = min(total_artists, 5) or 1
        writer_workers = 2
        fetch_semaphore = asyncio.Semaphore(fetch_workers)
        queue: asyncio.Queue = asyncio.Queue()
        progress_lock = asyncio.Lock()
        
        async def fetch_artist(artist, client):
            """Fetch enrichment data for one artist."""
            mbid = artist.get("mbid")
            if not mbid:
                return
            
            local_rgs = local_release_group_ids_map.get(mbid, set())
            
            async with fetch_semaphore:
                try:
                    payload = await self.process_artist(
                        artist,
                        options,
                        local_rgs,
                        fetch_only=True,
                        client=client
                    )
                except Exception as e:
                    logger.error(f"[{mbid}] Error in process_artist: {type(e).__name__}: {e}", exc_info=True)
                    payload = e
                
                await queue.put((artist, payload))
                
                async with progress_lock:
                    nonlocal processed_count
                    processed_count += 1
                    if self.progress_cb:
                        self.progress_cb(
                            processed_count,
                            total_artists,
                            f"Metadata: {artist.get('name') or artist.get('mbid')}",
                        )
        
        async def writer():
            """Write enrichment results to database."""
            while True:
                item = await queue.get()
                if item is None:
                    queue.task_done()
                    break
                
                artist, payload = item
                mbid = artist.get("mbid", "unknown")
                
                # Debug logging
                logger.debug(f"[{mbid}] Writer received payload type: {type(payload).__name__}")
                
                if isinstance(payload, Exception) or payload is None or payload is True:
                    logger.warning(f"[{mbid}] Skipping save - payload is {type(payload).__name__}")
                    results.append(payload if isinstance(payload, Exception) else True)
                    queue.task_done()
                    continue
                
                updates, art_res = payload
                
                # Skip save if no updates and no artwork
                if not updates and not art_res:
                    logger.debug(f"[{mbid}] Skipping save - no updates")
                    results.append(True)
                    queue.task_done()
                    continue
                
                logger.info(f"[{mbid}] Saving to DB - {len(updates)} update keys, artwork={bool(art_res)}")
                
                try:
                    async with self.pool.acquire() as db:
                        await self.save_artist_metadata(db, mbid, updates, art_res)
                        get_api_tracker().track_processed("artists", mbid)
                        get_api_tracker().track_processed("artists_metadata", mbid)
                    results.append(True)
                    logger.info(f"[{mbid}] Save successful")
                    
                    # Report metrics incrementally
                    self._report_stage_metrics(artists, results)
                except Exception as e:
                    logger.error(f"[{mbid}] DB Save Error: {e}", exc_info=True)
                    results.append(e)
                
                queue.task_done()
        
        # Start writer tasks
        writer_tasks = [asyncio.create_task(writer()) for _ in range(writer_workers)]
        
        # Start fetch tasks with shared client
        client = get_shared_client()
        fetch_tasks = [
            asyncio.create_task(fetch_artist(a, client))
            for a in artists if a.get("mbid")
        ]
        
        if fetch_tasks:
            await asyncio.gather(*fetch_tasks)
        
        # Signal writers to shut down
        for _ in writer_tasks:
            await queue.put(None)
        
        # Wait for queue to drain
        if fetch_tasks:
            await queue.join()
        
        # Wait for writers to finish
        await asyncio.gather(*writer_tasks)
        
        # Aggregate and report metrics
        self._report_stage_metrics(artists, results)
        
        # Log results
        success_count = sum(1 for res in results if res is True)
        logger.info(f"V3 pipeline complete. Updated {success_count}/{len(artists)} artists.")
    
    def _report_stage_metrics(self, artists: list, results: list):
        """
        Analyze missing data and aggregate stage metrics to report to stats tracker.
        
        Args:
            artists: List of artist dicts that were processed
            results: List of results from processing (True, Exception, or None)
        """
        # Stage name mapping (stage key -> display name)
        stage_names = {
            "core_metadata": "MusicBrainz Core",
            "external_links": "External Links",
            "artwork": "Fanart",
            "wikipedia_bio": "Bio",
            "top_tracks": "Top Tracks",
            "similar_artists": "Similar Artists",
            "singles": "Singles",
            "album_metadata": "Album Metadata",
        }
        
        # Pre-scan: Count how many artists are missing each type of data
        missing_counts = {
            "MusicBrainz Core": 0,
            "External Links": 0,
            "Fanart": 0,
            "Bio": 0,
            "Top Tracks": 0,
            "Similar Artists": 0,
            "Singles": 0,
            "Album Metadata": 0,
        }
        
        for artist in artists:
            # Core metadata: missing if no name
            if not artist.get("name"):
                missing_counts["MusicBrainz Core"] += 1
            
            # External links: missing if not all link types present
            all_links = artist.get("all_links", {})
            required_links = ["homepage", "spotify", "wikipedia", "qobuz", "tidal", "lastfm", "discogs"]
            if not all(all_links.get(link) for link in required_links):
                missing_counts["External Links"] += 1
            
            # Artwork: missing if no image_url
            if not artist.get("image_url"):
                missing_counts["Fanart"] += 1
            
            # Bio: missing if no bio
            if not artist.get("bio"):
                missing_counts["Bio"] += 1
            
            # Top tracks: missing if flag says so
            if not artist.get("has_top_tracks"):
                missing_counts["Top Tracks"] += 1
            
            # Similar artists: missing if flag says so
            if not artist.get("has_similar"):
                missing_counts["Similar Artists"] += 1
            
            # Singles: missing if flag says so
            if not artist.get("has_singles"):
                missing_counts["Singles"] += 1
            
            # Album metadata: always consider as potentially missing
            # (we don't have a good pre-check for this)
            if artist.get("has_primary_album"):
                missing_counts["Album Metadata"] += 1
        
        # Post-execution: Aggregate metrics from stage results
        stage_metrics = {
            "MusicBrainz Core": {"searched": 0, "hits": 0},
            "External Links": {"searched": 0, "hits": 0},
            "Fanart": {"searched": 0, "hits": 0},
            "Bio": {"searched": 0, "hits": 0},
            "Top Tracks": {"searched": 0, "hits": 0},
            "Similar Artists": {"searched": 0, "hits": 0},
            "Singles": {"searched": 0, "hits": 0},
            "Album Metadata": {"searched": 0, "hits": 0},
        }
        
        # Aggregate from all pipeline results
        for pipeline_result in self.pipeline_results:
            for stage_key, stage_result in pipeline_result.results.items():
                display_name = stage_names.get(stage_key)
                if not display_name or display_name not in stage_metrics:
                    continue
                
                metrics = stage_result.metrics or {}
                stage_metrics[display_name]["searched"] += metrics.get("searched", 0)
                if metrics.get("found"):
                    stage_metrics[display_name]["hits"] += 1
        
        # Report to stats tracker
        for display_name in stage_metrics.keys():
            missing = missing_counts.get(display_name, 0)
            searched = stage_metrics[display_name]["searched"]
            hits = stage_metrics[display_name]["hits"]
            
            get_api_tracker().track_stage_metrics(
                stage=display_name,
                missing=missing,
                searched=searched,
                hits=hits
            )
    
    async def process_artist(
        self,
        artist: dict,
        options: dict,
        local_release_group_ids: set,
        fetch_only: bool = False,
        client = None
    ):
        """
        Process a single artist using the v3 pipeline.
        
        Args:
            artist: Artist dict from DB
            options: Enrichment options
            local_release_group_ids: Set of release group MBIDs for this artist
            fetch_only: If True, return data without saving to DB
            client: Optional HTTP client to reuse
            
        Returns:
            If fetch_only: (updates_dict, artwork_result) tuple
            Otherwise: True on success
        """
        mbid = artist["mbid"]
        
        # Convert old options dict to ScanOptions
        scan_options = ScanOptions(
            fetch_metadata=options.get("fetch_metadata", False) or options.get("fetch_base_metadata", False),
            fetch_artwork=options.get("fetch_artwork", False),
            fetch_spotify_artwork=options.get("fetch_spotify_artwork", False),
            fetch_bio=options.get("fetch_bio", False),
            fetch_top_tracks=options.get("fetch_top_tracks", False) or options.get("refresh_top_tracks", False),
            fetch_similar_artists=options.get("fetch_similar_artists", False) or options.get("refresh_similar_artists", False),
            fetch_singles=options.get("fetch_singles", False) or options.get("refresh_singles", False),
            fetch_album_metadata=options.get("fetch_album_metadata", False),
            missing_only=options.get("missing_only", False),
            links_only=options.get("links_only", False),
        )
        
        # Convert artist dict to ArtistState
        artist_state = ArtistState.from_db_row(artist)
        
        # Create enrichment context
        context = EnrichmentContext(
            artist=artist_state,
            options=scan_options,
            client=client or get_shared_client(),
            local_release_groups=local_release_group_ids
        )
        
        # Create plan and execute
        planner = EnrichmentPlanner()
        plan = planner.create_plan(artist_state, scan_options, local_release_group_ids)
        
        logger.info(f"[{mbid}] Processing '{artist_state.name or mbid}' - {len(plan.stages)} stages planned")
        if plan.stages:
            stage_names = [s.name for s in plan.stages]
            logger.info(f"[{mbid}] Stages: {', '.join(stage_names)}")
        
        executor = PipelineExecutor()
        result = await executor.execute(plan, context)
        
        # Log results
        success_count = sum(1 for r in result.results.values() if r.success)
        skip_count = sum(1 for r in result.results.values() if r.skipped)
        error_count = sum(1 for r in result.results.values() if not r.success and not r.skipped)
        
        logger.info(
            f"[{mbid}] Complete - Success: {success_count}, Skipped: {skip_count}, Errors: {error_count}, "
            f"API calls: {result.total_api_calls}"
        )
        
        # Store result for metric aggregation
        self.pipeline_results.append(result)
        
        # Convert pipeline result to old format
        updates = self._convert_result_to_updates(result)
        art_res = self._extract_artwork_result(result)
        
        if fetch_only:
            return (updates, art_res)
        
        # Save to database
        async with self.pool.acquire() as db:
            await self.save_artist_metadata(db, mbid, updates, art_res)
        
        return True
    
    def _convert_result_to_updates(self, result) -> dict:
        """Convert PipelineResult to old updates dict format."""
        updates = {}
        
        # Extract data from all stages
        for stage_name, stage_result in result.results.items():
            if not stage_result.success or not stage_result.data:
                continue
            
            # Merge stage data into updates
            updates.update(stage_result.data)
        
        return updates
    
    def _extract_artwork_result(self, result) -> Optional[dict]:
        """Extract artwork result from pipeline result."""
        artwork_result = result.results.get("artwork")
        if artwork_result and artwork_result.success and artwork_result.data:
            return artwork_result.data
        return None
    
    async def save_artist_metadata(self, db, mbid: str, updates: dict, art_res: Optional[dict]):
        """
        Save enrichment results to database.
        
        This matches the old coordinator's save logic.
        """
        from app.scanner.artwork import upsert_artwork_record, upsert_image_mapping
        
        try:
            async with db.transaction():
                # Upsert Artwork (thumb + background)
                artwork_id = None
                background_id = None
                if art_res:
                    # Normalize shape: allow dict with thumb/background or single art dict
                    if isinstance(art_res, dict):
                        thumb_res = art_res.get("thumb")
                        bg_res = art_res.get("background")
                    else:
                        thumb_res = art_res
                        bg_res = None

                    if thumb_res:
                        try:
                            artwork_id = await upsert_artwork_record(
                                db,
                                thumb_res.get("sha1"),
                                meta=thumb_res.get("meta"),
                                source=updates.get("image_source"),
                                source_url=updates.get("image_url")
                            )
                            if artwork_id:
                                await upsert_image_mapping(db, artwork_id, "artist", mbid, "artistthumb")
                                updates["artwork_id"] = artwork_id
                        except Exception as e:
                            logger.error(f"Artwork Save Error (thumb): {e}")

                    if bg_res:
                        try:
                            background_id = await upsert_artwork_record(
                                db,
                                bg_res.get("sha1"),
                                meta=bg_res.get("meta"),
                                source=updates.get("image_source"),
                                source_url=updates.get("background_url")
                            )
                            if background_id:
                                await upsert_image_mapping(db, background_id, "artist", mbid, "artistbackground")
                        except Exception as e:
                            logger.error(f"Artwork Save Error (background): {e}")

                # 1. Update Artist Table
                cols = []
                vals = []
                i = 1
                
                for key in ["name", "sort_name", "bio", "image_url", "artwork_id"]:
                    if key in updates and updates[key] is not None:
                        cols.append(f"{key} = ${i}")
                        vals.append(updates[key])
                        i += 1
                
                # Always update timestamp
                cols.append("updated_at = NOW()")
                        
                if cols:
                    vals.append(mbid)
                    await db.execute(
                        f"UPDATE artist SET {', '.join(cols)} WHERE mbid = ${i}",
                        *vals
                    )
                
                # 2. External Links
                links = []
                for k in ["spotify_url", "tidal_url", "qobuz_url", "lastfm_url", "discogs_url", "homepage", "musicbrainz_url", "wikipedia_url", "wikidata_url"]:
                    if updates.get(k):
                        l_type = k.replace("_url", "")
                        links.append((l_type, updates[k]))
                        
                for l_type, url in links:
                    # Normalize Qobuz URLs
                    if l_type == "qobuz" and "play.qobuz.com" not in url:
                        import re
                        # Extract ID from end of URL
                        match = re.search(r'(\d+)$', url)
                        if match:
                            url = f"https://play.qobuz.com/artist/{match.group(1)}"
                        else:
                            # Skip saving malformed Qobuz link
                            continue

                    await db.execute("""
                        INSERT INTO external_link (entity_type, entity_id, type, url)
                        VALUES ('artist', $1, $2, $3)
                        ON CONFLICT (entity_type, entity_id, type) DO UPDATE SET url = EXCLUDED.url
                    """, mbid, l_type, url)

                # 3. Top Tracks (Replace all for this type)
                if "top_tracks" in updates:
                    await db.execute("DELETE FROM top_track WHERE artist_mbid = $1 AND type = 'top'", mbid)
                    for t in updates["top_tracks"]:
                        await db.execute("""
                            INSERT INTO top_track (artist_mbid, type, external_name, rank, popularity, external_mbid)
                            VALUES ($1, 'top', $2, $3, $4, $5)
                        """, mbid, t["name"], int(t["rank"]), int(t["popularity"]), t["mbid"])

                # 4. Singles (MusicBrainz singles go into top_track with type='single')
                if "singles" in updates:
                    await db.execute("DELETE FROM top_track WHERE artist_mbid = $1 AND type = 'single'", mbid)
                    
                    for i, s in enumerate(updates["singles"], start=1):
                        await db.execute("""
                            INSERT INTO top_track (artist_mbid, type, external_name, external_album, external_date, external_mbid, rank)
                            VALUES ($1, 'single', $2, $3, $4, $5, $6)
                            ON CONFLICT (artist_mbid, type, external_mbid) DO NOTHING
                        """, mbid, s["title"], s.get("album"), s.get("date"), s["mbid"], i)
                        
                # 5. Similar Artists
                if "similar_artists" in updates:
                    await db.execute("DELETE FROM similar_artist WHERE artist_mbid = $1", mbid)
                    for i, s in enumerate(updates["similar_artists"], start=1):
                        await db.execute("""
                            INSERT INTO similar_artist (artist_mbid, similar_artist_name, similar_artist_mbid, rank)
                            VALUES ($1, $2, $3, $4)
                        """, mbid, s["name"], s["mbid"], i)

                # 6. Genres
                if "genres" in updates:
                    await db.execute("DELETE FROM artist_genre WHERE artist_mbid = $1", mbid)
                    for g in updates["genres"]:
                        await db.execute("""
                            INSERT INTO artist_genre (artist_mbid, genre, count)
                            VALUES ($1, $2, $3)
                        """, mbid, g["name"], g["count"])

                # 7. Album Metadata
                if "albums_metadata" in updates:
                    for rg_id, meta in updates["albums_metadata"].items():
                        # Update Album table
                        upd_cols = ["updated_at = NOW()"]
                        upd_vals = []
                        
                        if meta.get("description"):
                            upd_vals.append(meta["description"])
                            upd_cols.append(f"description = ${len(upd_vals)}")
                            
                        if meta.get("peak_chart_position"):
                            upd_vals.append(meta["peak_chart_position"])
                            upd_cols.append(f"peak_chart_position = ${len(upd_vals)}")
                            
                        if upd_vals:
                            # We only update existing albums
                            upd_vals.append(rg_id)
                            # Update ALL albums in this Release Group
                            await db.execute(
                                f"UPDATE album SET {', '.join(upd_cols)} WHERE release_group_mbid = ${len(upd_vals)}",
                                *upd_vals
                            )
                            
                        # Update Album Links
                        if meta.get("external_links"):
                            for l_type, url in meta["external_links"]:
                                await db.execute("""
                                    INSERT INTO external_link (entity_type, entity_id, type, url)
                                    VALUES ('album', $1, $2, $3)
                                    ON CONFLICT (entity_type, entity_id, type) DO UPDATE SET url = EXCLUDED.url
                                """, rg_id, l_type, url)

        except Exception as e:
            logger.error(f"DB Save Error for {mbid}: {e}")
            raise
