import asyncio
import logging
import time
import os
from typing import Optional, Dict, Any
from app.scanner.core import Scanner
from app.config import get_music_path
from app.scanner.stats import get_api_tracker

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
        self._event_queues = set()  # Set of asyncio.Queue for connected clients
        self.scanner = Scanner()
        self._phase: Optional[str] = None
        self._music_path = get_music_path()
        self._configure_logging()

    def _configure_logging(self):
        # Central logging handles file output now.
        # We only need to attach the UI Broadcast Handler to the scanner logger.
        scan_logger = logging.getLogger("scanner")

        # UI Broadcast Handler
        if not any(getattr(h, "_ui_broadcast", False) for h in scan_logger.handlers):
            bh = self.BroadcastLogHandler(self)
            bh._ui_broadcast = True
            bh.setLevel(logging.INFO)  # Only show INFO+ in UI to avoid flood
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
        """
        Subscribe to progress events. Returns an async generator.
        """
        queue = asyncio.Queue()
        self._event_queues.add(queue)
        try:
            # Yield current status immediately
            yield {"type": "status", "status": self._status, "stats": self._stats}

            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            self._event_queues.remove(queue)

    async def shutdown(self):
        """Stop any active scan and close all subscriber queues."""
        await self.stop_scan()
        for queue in self._event_queues:
            queue.put_nowait(None)

    def _broadcast(self, event: Dict[str, Any]):
        """Push event to all connected clients"""
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
        }
        self._broadcast(
            {
                "type": "progress",
                "current": current,
                "total": total,
                "percentage": percentage,
                "message": message,
                "phase": self._phase,
                "api_stats": self._stats["api_stats"],
                "processed_stats": self._stats["processed_stats"],
            }
        )

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

            # Wrap in task to run in background
            self._current_task = asyncio.create_task(self._run_scan(path, force))
            return self._current_task

    async def _run_scan(self, path, force):
        try:
            self._broadcast(
                {"type": "start", "mode": "filesystem", "phase": self._phase}
            )
            self._log_message(f"Starting filesystem scan. Force: {force}")

            # The scanner core checks self._stop_event if we pass it or if we attach it to scanner?
            # App Scanner has its own _stop_event. We should probably sync them or pass ours.
            # Currently Scanner creates its own. Let's start by just calling it.
            # TODO: Modify Scanner to accept stop_event or set it.
            self.scanner._stop_event = self._stop_event

            await self.scanner.scan_filesystem(root_path=path, force_rescan=force)

            self._status = "Idle"
            self._broadcast(
                {"type": "complete", "status": "success", "phase": self._phase}
            )
            self._log_message("Scan complete.")
        except asyncio.CancelledError:
            self._status = "Idle"
            self._broadcast(
                {"type": "complete", "status": "cancelled", "phase": self._phase}
            )
            self._log_message("Scan cancelled.")
        except Exception as e:
            logger.exception("Scan failed")
            self._status = "Idle"
            self._broadcast(
                {
                    "type": "complete",
                    "status": "error",
                    "error": str(e),
                    "phase": self._phase,
                }
            )
            self._log_message(f"Scan failed: {e}")
        finally:
            self._current_task = None
            self._phase = None

    async def start_metadata_update(
        self,
        artist_filter=None,
        mbid_filter=None,
        missing_only=False,
        bio_only=False,
        links_only=False,
        refresh_top_tracks=False,
        refresh_singles=False,
        fetch_metadata=True,
        fetch_bio=True,
        fetch_artwork=True,
        fetch_spotify_artwork=False,
        fetch_links=True,
        fetch_similar_artists=False,
    ):
        async with self._lock:
            if self._current_task and not self._current_task.done():
                raise RuntimeError("Scan already in progress")

            self._stop_event.clear()
            self._status = "Starting Metadata Update..."
            self._phase = "metadata" if not links_only else "links"
            get_api_tracker().reset()
            self.scanner.scan_logger = self.ManagerLogger(self)

            self._current_task = asyncio.create_task(
                self._run_metadata(
                    artist_filter,
                    mbid_filter,
                    missing_only,
                    bio_only,
                    links_only,
                    refresh_top_tracks,
                    refresh_singles,
                    fetch_metadata,
                    fetch_bio,
                    fetch_artwork,
                    fetch_spotify_artwork,
                    fetch_links,
                    fetch_similar_artists,
                )
            )
            return self._current_task

    async def _run_metadata(
        self,
        artist,
        mbid,
        missing_only,
        bio_only,
        links_only,
        refresh_top_tracks,
        refresh_singles,
        fetch_metadata,
        fetch_bio,
        fetch_artwork,
        fetch_spotify_artwork,
        fetch_links,
        fetch_similar_artists,
    ):
        try:
            self._broadcast(
                {
                    "type": "start",
                    "mode": "metadata" if not links_only else "links",
                    "phase": self._phase,
                }
            )
            mode_name = "links-only refresh" if links_only else "metadata update"
            self._log_message(f"Starting {mode_name}. Artist: {artist or 'All'}")

            self.scanner._stop_event = self._stop_event
            if links_only:
                await self.scanner.update_links(artist_filter=artist, mbid_filter=mbid)
            else:
                await self.scanner.update_metadata(
                    artist_filter=artist,
                    mbid_filter=mbid,
                    missing_only=missing_only,
                    bio_only=bio_only or fetch_bio,
                    refresh_top_tracks=refresh_top_tracks,
                    refresh_singles=refresh_singles,
                    fetch_metadata=fetch_metadata,
                    fetch_bio=fetch_bio,
                    fetch_artwork=fetch_artwork,
                    fetch_spotify_artwork=fetch_spotify_artwork,
                    fetch_links=fetch_links,
                    fetch_similar_artists=fetch_similar_artists,
                )

            self._status = "Idle"
            self._broadcast(
                {"type": "complete", "status": "success", "phase": self._phase}
            )
            self._log_message(f"{mode_name.capitalize()} complete.")
        except asyncio.CancelledError:
            self._status = "Idle"
            self._broadcast(
                {"type": "complete", "status": "cancelled", "phase": self._phase}
            )
            self._log_message(f"{mode_name.capitalize()} cancelled.")
        except Exception as e:
            logger.exception("Metadata update failed")
            self._status = "Idle"
            self._broadcast(
                {
                    "type": "complete",
                    "status": "error",
                    "error": str(e),
                    "phase": self._phase,
                }
            )
        finally:
            self._current_task = None
            self._phase = None

    async def start_full(
        self,
        path: str = None,
        force: bool = False,
        artist_filter=None,
        mbid_filter=None,
        missing_only=False,
        bio_only=False,
        links_only=False,
        refresh_top_tracks=False,
        refresh_singles=False,
        fetch_metadata=True,
        fetch_bio=True,
        fetch_artwork=True,
        fetch_spotify_artwork=False,
        fetch_links=True,
        prune=True,
        fetch_similar_artists=False,
    ):
        async with self._lock:
            if self._current_task and not self._current_task.done():
                raise RuntimeError("Scan already in progress")

            self._stop_event.clear()
            self._status = "Starting Full Scan..."
            self._phase = "filesystem"
            get_api_tracker().reset()
            self.scanner.scan_logger = self.ManagerLogger(self)

            # For full runs: default to missing-only metadata unless force is requested.
            metadata_missing_only = False if force else missing_only

            self._current_task = asyncio.create_task(
                self._run_full(
                    path,
                    force,
                    artist_filter,
                    mbid_filter,
                    metadata_missing_only,
                    bio_only,
                    links_only,
                    refresh_top_tracks,
                    refresh_singles,
                    fetch_metadata,
                    fetch_bio,
                    fetch_artwork,
                    fetch_spotify_artwork,
                    fetch_links,
                    prune=True,
                    fetch_similar_artists=fetch_similar_artists,
                )
            )
            return self._current_task

    async def _run_full(
        self,
        path,
        force,
        artist,
        mbid,
        missing_only,
        bio_only,
        links_only,
        refresh_top_tracks,
        refresh_singles,
        fetch_metadata,
        fetch_bio,
        fetch_artwork,
        fetch_spotify_artwork,
        fetch_links,
        prune,
        fetch_similar_artists=False,
    ):
        try:
            self._broadcast({"type": "start", "mode": "full", "phase": self._phase})
            self._log_message(
                "Starting full library refresh (scan -> metadata -> prune)"
            )

            self.scanner._stop_event = self._stop_event

            artist_mbids = (
                await self.scanner.scan_filesystem(root_path=path, force_rescan=force)
                or set()
            )

            # Logic: Determine if we should filter the metadata update
            # 1. If it's a partial scan (subfolder), we ALWAYS filter to the artists found, even if Force=True.
            # 2. If it's a full scan AND Force=True, we clear the filter to update everything efficiently (avoid huge IN clause).
            # 3. If Force=False, we always filter to what changed (scanned_mbid_filter).

            music_path = get_music_path()
            # Normalize paths for comparison
            p_abs = os.path.abspath(path) if path else os.path.abspath(music_path)
            m_abs = os.path.abspath(music_path)
            is_partial_scan = p_abs != m_abs

            scanned_mbid_filter = {mb for mb, _ in artist_mbids if mb}

            if not is_partial_scan and force:
                # Full Library Error/Force Scan -> Update All (Efficiently)
                scanned_mbid_filter = None

            if self._stop_event.is_set():
                raise asyncio.CancelledError()

            # After adding/updating files, re-run local matching for existing top tracks
            await self.scanner.rematch_tracks_top(artist_mbids)

            self._phase = "links" if links_only else "metadata"
            self._broadcast(
                {"type": "start", "mode": self._phase, "phase": self._phase}
            )
            if links_only:
                await self.scanner.update_links(artist_filter=artist, mbid_filter=mbid)
            else:
                # If force: run full metadata for all (or specified filter)
                # If not force: restrict to artists touched in this scan
                # LOGIC CHANGE: If we scanned specific files (scanned_mbid_filter), we MUST restrict metadata update to them.
                # ignoring scanned_mbid_filter when force=True caused partial directory scans to trigger FULL DB metadata updates.
                filter_mbid = scanned_mbid_filter if scanned_mbid_filter else mbid
                # If nothing new/updated and no explicit filter, skip metadata to avoid touching everything
                if (
                    not force
                    and not artist
                    and not mbid
                    and not scanned_mbid_filter
                    and not refresh_top_tracks
                    and not refresh_singles
                ):
                    # Logic: If nothing changed, BUT it's a partial scan, we must still respect the partial scan intent.
                    # e.g. "Force Rescan" on a folder that didn't change anything internally (0 additions)
                    # OR just a rescan of a folder that yielded nothing new.
                    # The user expects metadata for THIS FOLDER to be checked if they asked for it.
                    # But wait, original logic skipped metadata if `scanned_mbid_filter` was empty.
                    
                    if is_partial_scan:
                        # Fetch artists in this path to behave as if we scanned them
                        self._log_message("No file changes in partial scan; verifying existing artists in path...")
                        found_artists = await self.scanner.get_artists_in_path(path)
                        if found_artists:
                             filter_mbid = found_artists
                        else:
                             # Empty folder or no tracks
                             self._log_message("No artists found in path; skipping metadata.")
                             filter_mbid = set() # Ensure it's empty so loop can skip or handle gracefully (actually update_metadata handles empty filter by querying all, we MUST NOT let that happen)
                             
                             # Actually, update_metadata with empty set as filter MIGHT act weird if we don't pass explicit clauses.
                             # Let's check update_metadata logic:
                             # if mbid_filter: clauses.append("mbid = ANY(...)")
                             # If we pass an EMPTY SET, params will be empty list, clause "mbid = ANY($1)".
                             # Postgres "ANY('{}')" matches nothing. Correct.
                             filter_mbid = set()

                    else:
                         self._log_message(
                            "No new/updated artists detected; skipping metadata step."
                        )
                         filter_mbid = set() # Skip

                # Final Safety: If partial scan, NEVER allow filter_mbid to be None/Empty if we intended to scan something.
                # If we found nothing, filter_mbid is empty set -> matches nothing -> safe.
                # If we found something, filter_mbid is set -> matches them -> safe.
                # If full scan and nothing changed -> skipped above or empty set -> safe.

                if not is_partial_scan and not filter_mbid and not force and not artist and not mbid:
                     # Double check we don't accidentally update everything if we fell through
                     pass

                if is_partial_scan and not filter_mbid:
                     # Optimization: if strict partial scan yielded 0 artists, don't even call update
                     pass
                else: 
                     # Always allow new artists to fetch top tracks; existing artists obey refresh_top_tracks flag.
                     await self.scanner.update_metadata(
                        artist_filter=artist,
                        mbid_filter=filter_mbid,
                        missing_only=missing_only,
                        bio_only=bio_only,
                        refresh_top_tracks=refresh_top_tracks,
                        refresh_singles=refresh_singles,
                        fetch_metadata=fetch_metadata,
                        fetch_bio=fetch_bio,
                        fetch_artwork=fetch_artwork,
                        fetch_spotify_artwork=fetch_spotify_artwork,
                        fetch_links=fetch_links,
                        fetch_similar_artists=fetch_similar_artists,
                    )

            if self._stop_event.is_set():
                raise asyncio.CancelledError()

            if prune:
                self._phase = "prune"
                self._broadcast(
                    {"type": "start", "mode": "prune", "phase": self._phase}
                )
                await self.scanner.prune_library()
            else:
                self._log_message("Prune skipped (not requested).")

            self._status = "Idle"
            self._broadcast(
                {"type": "complete", "status": "success", "phase": self._phase}
            )
            self._log_message("Full library refresh complete.")
        except asyncio.CancelledError:
            self._status = "Idle"
            self._broadcast(
                {"type": "complete", "status": "cancelled", "phase": self._phase}
            )
            self._log_message("Full refresh cancelled.")
        except Exception as e:
            logger.exception("Full refresh failed")
            self._status = "Idle"
            self._broadcast(
                {
                    "type": "complete",
                    "status": "error",
                    "error": str(e),
                    "phase": self._phase,
                }
            )
            self._log_message(f"Full refresh failed: {e}")
        finally:
            self._current_task = None
            self._phase = None

    async def start_prune(self):
        async with self._lock:
            if self._current_task and not self._current_task.done():
                raise RuntimeError("Scan already in progress")

            self._stop_event.clear()
            self._status = "Pruning Library..."
            self._phase = "prune"
            self.scanner.scan_logger = self.ManagerLogger(self)

            self._current_task = asyncio.create_task(self._run_prune())
            return self._current_task

    async def _run_prune(self):
        try:
            self._broadcast({"type": "start", "mode": "prune", "phase": self._phase})
            self._log_message("Starting library prune...")

            self.scanner._stop_event = self._stop_event
            await self.scanner.prune_library()

            self._status = "Idle"
            self._broadcast(
                {"type": "complete", "status": "success", "phase": self._phase}
            )
            self._log_message("Prune complete.")
        except Exception as e:
            logger.exception("Prune failed")
            self._status = "Idle"
            self._broadcast(
                {
                    "type": "complete",
                    "status": "error",
                    "error": str(e),
                    "phase": self._phase,
                }
            )
        finally:
            self._current_task = None
            self._phase = None

    async def stop_scan(self):
        if self._current_task and not self._current_task.done():
            self._stop_event.set()
            self._log_message("Stopping scan...")
            try:
                # Wait for task to finish gracefully with a timeout
                await asyncio.wait_for(self._current_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "Scan task did not stop gracefully, forcing cancellation..."
                )
                self._current_task.cancel()
                try:
                    await self._current_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Error waiting for scan to stop: {e}")

    async def start_missing_albums_scan(self, artist_filter=None, mbid_filter=None):
        async with self._lock:
            if self._current_task and not self._current_task.done():
                raise RuntimeError("Scan already in progress")

            self._stop_event.clear()
            self._status = "Scanning Missing Albums..."
            self._phase = "missing_albums"
            get_api_tracker().reset()
            self.scanner.scan_logger = self.ManagerLogger(self)

            self._current_task = asyncio.create_task(
                self._run_missing_albums_scan(artist_filter, mbid_filter)
            )
            return self._current_task

    async def _run_missing_albums_scan(self, artist_filter, mbid_filter):
        try:
            self._broadcast(
                {"type": "start", "mode": "missing_albums", "phase": self._phase}
            )
            self._log_message(
                f"Starting Missing Albums Scan. Filter: {artist_filter or mbid_filter or 'All'}"
            )

            self.scanner._stop_event = self._stop_event
            await self.scanner.scan_missing_albums(
                artist_filter=artist_filter, mbid_filter=mbid_filter
            )

            self._status = "Idle"
            self._broadcast(
                {"type": "complete", "status": "success", "phase": self._phase}
            )
            self._log_message("Missing Albums Scan complete.")
        except asyncio.CancelledError:
            self._status = "Idle"
            self._broadcast(
                {"type": "complete", "status": "cancelled", "phase": self._phase}
            )
            self._log_message("Missing Albums Scan cancelled.")
        except Exception as e:
            logger.exception("Missing Albums Scan failed")
            self._status = "Idle"
            self._broadcast(
                {
                    "type": "complete",
                    "status": "error",
                    "error": str(e),
                    "phase": self._phase,
                }
            )
            self._log_message(f"Missing Albums Scan failed: {e}")
        finally:
            self._current_task = None
            self._phase = None
