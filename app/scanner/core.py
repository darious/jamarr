import os
import asyncio
import logging
import json
import time
from app.db import get_db
from app.scanner.tags import extract_tags
from app.scanner.artwork import extract_and_save_artwork, download_and_save_artwork, cleanup_orphaned_artwork, upsert_artwork_record, upsert_image_mapping
from app.config import get_music_path
from app.scanner.metadata import fetch_artist_metadata, fetch_track_credits, SPOTIFY_SCANNING_DISABLED
import difflib
import re
from app.tidal import TidalClient, year_from_date
import shlex

logger = logging.getLogger("scanner.core")

SUPPORTED_EXTENSIONS = {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aiff"}

class Scanner:
    def __init__(self):
        self._stop_event = asyncio.Event()
        self.stats = {
            "scanned": 0,
            "added": 0,
            "updated": 0,
            "errors": 0,
            "total_estimate": 0,
            "current_status": "Idle"
        }
        self.scan_logger = None # Can be attached later
        self.art_cache_path = "cache/art"
        self._db_files_cache = {} # path -> mtime
        self._processed_artists_session = set() # (mbid, name)
        self._batch_counter = 0
        self._batch_size = 100

    async def scan_filesystem(self, root_path: str = None, force_rescan: bool = False):
        if root_path is None:
            root_path = get_music_path()

        if not os.path.exists(root_path):
            logger.error(f"Scan path not found: {root_path}")
            return

        self.stats = {"scanned": 0, "added": 0, "updated": 0, "errors": 0, "total_estimate": 0, "current_status": "Scanning"}
        self._stop_event.clear()
        self._processed_artists_session = set()
        self._batch_counter = 0
        
        logger.info(f"Starting scan of {root_path} (Force: {force_rescan})")
        
        # 1. Estimate
        self.stats["current_status"] = "Counting files..."
        # Optimization: Don't walk filesystem (blocking). Use DB count as estimate.
        # It's better to start scanning immediately.
        # file_count = 0
        # for _, _, files in os.walk(root_path): ...
        
        file_count = 0 # Will be updated after DB load
        self.stats["total_estimate"] = 0

        # Pre-scan Cleanup (Force Rescan only)
        if force_rescan:
            try:
                music_root = get_music_path()
                rel_root = os.path.relpath(root_path, music_root)
                
                if rel_root == ".":
                    limit_clause = "1=1"
                    params = ()
                else:
                    limit_clause = "path LIKE ? OR path = ?"
                    params = (f"{rel_root}/%", rel_root)
                
                async for db in get_db():
                    # Comprehensive cleanup for Force Rescan
                    # Delete tracks, albums, and ALL related data for the target path
                    
                    start_t = time.time()
                    
                    # Step 1: Identify tracks and albums in scope
                    cursor = await db.execute(f"SELECT id FROM track WHERE {limit_clause}", params)
                    t_rows = await cursor.fetchall()
                    track_ids = [r[0] for r in t_rows]
                    
                    cursor = await db.execute(f"SELECT DISTINCT release_group_mbid FROM track WHERE {limit_clause}", params)
                    a_rows = await cursor.fetchall()
                    album_mbids = [r[0] for r in a_rows if r[0]]
                    
                    # Step 2: Identify artists associated with these tracks/albums
                    # (We'll clean up their metadata links)
                    artist_mbids_to_clean = set()
                    if track_ids:
                        t_placeholders = ",".join("?" * len(track_ids))
                        cursor = await db.execute(f"SELECT DISTINCT artist_mbid FROM track_artist WHERE track_id IN ({t_placeholders})", track_ids)
                        artist_rows = await cursor.fetchall()
                        artist_mbids_to_clean = {r[0] for r in artist_rows if r[0]}

                    if not track_ids:
                        logger.info("Force Rescan Cleanup: No existing tracks found in this path.")
                        continue

                    # Step 3: Delete all related data
                    counts = {}
                    
                    # A. Track-level deletions
                    t_placeholders = ",".join("?" * len(track_ids))
                    
                    # Delete track-artist links
                    cursor = await db.execute(f"DELETE FROM track_artist WHERE track_id IN ({t_placeholders})", track_ids)
                    counts['track_artists'] = cursor.rowcount
                    
                    # Delete image mappings for tracks
                    cursor = await db.execute(f"DELETE FROM image_map WHERE entity_type='track' AND entity_id IN ({t_placeholders})", [str(tid) for tid in track_ids])
                    counts['track_images'] = cursor.rowcount
                    
                    # Delete tracks themselves
                    await db.execute(f"DELETE FROM track WHERE id IN ({t_placeholders})", track_ids)
                    counts['tracks'] = len(track_ids)
                    
                    # B. Album-level deletions
                    if album_mbids:
                        a_placeholders = ",".join("?" * len(album_mbids))
                        
                        # Delete artist-album links
                        cursor = await db.execute(f"DELETE FROM artist_album WHERE album_mbid IN ({a_placeholders})", album_mbids)
                        counts['artist_albums'] = cursor.rowcount
                        
                        # Delete album external links
                        cursor = await db.execute(f"DELETE FROM external_link WHERE entity_type='album' AND entity_id IN ({a_placeholders})", album_mbids)
                        counts['album_links'] = cursor.rowcount
                        
                        # Delete album image mappings
                        cursor = await db.execute(f"DELETE FROM image_map WHERE entity_type='album' AND entity_id IN ({a_placeholders})", album_mbids)
                        counts['album_images'] = cursor.rowcount
                        
                        # Delete albums
                        cursor = await db.execute(f"DELETE FROM album WHERE mbid IN ({a_placeholders})", album_mbids)
                        counts['albums'] = cursor.rowcount
                        
                        # Delete missing_albums entries (they'll be re-discovered if still missing)
                        cursor = await db.execute(f"DELETE FROM missing_album WHERE release_group_mbid IN ({a_placeholders})", album_mbids)
                        counts['missing_albums'] = cursor.rowcount
                    
                    # C. Artist metadata cleanup (for artists in this scope)
                    # Note: We DON'T delete the artists themselves, as they might have tracks elsewhere
                    # But we DO clean up their metadata links that might be stale
                    if artist_mbids_to_clean:
                        am_placeholders = ",".join("?" * len(artist_mbids_to_clean))
                        artist_list = list(artist_mbids_to_clean)
                        
                        # Delete artist external links
                        cursor = await db.execute(f"DELETE FROM external_link WHERE entity_type='artist' AND entity_id IN ({am_placeholders})", artist_list)
                        counts['artist_links'] = cursor.rowcount
                        
                        # Delete artist image mappings
                        cursor = await db.execute(f"DELETE FROM image_map WHERE entity_type='artist' AND entity_id IN ({am_placeholders})", artist_list)
                        counts['artist_images'] = cursor.rowcount
                        
                        # Delete artist genres
                        cursor = await db.execute(f"DELETE FROM artist_genre WHERE artist_mbid IN ({am_placeholders})", artist_list)
                        counts['artist_genres'] = cursor.rowcount
                        
                        # Delete top tracks/singles
                        cursor = await db.execute(f"DELETE FROM top_track WHERE artist_mbid IN ({am_placeholders})", artist_list)
                        counts['tracks_top'] = cursor.rowcount
                        
                        # Delete similar artists
                        cursor = await db.execute(f"DELETE FROM similar_artist WHERE artist_mbid IN ({am_placeholders})", artist_list)
                        counts['similar_artists'] = cursor.rowcount

                    await db.commit()
                    
                    # Build summary log
                    summary_parts = []
                    if counts.get('tracks'): summary_parts.append(f"{counts['tracks']} tracks")
                    if counts.get('albums'): summary_parts.append(f"{counts['albums']} albums")
                    if counts.get('artist_albums'): summary_parts.append(f"{counts['artist_albums']} artist-album links")
                    if counts.get('artist_links'): summary_parts.append(f"{counts['artist_links']} artist external links")
                    if counts.get('album_links'): summary_parts.append(f"{counts['album_links']} album external links")
                    if counts.get('tracks_top'): summary_parts.append(f"{counts['tracks_top']} top tracks/singles")
                    if counts.get('artist_genres'): summary_parts.append(f"{counts['artist_genres']} genre tags")
                    
                    
                    summary = ", ".join(summary_parts) if summary_parts else "no data"
                    logger.info(f"Force Rescan Cleanup: Purged {summary} for '{rel_root}' ({time.time() - start_t:.2f}s)")
                    break  # Exit the async for loop to close the DB connection before scanning starts
            except Exception as e:
                logger.warning(f"Cleanup failed: {e}")
        
        # Concurrency for directory scanning
        # self._recursion_sem = asyncio.Semaphore(20) # Removed in favor of Queue

        # 2. Scanning
        self.stats["current_status"] = "Scanning Files"
        artist_mbids = set()
        seen_paths = set()
        
        async for db in get_db():
            # Pre-fetch existing files for batch check
            self.stats["current_status"] = "Loading DB Cache..."
            logger.info("Pre-fetching file list from database...")
            self._db_files_cache = {}
            async with db.execute("SELECT path, updated_at FROM track") as cursor:
                rows = await cursor.fetchall()
                for r in rows:
                    self._db_files_cache[r[0]] = r[1]
            
            # Use 'find' for accurate fast estimate
            self.stats["current_status"] = "Counting files..."
            db_count = len(self._db_files_cache)
            # Only use find if we expect a sub-scan (root_path is not default) OR to be safe always?
            # User said "is almost instant". Let's use it.
            actual_count = await self._estimate_file_count(root_path)
            
            # Use the larger of the two to avoid 100% too early if find misses something? 
            # No, find is ground truth for the filesystem scan.
            self.stats["total_estimate"] = actual_count if actual_count > 0 else (db_count or 1000)
            
            logger.info(f"Estimated file count: {self.stats['total_estimate']} (find said {actual_count}, db has {db_count})")
            self.stats["current_status"] = "Scanning Files"

            await self._scan_recursive(root_path, db, artist_mbids, seen_paths, force_rescan)
            
            # Commit any remaining items
            if self._batch_counter > 0:
                await db.commit()
                self._batch_counter = 0

            # 3. Cleanup
            self.stats["current_status"] = "Cleaning Orphans"
            await self._cleanup_orphans(db, root_path, seen_paths)
            
            # 4. Populate Artists Table
            # Ensure all referenced artists exist in the artists table (from current scan OR existing DB)
            async with db.execute("SELECT DISTINCT artist_mbid FROM track_artist") as cursor:
                rows = await cursor.fetchall()
                db_mbids = {r[0] for r in rows if r[0]}
            
            # Merge known names from scan if available
            all_mbids = db_mbids.union({m[0] for m in artist_mbids if m[0]})

            logger.info(f"Ensuring {len(all_mbids)} artists exist in database...")
            
            # Use batch inserts for missing artists if possible, but simple loop is fine for updates
            # Actually, `_processed_artists_session` might have handled most if `_process_track_artists` works right
            # But we still need to ensure consistency.
            
            count = 0
            for mbid in all_mbids:
                 await db.execute("INSERT OR IGNORE INTO artist (mbid) VALUES (?)", (mbid,))
                 count += 1
                 if count % 100 == 0: await db.commit()
            
            # Update names if we have them from the scan
            count = 0
            for mbid, name in artist_mbids:
                 if mbid and name:
                     await db.execute("UPDATE artist SET name = ? WHERE mbid = ? AND (name IS NULL OR name = '')", (name, mbid))
                     count += 1
                     if count % 100 == 0: await db.commit()

            await db.commit()
            
            # Clear caches
            self._db_files_cache = {}
            self._processed_artists_session = set()

            logger.info(f"Scanner finished: {self.stats['scanned']} scanned, {self.stats['added']} added, {self.stats['updated']} updated, {self.stats.get('deleted_relations', 0)} relations cleared.")

            return artist_mbids

    async def _estimate_file_count(self, root_path):
        """
        Fast file count using 'find' command to get an accurate progress bar estimate.
        """
        # Build command: find "/path" -type f \( -iname '*.mp3' -o -iname '*.flac' ... \) -print | wc -l
        safe_root = shlex.quote(root_path)
        clauses = []
        for ext in SUPPORTED_EXTENSIONS:
            # quote the pattern to avoid shell expansion issues
            clauses.append(f"-iname '*{ext}'")
        
        or_clause = " -o ".join(clauses)
        cmd = f"find {safe_root} -type f \\( {or_clause} \\) -print | wc -l"
        
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if stdout:
                 count = int(stdout.decode().strip())
                 return count
        except Exception as e:
            logger.warning(f"Failed to estimate file count via shell: {e}")
        
        # Fallback to a safe default
        return 0

    async def _scan_recursive(self, root, db, artist_mbids, seen_paths, force_rescan):
        if self._stop_event.is_set(): return

        queue = asyncio.Queue()
        queue.put_nowait(root)
        
        # Determine number of workers (can be higher now that we don't deadlock)
        num_workers = 20

        async def worker():
            batch_counter = 0  # Per-worker batch counter
            while True:
                try:
                    path = await queue.get()
                    try:
                        if self._stop_event.is_set():
                            continue

                        # logger.info(f"Listing directory: {path}")
                        with os.scandir(path) as it:
                            entries = list(it)
                        
                        for entry in entries:
                            if entry.is_dir():
                                queue.put_nowait(entry.path)
                            elif entry.is_file():
                                ext = os.path.splitext(entry.name)[1].lower()
                                if ext in SUPPORTED_EXTENSIONS:
                                    seen_paths.add(entry.path)
                                    self.stats["scanned"] += 1
                                    
                                    if self.scan_logger and self.stats["scanned"] % 10 == 0:
                                        percent = (self.stats["scanned"] / self.stats["total_estimate"] * 100) if self.stats["total_estimate"] else 0
                                        self.scan_logger.emit_progress(self.stats["scanned"], self.stats["total_estimate"], f"Scanning {entry.name}")
                                    
                                    await self._process_file(entry.path, db, artist_mbids, force_rescan, entry=entry)
                                    
                                    # Batch Commit (per-worker)
                                    batch_counter += 1
                                    if batch_counter >= self._batch_size:
                                        await db.commit()
                                        batch_counter = 0

                    except OSError as e:
                        logger.error(f"Error listing {path}: {e}")
                    except Exception as e:
                        logger.exception(f"Error scanning {path}: {e}")
                    finally:
                        queue.task_done()
                except asyncio.CancelledError:
                    break
        
        workers = [asyncio.create_task(worker()) for _ in range(num_workers)]
        
        # Wait for queue to be fully processed
        await queue.join()
        
        # Cancel workers
        for w in workers: w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)



    async def _process_file(self, path, db, artist_mbids, force_rescan, entry=None):
        try:

            # Check modification time using Cache
            music_root = get_music_path()
            rel_path = os.path.relpath(path, music_root)
            # logger.debug(f"[filesystem] Processing file: {rel_path}")
            
            # Optimization: Use entry.stat() if available (likely cached or just one syscall)
            # instead of os.path.getmtime(path)
            if entry:
                mtime = entry.stat().st_mtime
            else:
                mtime = os.path.getmtime(path)
            
            # Optimized Check
            cached_mtime = self._db_files_cache.get(rel_path)
            if not force_rescan and cached_mtime is not None and abs(cached_mtime - mtime) < 0.001:
                # logger.debug(f"[filesystem] Skipping unchanged file: {rel_path}")
                return # Unchanged

            # Extract Tags
            tags = extract_tags(path)
            if not tags: return

            # Artwork
            art_result = await extract_and_save_artwork(path)
            artwork_id = None
            if art_result:
                artwork_id = await upsert_artwork_record(
                    db,
                    art_result.get("sha1"),
                    meta=art_result.get("meta"),
                )
                # logger.debug(f"[filesystem] Artwork cached for {rel_path} sha1={art_result.get('sha1')}")

            mb_rg_id = tags.get("release_group_mbid")

            # Upsert Track
            keys = ["path", "updated_at", "title", "artist", "album", "album_artist", 
                    "track_no", "disc_no", "date", "genre", "duration_seconds", 
                    "codec", "sample_rate_hz", "bit_depth", "bitrate", "channels", "label", 
                    "artist_mbid", "album_artist_mbid", "track_mbid", "release_track_mbid", "release_mbid", "release_group_mbid", "artwork_id"]
            
            values = [
                rel_path, mtime, tags.get("title"), tags.get("artist"), tags.get("album"), 
                tags.get("album_artist"), tags.get("track_no"), tags.get("disc_no"), 
                tags.get("date"), tags.get("genre"), tags.get("duration_seconds"),
                tags.get("codec"), tags.get("sample_rate_hz"), tags.get("bit_depth"),
                tags.get("bitrate"), tags.get("channels"), tags.get("label"),
                tags.get("artist_mbid"), tags.get("album_artist_mbid"), 
                tags.get("track_mbid"), tags.get("release_track_mbid"), tags.get("release_mbid"), mb_rg_id, artwork_id
            ]
            
            placeholders = ", ".join(["?"] * len(keys))
            columns = ", ".join(keys)
            
            sql = f"""
                INSERT INTO track ({columns}) VALUES ({placeholders})
                ON CONFLICT(path) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    title=excluded.title,
                    artist=excluded.artist,
                    album=excluded.album,
                    album_artist=excluded.album_artist,
                    track_no=excluded.track_no,
                    disc_no=excluded.disc_no,
                    date=excluded.date,
                    genre=excluded.genre,
                    duration_seconds=excluded.duration_seconds,
                    codec=excluded.codec,
                    sample_rate_hz=excluded.sample_rate_hz,
                    bit_depth=excluded.bit_depth,
                    bitrate=excluded.bitrate,
                    channels=excluded.channels,
                    label=excluded.label,
                    artist_mbid=excluded.artist_mbid,
                    album_artist_mbid=excluded.album_artist_mbid,
                    track_mbid=excluded.track_mbid,
                    release_track_mbid=excluded.release_track_mbid,
                    release_mbid=excluded.release_mbid,
                    release_group_mbid=excluded.release_group_mbid,
                    artwork_id=excluded.artwork_id
            """
            cursor = await db.execute(sql, values)
            
            if cursor.lastrowid:
                track_id = cursor.lastrowid
            else:
                async with db.execute("SELECT id FROM track WHERE path = ?", (rel_path,)) as c2:
                    row = await c2.fetchone()
                    track_id = row[0] if row else None
        
            if cached_mtime is not None:
                self.stats["updated"] += 1
            else:
                self.stats["added"] += 1

            # Map artwork to album or track fallback
            if artwork_id:
                if mb_rg_id:
                    await upsert_image_mapping(db, artwork_id, "album", mb_rg_id, "album")
                else:
                    await upsert_image_mapping(db, artwork_id, "track", track_id, "album")

            # --- Populate Normalized Tables from Tags ---
            
            # 1. Albums
            mb_rg_id = tags.get("release_group_mbid")
            album_title = tags.get("album")
            if mb_rg_id and album_title:
                 # Upsert Album
                 try:
                     await db.execute("""
                        INSERT INTO album (mbid, title, release_date, secondary_types, artwork_id, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(mbid) DO UPDATE SET
                            title=COALESCE(excluded.title, title),
                            release_date=COALESCE(excluded.release_date, release_date),
                            artwork_id=COALESCE(excluded.artwork_id, artwork_id)
                     """, (mb_rg_id, album_title, tags.get("date"), 'Album', artwork_id, time.time()))

                     # Remove from missing_album if we have it now
                     await db.execute("DELETE FROM missing_album WHERE release_group_mbid = ?", (mb_rg_id,))
                 except Exception as e:
                     logger.warning(f"Error upserting album {album_title} ({mb_rg_id}): {e}")

            # 2. Handle Artists & Junctions
            if track_id:
                await self._process_track_artists(db, track_id, tags, artist_mbids, mb_rg_id)

            # Removed db.commit() - handled by batcher

        except Exception as e:
            logger.error(f"Failed to process {path}: {e}")
            self.stats["errors"] += 1

    async def _process_track_artists(self, db, track_id, tags, artist_mbids, mb_rg_id=None):
        # Clear existing
        await db.execute("DELETE FROM track_artist WHERE track_id = ?", (track_id,))
        
        # Helper to extract IDs
        def extract_ids(raw):
            if not raw: return []
            cleaned = raw.replace("/", ";").replace("&", ";")
            return [x.strip() for x in cleaned.split(";") if x.strip()]

        aa_ids = []
        if tags.get("album_artist_mbid"):
             aa_ids = extract_ids(tags["album_artist_mbid"])

        ids = []
        if tags.get("artist_mbid"):
            ids = extract_ids(tags["artist_mbid"])

        # Deduplicate IDs to prevent UNIQUE constraint violations
        ids = list(dict.fromkeys(ids))

        for mbid in ids:
            await db.execute("INSERT OR IGNORE INTO track_artist (track_id, artist_mbid) VALUES (?, ?)", (track_id, mbid))
            
            # Upsert Artist (Track Artist)
            name = tags.get("artist") if len(ids) == 1 else None
            
            if (mbid, name) not in self._processed_artists_session:
                await db.execute("""
                    INSERT INTO artist (mbid, name, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(mbid) DO UPDATE SET name=COALESCE(name, excluded.name)
                """, (mbid, name, time.time()))
                
                # Create MusicBrainz external link
                from app.config import get_musicbrainz_root_url
                mb_url = f"{get_musicbrainz_root_url()}/artist/{mbid}"
                await db.execute("""
                    INSERT OR IGNORE INTO external_link (entity_type, entity_id, type, url)
                    VALUES (?, ?, ?, ?)
                """, ('artist', mbid, 'musicbrainz', mb_url))
                
                self._processed_artists_session.add((mbid, name))

            artist_mbids.add((mbid, name))
            
            # Logic: Link to Album as 'appears_on' if not album artist
            if mb_rg_id and mbid not in aa_ids:
                 await db.execute("""
                    INSERT INTO artist_album (artist_mbid, album_mbid, type)
                    VALUES (?, ?, ?)
                    ON CONFLICT(artist_mbid, album_mbid) DO NOTHING
                 """, (mbid, mb_rg_id, 'appears_on'))
        
        # Album Artist & Album Junction
        if tags.get("album_artist_mbid"):
             aa_ids = extract_ids(tags["album_artist_mbid"])
             aa_name = tags.get("album_artist") or tags.get("artist")
             name = aa_name if len(aa_ids) == 1 else None
             
             for mbid in aa_ids:
                 # Upsert Artist (Album Artist)
                 if (mbid, name) not in self._processed_artists_session:
                     await db.execute("""
                        INSERT INTO artist (mbid, name, updated_at) VALUES (?, ?, ?)
                        ON CONFLICT(mbid) DO UPDATE SET name=COALESCE(name, excluded.name)
                     """, (mbid, name, time.time()))
                     
                     # Create MusicBrainz external link
                     from app.config import get_musicbrainz_root_url
                     mb_url = f"{get_musicbrainz_root_url()}/artist/{mbid}"
                     await db.execute("""
                        INSERT OR IGNORE INTO external_link (entity_type, entity_id, type, url)
                        VALUES (?, ?, ?, ?)
                     """, ('artist', mbid, 'musicbrainz', mb_url))
                     
                     self._processed_artists_session.add((mbid, name))

                 artist_mbids.add((mbid, name))
                 
                 # Junction: Artist-Album (Primary)
                 if mb_rg_id:
                     safe_title = tags.get("album") or f"Unknown Album ({mb_rg_id})"
                     await db.execute("""
                        INSERT INTO album (mbid, title, release_date, secondary_types, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(mbid) DO NOTHING
                     """, (mb_rg_id, safe_title, tags.get("date"), 'Album', time.time()))

                     await db.execute("""
                        INSERT INTO artist_album (artist_mbid, album_mbid, type)
                        VALUES (?, ?, ?)
                        ON CONFLICT(artist_mbid, album_mbid) DO NOTHING
                     """, (mbid, mb_rg_id, 'primary'))

             # Update top_track if this track is a match
             if tags.get("title"):
                 track_title = tags.get("title").strip().lower()
                 track_album = tags.get("album", "").strip().lower()
                 
                 for mbid in aa_ids:
                     # Fetch Top Tracks (Existing Logic kept, optimization complex due to fuzzy search)
                     # Since this is a SELECT, it's safer, but could catch in local variable if needed.
                     # For now, leaving as is to reduce risk of breaking fuzzy logic.
                     top_tracks = []
                     async with db.execute("""
                         SELECT id, external_name, external_album, external_duration_ms
                         FROM top_track
                         WHERE artist_mbid = ? AND track_id IS NULL
                     """, (mbid,)) as cursor:
                          top_tracks = await cursor.fetchall()
                          
                     if not top_tracks:
                         continue

                     # Fuzzy Match Logic
                     def normalize(s):
                         if not s: return ""
                         s = s.lower().strip()
                         s = re.sub(r'[\(\[][^\)\]]*(feat|with|remast|deluxe|edit|mix)[^\)\]]*[\)\]]', '', s)
                         s = re.sub(r'[^\w\s]', '', s)
                         s = re.sub(r'\s+', ' ', s).strip()
                         return s

                     def fuzzy_score(s1, s2):
                         return difflib.SequenceMatcher(None, normalize(s1), normalize(s2)).ratio()
                     
                     curr_title = tags.get("title", "")
                     curr_album = tags.get("album", "")
                     curr_duration = tags.get("duration", 0) # seconds

                     for tt in top_tracks:
                         tt_id, tt_name, tt_album, tt_dur_ms = tt
                         
                         total_weight = 0.6
                         current_score = 0
                         
                         t_score = fuzzy_score(tt_name, curr_title)
                         if t_score < 0.6: continue
                         current_score += t_score * 0.6
                         
                         if tt_album and curr_album:
                             total_weight += 0.2
                             a_score = fuzzy_score(tt_album, curr_album)
                             current_score += a_score * 0.2
                         
                         if tt_dur_ms and curr_duration:
                             total_weight += 0.2
                             diff = abs((tt_dur_ms / 1000) - curr_duration)
                             if diff < 5:
                                 current_score += 0.2
                             elif diff < 15:
                                 current_score += 0.1
                         
                         final_score = current_score / total_weight
                         
                         if final_score > 0.75:
                              await db.execute("""
                                 UPDATE top_track
                                 SET track_id = ?, updated_at = ?
                                 WHERE id = ?
                              """, (track_id, time.time(), tt_id))

    async def _cleanup_orphans(self, db, root_path, seen_paths):
        music_root = get_music_path()
        seen_rel_paths = {os.path.relpath(p, music_root) for p in seen_paths}
        
        # Calculate relative scan root effectively
        # If we scanned the whole library, self._db_files_cache has everything.
        # But if we scanned a SUBFOLDER, we only want to prune tracks within that subfolder.
        # However, _db_files_cache was loaded with EVERYTHING from DB properly? 
        # Wait, I loaded `SELECT path FROM track`. Yes, everything.
        
        if os.path.abspath(root_path) == os.path.abspath(music_root):
            # Full scan: Orphans are simply DB - seen
            db_paths = set(self._db_files_cache.keys())
            orphans = db_paths - seen_rel_paths
        else:
            # Partial scan: Filter DB paths to only those starting with rel_root
            rel_root = os.path.relpath(root_path, music_root)
            if rel_root == ".": rel_root = ""
            
            db_paths_in_scope = set()
            for p in self._db_files_cache.keys():
                if p.startswith(rel_root):
                    db_paths_in_scope.add(p)
            
            orphans = db_paths_in_scope - seen_rel_paths

        if orphans:
            logger.info(f"Removing {len(orphans)} orphaned track.")
            count = 0
            for orphan in orphans:
                await db.execute("DELETE FROM track WHERE path = ?", (orphan,))
                count += 1
                if count % 100 == 0: await db.commit()
            await db.commit()

    async def prune_library(self):
        """
        Comprehensive cleanup of the database and filesystem.
        Removes:
        1. Tracks not on disk.
        2. Artists/Albums with no track.
        3. External links for deleted entities.
        4. Artwork not referenced in DB (Filesystem & DB).
        """
        self.stats["current_status"] = "Pruning Library"
        logger.info("Starting Library Prune...")
        
        async for db in get_db():
            # 1. Prune Tracks (DB -> FS check)
            logger.info("Checking for deleted files...")
            async with db.execute("SELECT id, path FROM track") as cursor:
                rows = await cursor.fetchall()
            
            music_root = get_music_path()
            deleted_tracks = 0
            for track_id, rel_path in rows:
                abs_path = os.path.join(music_root, rel_path)
                if not os.path.exists(abs_path):
                    # logger.debug(f"Pruning missing file: {path}")
                    await db.execute("DELETE FROM track WHERE id = ?", (track_id,))
                    deleted_tracks += 1
            if deleted_tracks:
                await db.commit()
                logger.info(f"Removed {deleted_tracks} missing track.")
            
            # 2. Prune Orphaned Artists (No tracks in track_artists)
            # Find artists who are NOT in track_artists
            logger.info("Pruning orphaned artists...")
            await db.execute("""
                DELETE FROM artist 
                WHERE mbid NOT IN (SELECT DISTINCT mbid FROM track_artist)
            """)
            
            # 3. Prune Orphaned Albums (No tracks associated)
            # Based on track.release_group_mbid
            logger.info("Pruning orphaned albums...")
            await db.execute("""
                DELETE FROM album 
                WHERE mbid NOT IN (SELECT DISTINCT release_group_mbid FROM track WHERE release_group_mbid IS NOT NULL)
            """)
            
            # 4. Prune Orphaned Junctions (Artist-Albums)
            await db.execute("""
                DELETE FROM artist_album
                WHERE artist_mbid NOT IN (SELECT mbid FROM artist)
                OR album_mbid NOT IN (SELECT mbid FROM album)
            """)
            
            # 5. Prune External Links
            await db.execute("""
                DELETE FROM external_link
                WHERE (entity_type='artist' AND entity_id NOT IN (SELECT mbid FROM artist))
                OR (entity_type='album' AND entity_id NOT IN (SELECT mbid FROM album))
            """)

            await db.commit()
            
            # 6. Prune Artwork (The big one)
            logger.info("Pruning orphaned artwork...")
            
            used_shas = set()
            async with db.execute("""
                SELECT aw.sha1 FROM image_map im
                JOIN artwork aw ON aw.id = im.artwork_id
            """) as c:
                used_shas.update([r[0] for r in await c.fetchall()])

            art_paths = []
            root = self.art_cache_path
            if os.path.exists(root):
                for folder in os.listdir(root):
                    folder_path = os.path.join(root, folder)
                    if not os.path.isdir(folder_path): continue
                    for file in os.listdir(folder_path):
                        art_paths.append(os.path.join(folder_path, file))
            
            deleted_art = 0
            for path in art_paths:
                filename = os.path.basename(path)
                sha = os.path.splitext(filename)[0]
                
                if sha not in used_shas:
                    try:
                        os.remove(path)
                        deleted_art += 1
                    except: pass
            
            logger.info(f"Deleted {deleted_art} orphaned artwork files.")
            
            await db.execute("""
                DELETE FROM artwork
                WHERE id NOT IN (SELECT artwork_id FROM image_map)
            """)
            await db.commit()
            
            logger.info("Library Prune Complete.")

    async def update_metadata(self, artist_filter=None, mbid_filter=None, specific_fields=None, missing_only=False, bio_only=False, refresh_top_tracks=True, refresh_singles=True, fetch_metadata=True, fetch_bio=True, fetch_artwork=True, fetch_spotify_artwork=False, fetch_links=True, fetch_similar_artists=False):
        """
        Updates artist metadata using a Parallel Producer-Consumer pattern.
        """
        from app.scanner.metadata import match_track_to_library

        self.stats["current_status"] = "Updating Metadata"
        if self.scan_logger:
            self.scan_logger.emit_progress(0, 0, "Starting Metadata Update...")
        
        # Concurrency Control (Producer Limit)
        # We allow 20 concurrent network fetchers (Producers)
        # Database writes (Consumer) are batched and sequential
        semaphore = asyncio.Semaphore(20)
        
        async for db in get_db():
            # Get artists
            query = """
                SELECT a.mbid, a.name, a.updated_at, a.sort_name, a.bio, a.image_url, 
                       a.artwork_id, aw.source as art_source,
                       (SELECT url FROM external_link l WHERE l.entity_id=a.mbid AND l.type='spotify' LIMIT 1) as spotify_link_existing,
                       COALESCE(SUM(CASE WHEN el.type != 'musicbrainz' THEN 1 ELSE 0 END), 0) as link_count,
                       (SELECT COUNT(*) FROM top_track tt WHERE tt.artist_mbid=a.mbid AND tt.type='top') as top_track_count,
                       (SELECT COUNT(*) FROM top_track ts WHERE ts.artist_mbid=a.mbid AND ts.type='single') as single_count,
                       (SELECT COUNT(*) FROM similar_artist sa WHERE sa.artist_mbid=a.mbid) as similar_count
                FROM artist a
                LEFT JOIN artwork aw ON a.artwork_id = aw.id
                LEFT JOIN external_link el 
                    ON el.entity_type='artist' AND el.entity_id = a.mbid
            """
            params = []
            clauses = []
            if mbid_filter:
                if isinstance(mbid_filter, (list, set, tuple)):
                    filtered = [m for m in mbid_filter if m]
                    if filtered:
                        placeholders = ",".join(["?"] * len(filtered))
                        clauses.append(f"mbid IN ({placeholders})")
                        params.extend(filtered)
                else:
                    clauses.append("mbid = ?")
                    params.append(mbid_filter)
            elif artist_filter:
                clauses.append("name LIKE ?")
                params.append(f"%{artist_filter}%")
            # elif missing_only and not refresh_top_tracks:
            #     # Optimized filtering is risky if we are checking for specific gaps (like links)
            #     # that aren't covered by this clause. Relied on Python filter instead.
            #     pass
            
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " GROUP BY a.mbid"
            
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()

            # Helper for Gap Checking
            def has_selected_gaps(row, fetch_top, fetch_singles):
                mbid, name, updated_at, sort_name, bio, image_url, art_id_existing, art_source_existing, spotify_link_existing, link_count, top_track_count, single_count, similar_count = row
                
                # Check Explicit Missing Items
                if fetch_metadata and (not name or not str(name).strip() or not sort_name or not str(sort_name).strip()): return True
                if fetch_bio and (not bio or not str(bio).strip()): return True
                
                if fetch_artwork:
                     if not art_id_existing or not image_url: return True
                     elif art_source_existing == 'spotify': return True # Always replace spotify (low quality usually)
                
                if fetch_links and (link_count or 0) == 0: return True
                
                if fetch_top and (top_track_count or 0) == 0: return True
                if fetch_singles and (single_count or 0) == 0: return True
                
                if fetch_similar_artists and (similar_count or 0) == 0: return True

                return False

            # Filter if generic missing_only
            # Logic: If missing_only is set, we ONLY want rows where `has_selected_gaps` returns True
            # taking into account ALL requested flags.
            
            # --- PREPARE TASKS ---
            tasks_to_spawn = []
            
            for row in rows:
                mbid, name, updated_at, sort_name, bio, image_url, art_id_existing, art_source_existing, spotify_link_existing, link_count, top_track_count, single_count, similar_count = row
                if not mbid: continue

                # Logic Check
                if missing_only and not has_selected_gaps(row, refresh_top_tracks, refresh_singles):
                    continue

                eff_fetch_metadata = fetch_metadata
                eff_fetch_bio = fetch_bio
                eff_fetch_artwork = fetch_artwork
                eff_fetch_links = fetch_links
                
                # Dynamic Flags based on Gap Check (Don't re-fetch what we have)
                eff_refresh_top_tracks = refresh_top_tracks
                eff_refresh_singles = refresh_singles
                
                if missing_only:
                     if top_track_count > 0: eff_refresh_top_tracks = False
                     if single_count > 0: eff_refresh_singles = False
                eff_fetch_spotify_artwork = fetch_spotify_artwork
                eff_fetch_similar_artists = fetch_similar_artists

                has_artwork = bool(art_id_existing)
                has_fanart = has_artwork and art_source_existing == 'fanart.tv'
                has_spotify_art = has_artwork and art_source_existing == 'spotify'
                has_spotify_link = bool(spotify_link_existing)
                
                # Logic: Adjust Flags (Simplified from original for readability)
                if fetch_spotify_artwork:
                     if has_fanart: eff_fetch_spotify_artwork = False
                     if missing_only and has_spotify_art: eff_fetch_spotify_artwork = False
                     if missing_only and has_artwork: eff_fetch_spotify_artwork = False
                     
                     if has_spotify_link: eff_fetch_links = False
                     else:
                         if eff_fetch_spotify_artwork: eff_fetch_links = True
                
                has_bio = bool(bio and str(bio).strip())
                has_meta_core = bool(name and str(name).strip() and sort_name and str(sort_name).strip())
                has_links = (link_count or 0) > 0

                if missing_only:
                    if has_meta_core: eff_fetch_metadata = False
                    if has_bio: eff_fetch_bio = False
                    if has_artwork: eff_fetch_artwork = False
                    if has_links: eff_fetch_links = False
                
                any_work = any([eff_fetch_metadata, eff_fetch_bio, eff_fetch_artwork, eff_fetch_links, eff_refresh_top_tracks, eff_refresh_singles, eff_fetch_spotify_artwork, eff_fetch_similar_artists])
                
                if any_work:
                    tasks_to_spawn.append({
                        "row": row,
                        "flags": (eff_fetch_metadata, eff_fetch_bio, eff_fetch_artwork, eff_fetch_links, eff_refresh_top_tracks, eff_refresh_singles, eff_fetch_spotify_artwork, eff_fetch_similar_artists)
                    })

            total = len(tasks_to_spawn)
            logger.info(f"Found {total} artists to update.")
            processed_count = 0
            
            # --- PRODUCER-CONSUMER EXECUTION ---
            
            pending_tasks = set()
            results_buffer = []
            
            it = iter(tasks_to_spawn)
            
            async def spawn_cleanup_consume():
                # Helper to handle task management: Spawn new until max, await completed, consume results
                nonlocal processed_count
                nonlocal pending_tasks
                
                # 1. Spawn initial batch up to semaphore limit (or more? Semaphore controls execution, not task creation)
                # But we don't want 10k task objects. So we limit *pending tasks* to like 50 (2.5x semaphore).
                MAX_PENDING = 50 
                
                while True:
                    # Fill buffer
                    while len(pending_tasks) < MAX_PENDING:
                        try:
                            task_data = next(it)
                            # Create Coroutine
                            # Prepare Data needed for Producer (DB Reads happen HERE in Main Thread)
                            row = task_data["row"]
                            mbid = row[0]
                            flags = task_data["flags"]
                            eff_refresh_top_tracks, eff_refresh_singles = flags[4], flags[5]
                            eff_fetch_metadata, eff_fetch_bio, eff_fetch_links = flags[0], flags[1], flags[3]
                            eff_fetch_artwork, eff_fetch_spotify_artwork, eff_fetch_similar_artists = flags[2], flags[6], flags[7]
                            
                            # DB Read: Local RGs
                            async with db.execute("""
                                SELECT DISTINCT t.release_group_mbid 
                                FROM track t
                                JOIN track_artist ta ON t.id = ta.track_id
                                WHERE ta.artist_mbid = ? AND t.release_group_mbid IS NOT NULL
                            """, (mbid,)) as cursor:
                                local_rg_rows = await cursor.fetchall()
                                local_release_group_ids = {r[0] for r in local_rg_rows}

                            # DB Read: Missing Only Top/Singles Check
                            if missing_only and (eff_refresh_top_tracks or eff_refresh_singles):
                                 async with db.execute("SELECT type, count(*) FROM top_track WHERE artist_mbid=? GROUP BY type", (mbid,)) as cursor:
                                     rows_top = await cursor.fetchall()
                                     has_top_tracks = False
                                     has_singles = False
                                     for r_type, r_count in rows_top:
                                         if r_type == 'top' and r_count > 0: has_top_tracks = True
                                         if r_type == 'single' and r_count > 0: has_singles = True
                                     
                                     if has_top_tracks: eff_refresh_top_tracks = False
                                     if has_singles: eff_refresh_singles = False

                                     # Update Flags
                                     flags = (flags[0], flags[1], flags[2], flags[3], eff_refresh_top_tracks, eff_refresh_singles, flags[6], flags[7])
                            
                            # DB Read: Wikipedia
                            known_wikipedia_url = None
                            is_bio_only = eff_fetch_bio and not any([eff_fetch_metadata, eff_fetch_links, eff_fetch_artwork, eff_fetch_spotify_artwork, eff_refresh_top_tracks, eff_refresh_singles])
                            if is_bio_only:
                                async with db.execute("SELECT url FROM external_link WHERE entity_type='artist' AND entity_id=? AND type='wikipedia'", (mbid,)) as cursor:
                                    row_wiki = await cursor.fetchone()
                                    if row_wiki: known_wikipedia_url = row_wiki[0]

                            # Spawn Task
                            task = asyncio.create_task(self._produce_metadata_update(
                                semaphore, row, flags, local_release_group_ids, known_wikipedia_url
                            ))
                            pending_tasks.add(task)
                        
                        except StopIteration:
                            break
                    
                    if not pending_tasks:
                        break
                        
                    # Wait for at least one
                    done, pending_tasks = await asyncio.wait(pending_tasks, return_when=asyncio.FIRST_COMPLETED)
                    
                    for t in done:
                        try:
                            res = await t
                            if res: results_buffer.append(res)
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            logger.error(f"Task failed: {e}")
                            
                    # Batch Write
                    if len(results_buffer) >= 50:
                        await self._consume_metadata_update(db, results_buffer)
                        await db.commit()
                        processed_count += len(results_buffer)
                        
                        if self.scan_logger:
                             # Just use last item name for logs
                             last_name = results_buffer[-1]["row"][1] or "Unknown"
                             self.scan_logger.emit_progress(processed_count, total, f"Metadata: {last_name} (Batch)")
                        
                        results_buffer.clear()
                        
            await spawn_cleanup_consume()
            
            # Flush final buffer
            if results_buffer:
                await self._consume_metadata_update(db, results_buffer)
                await db.commit()
                processed_count += len(results_buffer)
                if self.scan_logger:
                    self.scan_logger.emit_progress(processed_count, total, f"Metadata: Complete")

            logger.info(f"Metadata update complete. Processed {processed_count} artists.")

    async def _produce_metadata_update(self, semaphore, row, flags, local_release_group_ids, known_wikipedia_url):
         eff_fetch_metadata, eff_fetch_bio, eff_fetch_artwork, eff_fetch_links, eff_refresh_top_tracks, eff_refresh_singles, eff_fetch_spotify_artwork, eff_fetch_similar_artists = flags
         mbid, name, updated_at, sort_name, bio, image_url, art_id_existing, art_source_existing, spotify_link_existing, link_count, top_track_count, single_count, similar_count = row
         
         if self._stop_event.is_set(): return None

         async with semaphore:
             # Call fetch_artist_metadata
             # Note: fetch_artist_metadata only does READS (Network).
             meta = await fetch_artist_metadata(
                mbid,
                name,
                local_release_group_ids=local_release_group_ids,
                bio_only=(eff_fetch_bio and not any([eff_fetch_metadata, eff_fetch_links, eff_fetch_artwork, eff_fetch_spotify_artwork, eff_refresh_top_tracks, eff_refresh_singles])),
                fetch_metadata=eff_fetch_metadata,
                fetch_bio=eff_fetch_bio,
                fetch_artwork=eff_fetch_artwork,
                fetch_spotify_artwork=eff_fetch_spotify_artwork,
                fetch_links=eff_fetch_links,
                fetch_top_tracks=eff_refresh_top_tracks,
                fetch_singles=eff_refresh_singles,
                known_wikipedia_url=known_wikipedia_url,
                known_spotify_url=spotify_link_existing,
                fetch_similar_artists=eff_fetch_similar_artists,
             )
             
             # Download artwork (Disk I/O + Network)
             art_download = None
             bg_download = None
             
             if not self._stop_event.is_set():
                 if eff_fetch_artwork and meta.get("image_url"):
                      art_download = await download_and_save_artwork(meta["image_url"], art_type='artistthumb')
                 if eff_fetch_artwork and meta.get("background_url"):
                      bg_download = await download_and_save_artwork(meta["background_url"], art_type='artistbackground')

             return {
                 "row": row,
                 "flags": flags,
                 "meta": meta,
                 "art_download": art_download,
                 "bg_download": bg_download
             }

    async def _consume_metadata_update(self, db, results):
        from app.scanner.metadata import match_track_to_library
        
        for res in results:
            row = res["row"]
            flags = res["flags"]
            meta = res["meta"]
            art_download = res["art_download"]
            bg_download = res["bg_download"]
            
            mbid, name, updated_at, sort_name, bio, image_url, art_id_existing, art_source_existing, spotify_link_existing, link_count, top_track_count, single_count, similar_count = row
            eff_fetch_metadata, eff_fetch_bio, eff_fetch_artwork, eff_fetch_links, eff_refresh_top_tracks, eff_refresh_singles, eff_fetch_spotify_artwork, eff_fetch_similar_artists = flags

            # 1. Upsert Artwork
            artwork_id = art_id_existing
            if art_download:
                artwork_id = await upsert_artwork_record(
                    db,
                    art_download.get("sha1"),
                    meta=art_download.get("meta"),
                    source=meta.get("image_source"),
                    source_url=art_download.get("source_url") or meta.get("image_url"),
                )
                if artwork_id:
                     await upsert_image_mapping(db, artwork_id, "artist", mbid, "artistthumb", meta.get("image_score"))
            
            bg_art_id = None
            if bg_download:
                bg_art_id = await upsert_artwork_record(
                    db,
                    bg_download.get("sha1"),
                    meta=bg_download.get("meta"),
                    source=meta.get("background_source"),
                    source_url=bg_download.get("source_url") or meta.get("background_url"),
                )
                if bg_art_id:
                    await upsert_image_mapping(db, bg_art_id, "artist", mbid, "artistbackground", meta.get("background_score"))

            # 2. Update Artist Core
            await db.execute("""
                UPDATE artist SET 
                    name=CASE WHEN (name IS NULL OR name = '') THEN ? ELSE name END,
                    sort_name=CASE WHEN (sort_name IS NULL OR sort_name = '') THEN ? ELSE sort_name END,
                    bio=COALESCE(?, bio),
                    image_url=COALESCE(?, image_url),
                    artwork_id=COALESCE(?, artwork_id),
                    updated_at=?
                WHERE mbid=?
            """, (
                meta.get("name") if eff_fetch_metadata else name,
                meta.get("sort_name") if eff_fetch_metadata else sort_name,
                meta.get("bio") if eff_fetch_bio else bio,
                meta.get("image_url") if eff_fetch_artwork else image_url,
                artwork_id,
                meta.get("updated_at") or time.time(),
                mbid
            ))
            
            # 3. External Links
            if eff_fetch_links:
                await db.execute("DELETE FROM external_link WHERE entity_type='artist' AND entity_id=?", (mbid,))
                artist_links = []
                try:
                    from app.config import get_musicbrainz_root_url
                    mb_url = f"{get_musicbrainz_root_url()}/artist/{mbid}"
                    artist_links.append(("musicbrainz", mb_url))
                except: pass
                
                if meta.get("spotify_url"): artist_links.append(("spotify", meta["spotify_url"]))
                if meta.get("tidal_url"): artist_links.append(("tidal", meta["tidal_url"]))
                if meta.get("qobuz_url"): artist_links.append(("qobuz", meta["qobuz_url"]))
                if meta.get("wikipedia_url"): artist_links.append(("wikipedia", meta["wikipedia_url"]))
                if meta.get("homepage"): artist_links.append(("homepage", meta["homepage"]))
                if meta.get("lastfm_url"): artist_links.append(("lastfm", meta["lastfm_url"]))
                if meta.get("discogs_url"): artist_links.append(("discogs", meta["discogs_url"]))
                
                for l_type, l_url in artist_links:
                    await db.execute("INSERT OR IGNORE INTO external_link (entity_type, entity_id, type, url) VALUES (?, ?, ?, ?)", 
                                     ('artist', mbid, l_type, l_url))

            # 4. Top Tracks
            should_refresh = eff_refresh_top_tracks and not SPOTIFY_SCANNING_DISABLED
            if should_refresh:
                 await db.execute("DELETE FROM top_track WHERE artist_mbid=? AND type='top'", (mbid,))
                 for idx, track in enumerate(meta.get("top_tracks", [])):
                        track_id = await match_track_to_library(
                            db, mbid, track["name"], track.get("album"), track.get("mbid")
                        )
                        await db.execute("""
                            INSERT OR REPLACE INTO top_track 
                            (artist_mbid, type, track_id, external_name, external_album, 
                             external_date, external_duration_ms, popularity, rank, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (mbid, 'top', track_id, track["name"], track.get("album"), 
                              track.get("date"), track.get("duration_ms"), track.get("popularity"), idx + 1, time.time()))

            # 5. Singles
            if eff_refresh_singles:
                 await db.execute("DELETE FROM top_track WHERE artist_mbid=? AND type='single'", (mbid,))
                 for single in meta.get("singles", []):
                        track_id = await match_track_to_library(
                            db, mbid, single["title"], None
                        )
                        await db.execute("""
                            INSERT OR REPLACE INTO top_track 
                            (artist_mbid, type, track_id, external_name, external_album, 
                             external_date, external_mbid, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (mbid, 'single', track_id, single["title"], single.get("album"),
                              single["date"], single.get("mbid"), time.time()))

            # 6. Similar Artists
            if eff_fetch_similar_artists:
                 await db.execute("DELETE FROM similar_artist WHERE artist_mbid=?", (mbid,))
                 for idx, similar_item in enumerate(meta.get("similar_artists", [])):
                        sim_name = similar_item.get("name") if isinstance(similar_item, dict) else similar_item
                        sim_mbid = similar_item.get("mbid") if isinstance(similar_item, dict) else None
                        if not sim_name: continue
                        
                        if not sim_mbid:
                             async with db.execute("SELECT mbid FROM artist WHERE LOWER(TRIM(name)) = ? LIMIT 1", (sim_name.lower().strip(),)) as c:
                                 row_sim = await c.fetchone()
                                 if row_sim: sim_mbid = row_sim[0]

                        await db.execute("""
                            INSERT OR REPLACE INTO similar_artist
                            (artist_mbid, similar_artist_name, similar_artist_mbid, rank, updated_at)
                            VALUES (?, ?, ?, ?, ?)
                        """, (mbid, sim_name, sim_mbid, idx + 1, time.time()))
            
            # 7. Genres
            if meta.get("genres"):
                 await db.execute("DELETE FROM artist_genre WHERE artist_mbid=?", (mbid,))
                 for g in meta["genres"]:
                      await db.execute("INSERT INTO artist_genre (artist_mbid, genre, count, updated_at) VALUES (?, ?, ?, ?)", 
                                       (mbid, g["name"], g["count"], time.time()))

            # 8. Albums (Release Groups)
            all_releases = meta.get("albums", []) + meta.get("singles", [])
            # We don't delete existing artist_albums blindly because we might lose primary links from scan?
            # Actually core scan populates 'primary'. This populates metadata.
            # Safe to overwrite if we have better data.
            # But the logic in original was: DELETE FROM artist_album WHERE artist_mbid...
            # Original logic:
            # await db.execute("DELETE FROM artist_album WHERE artist_mbid=?", (mbid,))
            if eff_fetch_metadata: # Only if we fetched albums
                # await db.execute("DELETE FROM artist_album WHERE artist_mbid=?", (mbid,))
                pass
                
                for release in all_releases:
                    r_mbid, r_title, r_date = release["mbid"], release["title"], release["date"]
                    r_links = release.get("links") or []
                    r_release_ids = release.get("release_ids") or []
                    r_primary_release = release.get("primary_release_id")
                    
                    # Tagged Priority
                    tagged_release_ids = []
                    async with db.execute("SELECT DISTINCT release_mbid FROM track WHERE release_group_mbid = ? AND release_mbid IS NOT NULL", (r_mbid,)) as cursor:
                         rows_tagged = await cursor.fetchall()
                         tagged_release_ids = [r[0] for r in rows_tagged if r[0]]
                    if tagged_release_ids:
                        r_primary_release = tagged_release_ids[0]
                        r_release_ids = tagged_release_ids
                    
                    await db.execute("""
                        INSERT INTO album (mbid, title, release_date, primary_type, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(mbid) DO UPDATE SET title=excluded.title, release_date=excluded.release_date, updated_at=excluded.updated_at
                    """, (r_mbid, r_title, r_date, 'Album', time.time()))

                    if r_release_ids:
                        placeholders = ",".join("?" * len(r_release_ids))
                        await db.execute(f"UPDATE track SET release_group_mbid=? WHERE release_mbid IN ({placeholders})", (r_mbid, *r_release_ids))
                    
                    await db.execute("INSERT OR IGNORE INTO artist_album (artist_mbid, album_mbid, type) VALUES (?, ?, ?)", (mbid, r_mbid, 'primary'))
                    
                    # Links
                    from app.config import get_musicbrainz_root_url
                    mb_release_link = None
                    if r_primary_release: 
                        mb_release_link = f"{get_musicbrainz_root_url()}/release/{r_primary_release}"
                    elif r_release_ids: 
                        mb_release_link = f"{get_musicbrainz_root_url()}/release/{r_release_ids[0]}"
                    else:
                        mb_release_link = f"{get_musicbrainz_root_url()}/release-group/{r_mbid}"

                    link_payloads = []
                    if mb_release_link: link_payloads.append({"type": "musicbrainz", "url": mb_release_link})
                    link_payloads.extend(r_links)
                    
                    await db.execute("DELETE FROM external_link WHERE entity_type='album' AND entity_id=?", (r_mbid,))
                    for link in link_payloads:
                        await db.execute("INSERT OR IGNORE INTO external_link (entity_type, entity_id, type, url) VALUES (?, ?, ?, ?)", ("album", r_mbid, link["type"], link["url"]))

    async def update_links(self, artist_filter=None, mbid_filter=None):
        """
        Updates ONLY the external links (Tidal, Qobuz, Wikipedia, Spotify) by refetching MB.
        Can filter by artist name (--artist) or MusicBrainz ID (--mbid).
        """
        self.stats["current_status"] = "Updating Links"
        # Similar reuse of fetch_artist_metadata but we might want to optimize to NOT fetch everything?
        # Actually fetch_artist_metadata is generic enough, let's just reuse update_metadata logic 
        # but maybe we can ensure we overwrite links even if they exist (force refresh).
        # The update_metadata SQL uses COALESCE so it won't overwrite valid with null, 
        # but if we want to Refresh links, we probably want to update them regardless.
        # But for Phase 1, simply calling update_metadata is likely sufficient as it fetches fresh data.
        await self.update_metadata(artist_filter=artist_filter, mbid_filter=mbid_filter, refresh_top_tracks=False)

    async def rematch_tracks_top(self, artist_mbids: set):
        """
        Re-run matching of existing top tracks/singles to local library for the given artists.
        Only fills missing track_id values using current library contents.
        """
        artist_ids = {mb for mb, _ in artist_mbids if mb} if artist_mbids else set()
        if not artist_ids:
            return

        async for db in get_db():
            from app.scanner.metadata import match_track_to_library
            for mbid in artist_ids:
                async with db.execute("""
                    SELECT id, external_name, external_album
                    FROM top_track
                    WHERE artist_mbid = ? AND track_id IS NULL
                """, (mbid,)) as cursor:
                    rows = await cursor.fetchall()

                if not rows:
                    continue

                for row in rows:
                    tt_id, name, album = row
                    track_id = await match_track_to_library(db, mbid, name, album)
                    if track_id:
                        await db.execute(
                            "UPDATE top_track SET track_id = ?, updated_at = ? WHERE id = ?",
                            (track_id, time.time(), tt_id),
                        )
            await db.commit()

    async def scan_missing_albums(self, artist_filter=None, mbid_filter=None):
        """
        Scans for missing albums (Release Groups) from MusicBrainz for local artists.
        Populates missing_albums table.
        """
        self.stats["current_status"] = "Scanning Missing Albums"
        logger.info("Starting Missing Albums Scan...")

        from app.scanner.metadata import fetch_artist_release_groups, fetch_best_release_match
        import httpx

        async for db in get_db():
            # 1. Get List of Artists to Check
            # Filter: Must be a primary artist on at least one album (present in artist_albums)
            # UNLESS we are specifically asking for an artist/mbid
            
            query = "SELECT DISTINCT a.mbid, a.name FROM artist a"
            params = []
            clauses = []
            joins = []
            
            if mbid_filter:
               if isinstance(mbid_filter, (list, set, tuple)):
                   filtered = [m for m in mbid_filter if m]
                   if filtered:
                       placeholders = ",".join(["?"] * len(filtered))
                       clauses.append(f"a.mbid IN ({placeholders})")
                       params.extend(filtered)
               else:
                   clauses.append("a.mbid = ?")
                   params.append(mbid_filter)
            elif artist_filter:
                clauses.append("a.name LIKE ?")
                params.append(f"%{artist_filter}%")
            else:
                # Only enforce "has albums" rule if doing a bulk scan
                joins.append("JOIN artist_album aa ON a.mbid = aa.artist_mbid")
            
            if joins:
                query += " " + " ".join(joins)
            
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
                
            async with db.execute(query, params) as cursor:
                artists = await cursor.fetchall()

            total = len(artists)
            processed = 0
            
            async with httpx.AsyncClient(headers={"User-Agent": "Jamarr/0.1 ( jamarr@example.com )"}) as client:
                for row in artists:
                    if self._stop_event.is_set(): break
                    
                    mbid, name = row
                    current_name = name or "Unknown"
                    if self.scan_logger:
                         self.scan_logger.emit_progress(processed, total, f"Checking: {current_name}")
                    
                    # Initialize Tidal Client (re-use or init once per scanner?)
                    # Init per artist or once outside? Init is cheap.
                    tidal_client = TidalClient()

                    # 2. Get Local Release Group IDs (from album table)
                    # We check the albums table but via artist_albums to be sure we attribute correctly
                    async with db.execute("""
                        SELECT album_mbid FROM artist_album WHERE artist_mbid = ?
                    """, (mbid,)) as cursor:
                        local_rgs = {r[0] for r in await cursor.fetchall()}



                    # 3. Clear Old Missing entries for this artist
                    await db.execute("DELETE FROM missing_album WHERE artist_mbid = ?", (mbid,))
                    
                    # 4. Fetch All Release Groups from MB
                    try:
                        # Fetch Albums
                        mb_albums = await fetch_artist_release_groups(mbid, "album", client)
                        # Fetch Singles (?) - User said "albums only, no eps" but MB calls them singles sometimes
                        # User request: "albums only, no eps, no album+ live etc.."
                        # fetch_artist_release_groups already filters out secondary types (Live, etc)
                        # We just need to stick to "album" type_str.
                        
                        for album in mb_albums:
                            rg_id = album["mbid"]
                            
                            if rg_id in local_rgs:
                                continue # We have it
                                
                            # It is missing!
                            # Resolve Links (Tidal, Qobuz)
                            # This is the "slow" part
                            match = await fetch_best_release_match(rg_id, client)
                            
                            tidal_url = None
                            qobuz_url = None
                            
                            for link in match.get("links", []):
                                if link["type"] == "tidal": tidal_url = link["url"]
                                elif link["type"] == "qobuz": qobuz_url = link["url"]
                            
                            # Fallback: Search Tidal directly
                            if not tidal_url:
                                try:
                                    want_year = year_from_date(album.get("date"))
                                    found_url = tidal_client.find_album_match(current_name, album["title"], want_year)
                                    if found_url:
                                        tidal_url = found_url
                                        data_source = "Tidal Search"
                                        # logger.info(f"Found Tidal URL for {current_name} - {album['title']}: {tidal_url}")
                                except Exception as e:
                                    logger.debug(f"Tidal fallback search failed: {e}")

                            # Insert into missing_album
                            await db.execute("""
                                INSERT OR REPLACE INTO missing_album
                                (artist_mbid, release_group_mbid, title, release_date, primary_type, image_url, musicbrainz_url, tidal_url, qobuz_url, updated_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                mbid, rg_id, album["title"], album["date"], 'Album', 
                                None, # Image URL? We didn't fetch cover art, maybe unnecessary for list? Or use placeholder.
                                album.get("musicbrainz_url"),
                                tidal_url, qobuz_url,
                                time.time()
                            ))
                            
                        await db.commit()
                        
                    except Exception as e:
                        logger.error(f"Error checking missing albums for {current_name}: {e}")
                    
                    processed += 1
 
