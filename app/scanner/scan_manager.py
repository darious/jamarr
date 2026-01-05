import asyncio
import logging
import time
import os
from typing import Optional, Dict, Any
from app.scanner.core import Scanner, close_shared_client, warm_dns_cache
from app.scanner.services.coordinator import MetadataCoordinator
from app.config import get_music_path
from app.scanner.stats import get_api_tracker
from app.db import get_db

logger = logging.getLogger("scanner.manager")

class ScanManager:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = ScanManager()
        return cls._instance

    def __init__(self):
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._current_task: Optional[asyncio.Task] = None
        self._status = "Idle"
        self._stats = {}
        self._event_queues = set()
        self.scanner = Scanner()
        self._phase: Optional[str] = None
        self._music_path = get_music_path()
        self._configure_logging()

    def _configure_logging(self):
        scan_logger = logging.getLogger("scanner")
        if not any(getattr(h, "_ui_broadcast", False) for h in scan_logger.handlers):
            bh = self.BroadcastLogHandler(self)
            bh._ui_broadcast = True
            bh.setLevel(logging.INFO) 
            scan_logger.addHandler(bh)

    class BroadcastLogHandler(logging.Handler):
        def __init__(self, manager):
            super().__init__()
            self.manager = manager
        def emit(self, record):
            try:
                msg = self.format(record)
                self.manager._log_message(msg)
            except Exception:
                self.handleError(record)

    def get_music_path(self) -> str:
        return self._music_path

    async def subscribe(self):
        queue = asyncio.Queue()
        self._event_queues.add(queue)
        try:
            yield {"type": "status", "status": self._status, "stats": self._stats}
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            self._event_queues.remove(queue)

    async def shutdown(self):
        await self.stop_scan()
        for queue in self._event_queues:
            queue.put_nowait(None)
        await close_shared_client()

    def _broadcast(self, event: Dict[str, Any]):
        for queue in self._event_queues:
            queue.put_nowait(event)

    class ManagerLogger:
        def __init__(self, manager):
            self.manager = manager
        def emit_progress(self, current, total, message):
            self.manager._update_progress(current, total, message)

    def _update_progress(self, current, total, message):
        self._status = "Running"
        percentage = (current / total * 100) if total > 0 else 0
        self._stats = {
            "scanned": current,
            "total": total,
            "percentage": percentage,
            "message": message,
            "phase": self._phase,
            "api_stats": get_api_tracker().get_stats(),
            "processed_stats": get_api_tracker().get_processed_stats(),
            "detailed_stats": get_api_tracker().get_detailed_stats(),
        }
        self._broadcast({
            "type": "progress",
            "current": current,
            "total": total,
            "percentage": percentage,
            "message": message,
            "phase": self._phase,
            "api_stats": self._stats["api_stats"],
            "processed_stats": self._stats["processed_stats"],
            "detailed_stats": self._stats["detailed_stats"],
        })

    def _log_message(self, message):
        self._broadcast({"type": "log", "message": message, "timestamp": time.time()})

    async def start_scan(self, path: str = None, force: bool = False):
        async with self._lock:
            if self._current_task and not self._current_task.done():
                raise RuntimeError("Scan already in progress")

            self._stop_event.clear()
            self._status = "Starting Scan..."
            self._phase = "filesystem"
            get_api_tracker().reset()
            self.scanner.scan_logger = self.ManagerLogger(self)
            self._current_task = asyncio.create_task(self._run_scan(path, force))
            return self._current_task

    async def _run_scan(self, path, force):
        try:
            self._broadcast({"type": "start", "mode": "filesystem", "phase": self._phase})
            self._log_message(f"Starting filesystem scan. Force: {force}")
            self.scanner._stop_event = self._stop_event
            await self.scanner.scan_filesystem(root_path=path, force_rescan=force)
            self._status = "Idle"
            self._broadcast({"type": "complete", "status": "success", "phase": self._phase})
            self._log_message("Scan complete.")
        except asyncio.CancelledError:
            self._status = "Idle"
            self._broadcast({"type": "complete", "status": "cancelled", "phase": self._phase})
            self._log_message("Scan cancelled.")
        except Exception as e:
            logger.exception("Scan failed")
            self._status = "Idle"
            self._broadcast({"type": "complete", "status": "error", "error": str(e), "phase": self._phase})
            self._log_message(f"Scan failed: {e}")
        finally:
            self._current_task = None
            self._phase = None

    async def start_metadata_update(self, **kwargs):
        async with self._lock:
            if self._current_task and not self._current_task.done():
                raise RuntimeError("Scan already in progress")
            self._stop_event.clear()
            self._status = "Starting Metadata Update..."
            self._phase = "metadata"
            get_api_tracker().reset()
            self.scanner.scan_logger = self.ManagerLogger(self)
            self._current_task = asyncio.create_task(self._run_metadata(**kwargs))
            return self._current_task

    async def _run_metadata(self, artist_filter=None, mbid_filter=None, missing_only=False, path=None, **options):
        try:
            self._broadcast({"type": "start", "mode": "metadata", "phase": self._phase})
            self._log_message(f"Starting metadata update. Filter: {artist_filter or mbid_filter or 'All'}")
            
            async for db in get_db():
                coordinator = MetadataCoordinator(progress_cb=self._update_progress)

                # Scope to path if provided
                path_mbids = None
                if path:
                    path_mbids = await self.scanner.get_artists_in_path(path)
                    if path_mbids is None:
                        path_mbids = set()
                    if not path_mbids:
                        self._log_message(f"No artists found in path: {path}")
                        break

                # Fetch Artists
                artists = await self._fetch_artists_for_update(db, artist_filter, mbid_filter, path_mbids)
                self._log_message(f"Found {len(artists)} artists to process.")

                # Warm DNS cache before metadata operations to prevent DNS errors
                await warm_dns_cache()
                
                # Run Update
                run_opts = options.copy()
                run_opts["missing_only"] = missing_only

                await coordinator.update_metadata(artists, run_opts)
                
                # After fetching top tracks/singles, try to match them to local tracks
                if options.get("refresh_top_tracks") or options.get("refresh_singles"):
                    artist_mbids = [a["mbid"] for a in artists if a.get("mbid")]
                    if artist_mbids:
                        await self._rematch_tracks(db, artist_mbids)
                
            self._status = "Idle"
            self._broadcast({"type": "complete", "status": "success", "phase": self._phase})
            self._log_message("Metadata update complete.")
        except asyncio.CancelledError:
            self._status = "Idle"
            self._broadcast({"type": "complete", "status": "cancelled", "phase": self._phase})
            self._log_message("Metadata update cancelled.")
        except Exception as e:
            logger.exception("Metadata update failed")
            self._status = "Idle"
            self._broadcast({"type": "complete", "status": "error", "error": str(e), "phase": self._phase})
        finally:
            self._current_task = None
            self._phase = None

    async def _fetch_artists_for_update(self, db, artist_filter, mbid_filter, path_mbids=None):
        query = """
            SELECT 
                a.mbid, 
                a.name, 
                a.bio, 
                a.image_url, 
                a.image_source,
                -- Presence flags for missing-only logic
                EXISTS(SELECT 1 FROM top_track tt WHERE tt.artist_mbid = a.mbid AND tt.type = 'top') AS has_top_tracks,
                EXISTS(SELECT 1 FROM top_track tt WHERE tt.artist_mbid = a.mbid AND tt.type = 'single') AS has_singles,
                EXISTS(SELECT 1 FROM similar_artist sa WHERE sa.artist_mbid = a.mbid) AS has_similar,
                EXISTS(SELECT 1 FROM artist_album aa WHERE aa.artist_mbid = a.mbid AND aa.type = 'primary') AS has_primary_album,
                json_object_agg(el.type, el.url) FILTER (WHERE el.type IS NOT NULL) AS external_links
            FROM artist a
            LEFT JOIN external_link el ON el.entity_id = a.mbid AND el.entity_type = 'artist'
        """
        params = []
        clauses = []
        
        if path_mbids is not None:
            if not path_mbids:
                return []
            clauses.append(f"mbid = ANY(${len(params)+1}::text[])")
            params.append(list(path_mbids))
        
        if mbid_filter:
            if isinstance(mbid_filter, (list, set, tuple)):
                f = [m for m in mbid_filter if m]
                if f:
                    clauses.append(f"mbid = ANY(${len(params)+1}::text[])")
                    params.append(f)
            else:
                clauses.append(f"mbid = ${len(params)+1}")
                params.append(mbid_filter)
        elif artist_filter:
            clauses.append(f"name ILIKE ${len(params)+1}")
            params.append(f"%{artist_filter}%")
            
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        
        query += " GROUP BY a.mbid"
            
        rows = await db.fetch(query, *params)
        artists = []
        for r in rows:
            d = dict(r)
            # Flatten links
            links = d.pop("external_links", None)
            if links:
                try:
                     import json
                     links_dict = json.loads(links) if isinstance(links, str) else links
                     # Map external_links JSON to flat keys for coordinator
                     d["spotify_url"] = links_dict.get("spotify")
                     d["homepage"] = links_dict.get("homepage")
                     d["wikipedia_url"] = links_dict.get("wikipedia")
                     d["wikidata_url"] = links_dict.get("wikidata")
                     d["qobuz_url"] = links_dict.get("qobuz")
                     d["tidal_url"] = links_dict.get("tidal")
                     d["lastfm_url"] = links_dict.get("lastfm")
                     d["discogs_url"] = links_dict.get("discogs")
                     
                     d["all_links"] = links_dict
                except Exception:
                     pass
            artists.append(d)

        # Sort order:
        # 1) primary album link first
        # 2) has name first
        # 3) name alphabetically
        # 4) mbid
        artists.sort(
            key=lambda r: (
                -int(bool(r.get("has_primary_album"))),
                -int(bool(r.get("name"))),
                (r.get("name") or "").lower(),
                r.get("mbid") or "",
            )
        )
        return artists

    async def start_full(self, path: str = None, force: bool = False, **options):
        async with self._lock:
            if self._current_task and not self._current_task.done():
                raise RuntimeError("Scan already in progress")
            self._stop_event.clear()

            self._status = "Starting Full Scan..."
            self._phase = "filesystem"
            get_api_tracker().reset()
            self.scanner.scan_logger = self.ManagerLogger(self)
            self._current_task = asyncio.create_task(self._run_full(path, force, **options))
            return self._current_task

    async def _run_full(self, path, force, **options):
        try:
            self._broadcast({"type": "start", "mode": "full", "phase": self._phase})
            self._log_message("Starting full library refresh...")
            
            # Phase 1: Filesystem
            self.scanner._stop_event = self._stop_event
            artist_mbids = await self.scanner.scan_filesystem(root_path=path, force_rescan=force) or set()
            
            if self._stop_event.is_set():
                raise asyncio.CancelledError()
            
            # Phase 2: Metadata
            self._phase = "metadata"
            self._broadcast({"type": "start", "mode": "metadata", "phase": self._phase})

            # CRITICAL: Warm DNS cache before metadata operations
            # This handles cases where startup warming failed or cache is cold
            await warm_dns_cache()
            
            scanned_mbids = {m[0] for m in artist_mbids if m[0]}
            if path and not scanned_mbids:
                scanned_mbids = await self.scanner.get_artists_in_path(path) or set()
            is_partial = False 
            if path and os.path.abspath(path) != os.path.abspath(get_music_path()):
                is_partial = True
                
            filter_mbids = scanned_mbids
            
            # Logic for filtering
            if not is_partial and force:
                filter_mbids = None # Update all
            elif not scanned_mbids and not is_partial:
                # No changes, full scan -> skip metadata unless forced?
                if not force:
                    filter_mbids = set() 
                
            if is_partial and not scanned_mbids:
                 # Partial scan, no changes. Should we update metadata for existing files in path?
                 # Yes, assume user meant "Check this folder".
                 found = await self.scanner.get_artists_in_path(path)
                 filter_mbids = found
            
            if filter_mbids is not None and len(filter_mbids) == 0 and not force:
                 self._log_message("No artists to update.")
            else:
                 async for db in get_db():
                     coordinator = MetadataCoordinator(progress_cb=self._update_progress)
                     artists = await self._fetch_artists_for_update(db, None, filter_mbids, scanned_mbids if is_partial or path else None)
                     # Apply missing_only default logic
                     # Use passed options, default valid for full scan
                     await coordinator.update_metadata(artists, options)
                     
                     # Consolidate Top Tracks Matching
                     if options.get("refresh_top_tracks") or options.get("refresh_singles"):
                         await self._rematch_tracks(db, filter_mbids)

            if self._stop_event.is_set():
                raise asyncio.CancelledError()

            # Phase 3: Prune
            if options.get("prune", True):
                self._phase = "prune"
                self._broadcast({"type": "start", "mode": "prune", "phase": self._phase})
                await self.scanner.prune_library()

            self._status = "Idle"
            self._broadcast({"type": "complete", "status": "success", "phase": self._phase})
            self._log_message("Full refresh complete.")
            
        except asyncio.CancelledError:
            self._status = "Idle"
            self._broadcast({"type": "complete", "status": "cancelled", "phase": self._phase})
        except Exception as e:
            logger.exception("Full refresh failed")
            self._status = "Idle"
            self._broadcast({"type": "complete", "status": "error", "error": str(e), "phase": self._phase})
        finally:
            self._current_task = None
            self._phase = None

    async def _rematch_tracks(self, db, mbids):
        from app.scanner.core import match_track_to_library
        
        query = "SELECT id, external_name, external_album, artist_mbid FROM top_track WHERE track_id IS NULL"
        params = []
        if mbids:
             query += " AND artist_mbid = ANY($1::text[])"
             params.append(list(mbids))
             
        rows = await db.fetch(query, *params)
        
        for row in rows:
            tt_id, name, album, mbid = row
            track_id = await match_track_to_library(db, mbid, name, album)
            if track_id:
                await db.execute("UPDATE top_track SET track_id = $1, updated_at = NOW() WHERE id = $2", track_id, tt_id)

    async def start_prune(self):
        async with self._lock:
            if self._current_task and not self._current_task.done():
                raise RuntimeError("Busy")
            self._stop_event.clear()
            self._status = "Pruning..."
            self._phase = "prune"
            self._current_task = asyncio.create_task(self._run_prune())
            return self._current_task

    async def _run_prune(self):
        try:
             self._broadcast({"type": "start", "mode": "prune", "phase": self._phase})
             await self.scanner.prune_library()
             self._status = "Idle"
             self._broadcast({"type": "complete", "status": "success", "phase": self._phase})
        except Exception as e:
             logger.exception("Prune failed")
             self._status = "Idle"
             self._broadcast({"type": "complete", "status": "error", "error": str(e)})
        finally:
             self._current_task = None
             self._phase = None

    async def stop_scan(self):
        if self._current_task and not self._current_task.done():
            self._stop_event.set()
            try:
                await asyncio.wait_for(self._current_task, timeout=5.0)
            except Exception:
                pass

    async def start_missing_albums_scan(self, **kwargs):
        async with self._lock:
            if self._current_task and not self._current_task.done():
                raise RuntimeError("Busy")
            self._stop_event.clear()
            self._status = "Scanning Missing Albums"
            self._phase = "missing_albums"
            self._current_task = asyncio.create_task(self._run_missing_albums(**kwargs))
            return self._current_task

    async def _run_missing_albums(self, artist_filter=None, mbid_filter=None):
        try:
             self._broadcast({"type": "start", "mode": "missing_albums", "phase": self._phase})
             # Warm DNS cache before metadata operations
             await warm_dns_cache()
             
             from app.scanner.missing_scanner import MissingAlbumsScanner
             scanner = MissingAlbumsScanner()
             await scanner.scan(artist_filter, mbid_filter)
             self._status = "Idle"
             self._broadcast({"type": "complete", "status": "success"})
        except Exception as e:
             logger.exception("Missing albums scan failed")
             self._status = "Idle"
             self._broadcast({"type": "complete", "status": "error", "error": str(e)})
        finally:
             self._current_task = None
             self._phase = None
