import os
import asyncio
import logging
import difflib
import re
import shlex
import httpx
from datetime import datetime, timezone

try:
    from blake3 import blake3
except ImportError:
    import hashlib
    def blake3(data=b""):
        return hashlib.sha256(data)

from app.db import get_db
from app.scanner.tags import extract_tags
from app.scanner.stats import get_api_tracker
# DNS resolver imported lazily in warm_dns_cache() to avoid loading aiodns in web server
from app.scanner.artwork import (
    extract_and_save_artwork,
    upsert_artwork_record,
    upsert_image_mapping,
)
from app.config import get_music_path, get_max_workers
from app.scanner.album_helpers import upsert_artist_album

logger = logging.getLogger("scanner.core")

SUPPORTED_EXTENSIONS = {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aiff"}

async def match_track_to_library(db, artist_mbid, track_name, album_name=None, external_mb_track_id=None):
    """
    Match external track to local library track using fuzzy matching with dynamic weighting.
    Moved from metadata.py.
    """
    query = """
        SELECT t.id, t.title, t.album, t.duration_seconds, t.track_mbid, t.release_track_mbid, t.release_date, t.release_type
        FROM track t
        JOIN track_artist ta ON t.id = ta.track_id
        WHERE ta.artist_mbid = $1 
    """
    candidates = await db.fetch(query, artist_mbid)

    if not candidates:
        return None

    if external_mb_track_id:
        for row in candidates:
            # row is Record, access by index or name if using Record (asyncpg returns Record)
            # unpacking:
            cid, ctitle, calbum, cseconds, cmb_track_id, cmb_release_track_id, cdate, ctype = row
            if (cmb_track_id == external_mb_track_id or cmb_release_track_id == external_mb_track_id):
                return cid

    def normalize(s):
        if not s:
            return ""
        s = s.lower().strip()
        s = re.sub(r"[\(\[][^\)\]]*(feat|with|remast|deluxe|edit|mix)[^\)\]]*[\)\]]", "", s)
        s = re.sub(r"[^\w\s]", "", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def fuzzy_score(s1, s2):
        return difflib.SequenceMatcher(None, normalize(s1), normalize(s2)).ratio()

    def normalize_date(d):
        # d is likely datetime.date or None from DB, or str if legacy
        if not d:
            return None
        if isinstance(d, str):
            d_str = d.strip()
            if len(d_str) == 4 and d_str.isdigit():
                return f"{d_str}-01-01"
            if len(d_str) == 7 and d_str.replace("-","").isdigit():
                return f"{d_str}-01"
            if len(d_str) >= 10:
                return d_str[:10]
            return None
        # If it's date object, return ISO string
        return d.isoformat()

    TYPE_PRIORITY = {
        "single": 1,
        "ep": 2,
        "album": 3,
        "compilation": 4,
        "other": 5, 
        "live": 6
    }
    
    def get_type_priority(t_str):
        if not t_str:
            return 5 # Treat None as 'other'
        t_lower = t_str.lower()
        return TYPE_PRIORITY.get(t_lower, 5) # Default to 5 (Other)

    best_score = 0
    best_match = None
    best_date = None
    best_priority = 100 # Lower is better

    for row in candidates:
        cid, ctitle, calbum, cseconds, cmb_track_id, cmb_release_track_id, cdate, ctype = row

        total_weight = 0.6
        current_score = 0
        
        t_score = fuzzy_score(track_name, ctitle)
        if t_score < 0.6:
            continue
        current_score += t_score * 0.6

        if album_name and calbum:
            total_weight += 0.2
            a_score = fuzzy_score(album_name, calbum)
            current_score += a_score * 0.2

        final_score = current_score / total_weight
        norm_date = normalize_date(cdate)
        priority = get_type_priority(ctype)

        # Logic: 
        # 1. Higher Score wins
        # 2. Tie (< 0.001 diff):
        #    a. Lower Priority wins (Single < Album)
        #    b. Same Priority: Earlier Date wins
        
        if final_score > (best_score + 0.001):
            # Clearly better score
            best_score = final_score
            best_match = cid
            best_date = norm_date
            best_priority = priority
        elif abs(final_score - best_score) <= 0.001 and best_score > 0:
            # Check Priority
            if priority < best_priority:
                best_match = cid
                best_date = norm_date
                best_priority = priority
                # Keep best_score as is (they are tied)
            elif priority == best_priority:
                # Check Date
                if norm_date and best_date:
                    if norm_date < best_date:
                        best_match = cid
                        best_date = norm_date
                elif norm_date and not best_date:
                     best_match = cid
                     best_date = norm_date

    if best_score > 0.75:
        return best_match
    return None

class Scanner:
    def __init__(self):
        self._stop_event = asyncio.Event()
        self.stats = {
            "scanned": 0, "added": 0, "updated": 0, "errors": 0, 
            "total_estimate": 0, "current_status": "Idle", "skipped": 0
        }
        self.scan_logger = None
        self.art_cache_path = "cache/art"
        self._db_files_cache = {}  # path -> (mtime, size_bytes, quick_hash)
        self._processed_artists_session = set()
        self._batch_counter = 0
        self._batch_size = 100

    def _compute_quick_hash(self, path: str, mtime: float, size: int) -> bytes:
        """
        Compute BLAKE3-256 Quick Hash logic.
        Hash(first 16KB + last 16KB + size + mtime)
        """
        try:
            hasher = blake3()
            hasher.update(str(size).encode())
            hasher.update(str(mtime).encode())
            
            with open(path, "rb") as f:
                chunk_size = 16 * 1024
                # First 16KB
                hasher.update(f.read(chunk_size))
                
                # Last 16KB
                if size > chunk_size:
                    f.seek(max(chunk_size, size - chunk_size))
                    hasher.update(f.read(chunk_size))
            
            return hasher.digest()
        except Exception as e:
            logger.warning(f"Failed to compute hash for {path}: {e}")
            return None

    async def scan_filesystem(self, root_path: str = None, force_rescan: bool = False):
        if root_path is None:
            root_path = get_music_path()

        if not os.path.exists(root_path):
            error_msg = f"Scan path not found: {root_path}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        self.stats = {
            "scanned": 0, "added": 0, "updated": 0, "errors": 0, 
            "total_estimate": 0, "current_status": "Scanning", "skipped": 0
        }
        self._stop_event.clear()
        self._processed_artists_session = set()
        
        logger.info(f"Starting scan of {root_path} (Force: {force_rescan})")
        
        # Estimate
        count_task = asyncio.create_task(self._estimate_file_count(root_path))
        
        # Load Cache for Change Detection
        self.stats["current_status"] = "Loading DB Cache..."
        self._db_files_cache = {}
        async for db in get_db():
            # Fetch mtime, size, quick_hash from existing tracks
            query = "SELECT path, mtime, size_bytes, quick_hash FROM track"
            rows = await db.fetch(query)
            for r in rows:
                self._db_files_cache[r["path"]] = (r["mtime"], r["size_bytes"], r["quick_hash"])
            break # Only need one connection to load
            
        self.stats["total_estimate"] = await count_task
        logger.info(f"Estimated file count: {self.stats['total_estimate']}")
        
        artist_mbids = set()
        seen_paths = set()
        
        self.stats["current_status"] = "Scanning Files"
        await self._scan_recursive(root_path, artist_mbids, seen_paths, force_rescan)
        
        self.stats["current_status"] = "Cleaning Orphans"
        async for db in get_db():
            await self._cleanup_orphans(db, root_path, seen_paths)
            
            # Ensure Artists Exist
            rows = await db.fetch("SELECT DISTINCT artist_mbid FROM track_artist")
            db_mbids = {r[0] for r in rows if r[0]}
            all_mbids = db_mbids.union({m[0] for m in artist_mbids if m[0]})
            
            logger.info(f"Ensuring {len(all_mbids)} artists exist in database...")
            for mbid in all_mbids:
                await db.execute("INSERT INTO artist (mbid) VALUES ($1) ON CONFLICT (mbid) DO NOTHING", mbid)
                
            if all_mbids:
                await self._apply_artist_name_consensus(db, all_mbids)
                
            # Fallback
            for mbid, name in artist_mbids:
                if mbid and name:
                     await db.execute("UPDATE artist SET name = $1 WHERE mbid = $2 AND (name IS NULL OR name = '')", name, mbid)

        self._db_files_cache = {}
        self._processed_artists_session = set()
        
        logger.info(f"Scanner finished: {self.stats}")
        return artist_mbids

    async def _scan_recursive(self, root, artist_mbids, seen_paths, force_rescan):
        if self._stop_event.is_set():
            return
        
        queue = asyncio.Queue()
        queue.put_nowait(root)
        num_workers = max(1, int(get_max_workers() or 5))
        
        async def worker():
            async for db in get_db():
                while True:
                    try:
                        path = await queue.get()
                        try:
                            if self._stop_event.is_set():
                                continue

                            with os.scandir(path) as it:
                                entries = sorted(list(it), key=lambda e: e.name.lower())
                                

                            for entry in entries:
                                if entry.is_dir():
                                    queue.put_nowait(entry.path)
                                elif entry.is_file():
                                    ext = os.path.splitext(entry.name)[1].lower()
                                    if ext in SUPPORTED_EXTENSIONS:
                                        seen_paths.add(entry.path)
                                        self.stats["scanned"] += 1
                                        if self.scan_logger and self.stats["scanned"] % 50 == 0:
                                            self.scan_logger.emit_progress(
                                                self.stats["scanned"], self.stats["total_estimate"], f"Scanning {entry.name}"
                                            )
                                        
                                        await self._process_file(entry.path, db, artist_mbids, force_rescan, entry=entry)
                        except Exception as e:
                            logger.error(f"Error scanning {path}: {e}")
                        finally:
                            queue.task_done()
                    except asyncio.CancelledError:
                        break

        workers = [asyncio.create_task(worker()) for _ in range(num_workers)]
        await queue.join()
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    async def _process_file(self, path, db, artist_mbids, force_rescan, entry=None):
        try:
            music_root = get_music_path()
            rel_path = os.path.relpath(path, music_root)
            
            if entry:
                stat = entry.stat()
            else:
                stat = os.stat(path)
                
            mtime = stat.st_mtime
            size = stat.st_size
            curr_hash = None
            
            # Change Detection Logic
            changed = True
            cached = self._db_files_cache.get(rel_path)
            
            if not force_rescan and cached:
                c_mtime, c_size, c_hash = cached
                
                # Check 1: Mtime + Size
                # Mtime comparison with 1ms tolerance
                mtime_match = c_mtime is not None and abs(c_mtime - mtime) < 0.001
                size_match = c_size is not None and c_size == size
                
                if mtime_match and size_match:
                    if c_hash:
                        # All signatures match and we already have a quick_hash -> skip
                        changed = False
                    else:
                        # Missing quick_hash; compute once so we can persist it
                        curr_hash = await asyncio.to_thread(self._compute_quick_hash, path, mtime, size)
                        changed = True
            else:
                 curr_hash = await asyncio.to_thread(self._compute_quick_hash, path, mtime, size)

            if changed and curr_hash is None:
                 curr_hash = await asyncio.to_thread(self._compute_quick_hash, path, mtime, size)

            if not changed:
                self.stats["skipped"] += 1
                return
                
            # Changed or New
            tags = await asyncio.to_thread(extract_tags, path)
            if not tags:
                return

            # Strict MBID Check
            # Plan: "If artist_mbid or release_group_mbid missing -> Log Warning & SKIP"
            artist_mbid = tags.get("artist_mbid")
            rg_mbid = tags.get("release_group_mbid")
            
            if not artist_mbid or not rg_mbid:
                logger.warning(f"Skipping {rel_path}: Missing MBIDs (Artist: {artist_mbid}, RG: {rg_mbid})")
                return # Skip indexing

            # Upsert Artwork
            art_result = await extract_and_save_artwork(path)
            artwork_id = None
            if art_result:
                artwork_id = await upsert_artwork_record(db, art_result.get("sha1"), meta=art_result.get("meta"))
                
            # Upsert Track
            # Upsert Track
            
            # Map tags to columns
            cols = {
                "path": rel_path,
                "updated_at": datetime.now(timezone.utc),
                "mtime": mtime,
                "size_bytes": size,
                "quick_hash": curr_hash,
                "title": tags.get("title"),
                "artist": tags.get("artist"),
                "album": tags.get("album"),
                "album_artist": tags.get("album_artist"),
                "track_no": tags.get("track_no"),
                "disc_no": tags.get("disc_no"),
                "release_date": tags.get("release_date"),
                "duration_seconds": tags.get("duration_seconds"),
                "codec": tags.get("codec"),
                "sample_rate_hz": tags.get("sample_rate_hz"),
                "bit_depth": tags.get("bit_depth"),
                "bitrate": tags.get("bitrate"),
                "channels": tags.get("channels"),
                "label": tags.get("label"),
                "artist_mbid": artist_mbid,
                "album_artist_mbid": tags.get("album_artist_mbid"),
                "track_mbid": tags.get("track_mbid"),
                "release_track_mbid": tags.get("release_track_mbid"),
                "release_mbid": tags.get("release_mbid"),
                "release_group_mbid": rg_mbid,
                "artwork_id": artwork_id,
                "release_type": tags.get("release_type"),
                "release_type_raw": tags.get("release_type_raw"),
                "release_date_raw": tags.get("release_date_raw"),
                "release_date_tag": tags.get("release_date_tag"),
            }


            keys = list(cols.keys())
            vals = list(cols.values())
            placeholders = ", ".join([f"${i+1}" for i in range(len(keys))])
            
            # Dynamic Update Set
            set_clause = ", ".join([f"{k}=excluded.{k}" for k in keys if k != "path"])
            
            sql = f"INSERT INTO track ({', '.join(keys)}) VALUES ({placeholders}) ON CONFLICT(path) DO UPDATE SET {set_clause} RETURNING id"
            track_id = await db.fetchval(sql, *vals)
            
            if cached:
                self.stats["updated"] += 1
            else:
                self.stats["added"] += 1
                
            get_api_tracker().track_processed("tracks", track_id)
            
            # Mapping Art
            if artwork_id:
                if rg_mbid:
                    await upsert_image_mapping(db, artwork_id, "album", rg_mbid, "album")
                else:
                    await upsert_image_mapping(db, artwork_id, "track", track_id, "album")

            # Update Album and Artists
            # Update Album and Artists
            if rg_mbid:
                # Sync album date/type with track
                # UPDATED: Use Release ID as Album PK, but keep RG ID for grouping
                album_pk = tags.get("release_mbid")
                rg_mbid = tags.get("release_group_mbid")
                
                if album_pk and rg_mbid:
                    await db.execute("""
                        INSERT INTO album (mbid, release_group_mbid, title, release_date, release_type, release_type_raw, artwork_id, updated_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                        ON CONFLICT(mbid) DO UPDATE SET 
                            title=COALESCE(excluded.title, album.title),
                            release_group_mbid=excluded.release_group_mbid,
                            release_date=excluded.release_date,
                            release_type=excluded.release_type,
                            release_type_raw=excluded.release_type_raw,
                            updated_at=NOW()
                    """, album_pk, rg_mbid, tags.get("album"), tags.get("release_date"), tags.get("release_type"), tags.get("release_type_raw"), artwork_id)
                    get_api_tracker().track_processed("albums", album_pk)
                
            await self._process_track_artists(db, track_id, tags, artist_mbids, album_pk)
            
        except Exception as e:
            logger.error(f"Failed to process {path}: {e}")
            self.stats["errors"] += 1

    async def _process_track_artists(self, db, track_id, tags, artist_mbids, album_mbid=None):
        await db.execute("DELETE FROM track_artist WHERE track_id = $1", track_id)
        
        def extract_ids(raw):
            if not raw:
                return []
            cleaned = raw.replace("/", ";").replace("&", ";")
            return [x.strip() for x in cleaned.split(";") if x.strip()]

        aa_ids = extract_ids(tags.get("album_artist_mbid"))
        ids = list(dict.fromkeys(extract_ids(tags.get("artist_mbid"))))
        
        for mbid in ids:
            name = tags.get("artist") if len(ids) == 1 else None
            # We track (mbid, name) to ensure we have name info for final fallback
            artist_mbids.add((mbid, name))
            
            # Ensure artist exists to satisfy FK
            await db.execute("""
                INSERT INTO artist (mbid, name, updated_at) VALUES ($1, $2, NOW()) 
                ON CONFLICT (mbid) DO UPDATE SET 
                    name = COALESCE(artist.name, excluded.name),
                    updated_at = NOW()
            """, mbid, name)

            await db.execute("""
                INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, $2) ON CONFLICT DO NOTHING
            """, track_id, mbid)
            get_api_tracker().track_processed("artists", mbid)
            
            # Link to Album
            if album_mbid:
                type_ = "primary" if mbid in aa_ids else "contributor"
                await upsert_artist_album(db, mbid, album_mbid, type_)

    async def _estimate_file_count(self, root_path):
        safe_root = shlex.quote(root_path)
        clauses = [f"-iname '*{ext}'" for ext in SUPPORTED_EXTENSIONS]
        or_clause = " -o ".join(clauses)
        cmd = f"find {safe_root} -type f \\( {or_clause} \\) -print | wc -l"
        try:
            proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, _ = await proc.communicate()
            if stdout:
                return int(stdout.decode().strip())
        except Exception:
            pass
        return 0

    async def _cleanup_orphans(self, db, root_path, seen_paths):
         if not seen_paths:
             return
         # We need to delete tracks in DB inside root_path that are NOT in seen_paths
         # This is tricky with huge lists.
         # For full Scan, we can iterate DB and check presence? No, slow.
         # Current strategy using 'seen_paths' set works if it fits in memory (it does for <100k files).
         
         music_root = get_music_path()
         rel_root = os.path.relpath(root_path, music_root)
         
         params = []
         if rel_root == ".":
             where = "1=1"
         else:
             where = "path LIKE $1 OR path = $2"
             params = [f"{rel_root}/%", rel_root]
             
         rows = await db.fetch(f"SELECT id, path FROM track WHERE {where}", *params)
         to_delete = []
         for r in rows:
             full_path = os.path.join(music_root, r["path"])
             if full_path not in seen_paths:
                 to_delete.append(r["id"])
                 
         if to_delete:
             logger.info(f"Cleaning {len(to_delete)} orphaned tracks...")
             chunk_size = 500
             for i in range(0, len(to_delete), chunk_size):
                 chunk = to_delete[i:i+chunk_size]
                 await db.execute("DELETE FROM track WHERE id = ANY($1::bigint[])", chunk)
                 
    async def get_artists_in_path(self, root_path: str):
        if not root_path or not os.path.exists(root_path):
            return set()
        music_root = get_music_path()
        rel_root = os.path.relpath(root_path, music_root)
        if rel_root.startswith(".."):
            return set()
        
        where = "1=1"
        params = []
        if rel_root != ".":
            where = "path LIKE $1 OR path = $2"
            params = [f"{rel_root}/%", rel_root]
            
        async for db in get_db():
            q = f"SELECT DISTINCT ta.artist_mbid FROM track t JOIN track_artist ta ON t.id=ta.track_id WHERE {where}"
            rows = await db.fetch(q, *params)
            return {r[0] for r in rows if r[0]}
        return set()

    async def _apply_artist_name_consensus(self, db, mbids):
        if not mbids:
            return
        query = """
            WITH ranked_names AS (
                SELECT t.artist_mbid, t.artist as name, COUNT(*) as cnt,
                ROW_NUMBER() OVER (PARTITION BY t.artist_mbid ORDER BY COUNT(*) DESC) as rn
                FROM track t
                WHERE t.artist_mbid = ANY($1::text[]) 
                AND t.artist_mbid NOT LIKE '%;%' AND t.artist IS NOT NULL AND t.artist != ''
                GROUP BY t.artist_mbid, t.artist
            ), winners AS (
                SELECT artist_mbid, name FROM ranked_names WHERE rn = 1
            )
            UPDATE artist a SET name = w.name, updated_at = NOW()
            FROM winners w WHERE a.mbid = w.artist_mbid AND a.name != w.name;
        """
        try:
            await db.execute(query, list(mbids))
        except Exception as e:
            logger.error(f"Consensus error: {e}")

    async def prune_library(self):
        """
        Clean up unused metadata: empty albums, unused artists, genres, images.
        """
        logger.info("Starting Library Prune...")
        async for db in get_db():
             # 1. Empty Albums (no tracks)
             # Be careful not to delete missing_albums references if we want to keep them?
             # But 'album' table is for local albums.
             await db.execute("""
                 DELETE FROM album WHERE mbid NOT IN (
                     SELECT DISTINCT release_mbid FROM track WHERE release_mbid IS NOT NULL
                 )
             """)
             
             # 2. Unused Artists (no tracks, no album artist links)
             # Simple check: Not in track_artist AND not in artist_album
             await db.execute("""
                 DELETE FROM artist WHERE mbid NOT IN (
                     SELECT DISTINCT artist_mbid FROM track_artist
                     UNION
                     SELECT DISTINCT artist_mbid FROM artist_album
                 )
             """)
             
             # 3. Unused Genres
             await db.execute("""
                 DELETE FROM artist_genre WHERE artist_mbid NOT IN (SELECT mbid FROM artist)
             """)

             # 4. Unused External Links
             await db.execute("""
                 DELETE FROM external_link WHERE 
                 (entity_type = 'artist' AND entity_id NOT IN (SELECT mbid FROM artist)) OR
                 (entity_type = 'album' AND entity_id NOT IN (SELECT DISTINCT release_group_mbid FROM album WHERE release_group_mbid IS NOT NULL))
             """)
             
             # 5. Unused Images (not mapped to anything)
             # Check image_map first
             await db.execute("""
                 DELETE FROM image_map WHERE
                 (entity_type = 'artist' AND entity_id NOT IN (SELECT mbid FROM artist)) OR
                 (entity_type = 'album' AND entity_id NOT IN (SELECT DISTINCT release_group_mbid FROM album WHERE release_group_mbid IS NOT NULL)) OR
                 (entity_type = 'track' AND entity_id::bigint NOT IN (SELECT id FROM track))
             """)
             
             await db.execute("""
                 DELETE FROM artwork WHERE id NOT IN (SELECT DISTINCT artwork_id FROM image_map)
                 AND id NOT IN (SELECT artwork_id FROM album WHERE artwork_id IS NOT NULL)
                 AND id NOT IN (SELECT artwork_id FROM track WHERE artwork_id IS NOT NULL)
                 AND id NOT IN (SELECT artwork_id FROM artist WHERE artwork_id IS NOT NULL)
             """)
             
        logger.info("Library Prune Complete.")


_shared_client = None
_dns_cache_warmed = False

async def warm_dns_cache():
    """
    Pre-resolve known API hostnames to warm the DNS cache.
    This eliminates DNS lookups during scanning.
    
    This is optional and should only be called from the CLI scanner,
    not from the web server context.
    """
    global _dns_cache_warmed
    if _dns_cache_warmed:
        return
        
    try:
        # Lazy import to avoid loading aiodns in web server context
        from app.scanner.dns_resolver import warm_dns_cache as _warm_dns_cache
        
        logger.info("Warming DNS cache for scanner...")
        await _warm_dns_cache()
        _dns_cache_warmed = True
        logger.info("DNS cache warmed successfully")
    except Exception as e:
        # Don't fail if DNS warming fails - it's just an optimization
        logger.warning(f"Failed to warm DNS cache (non-fatal): {e}")

def get_shared_client() -> httpx.AsyncClient:
    """
    Returns a shared httpx.AsyncClient instance with DNS caching.
    Created lazily and lasts for the process lifetime (or until closed).
    """
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        # Create HTTP client
        # DNS caching is handled separately via warm_dns_cache() if needed
        
        limits = httpx.Limits(max_keepalive_connections=10, max_connections=25)
        _shared_client = httpx.AsyncClient(
            headers={"User-Agent": "Jamarr/0.1 ( jamarr@example.com )"},
            timeout=30.0,
            limits=limits,
            follow_redirects=True
        )
    return _shared_client

async def close_shared_client():
    global _shared_client
    if _shared_client and not _shared_client.is_closed:
        await _shared_client.aclose()
        logger.info("Shared scanner client closed.")
    _shared_client = None
