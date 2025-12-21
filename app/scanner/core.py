import os
import asyncio
import logging
import json
import time
from app.db import get_db
from app.scanner.tags import extract_tags
from app.scanner.artwork import extract_and_save_artwork, download_and_save_artwork, cleanup_orphaned_artwork
from app.config import get_music_path
from app.scanner.metadata import fetch_artist_metadata, fetch_track_credits

logger = logging.getLogger(__name__)

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

    async def scan_filesystem(self, root_path: str = None, force_rescan: bool = False):
        if root_path is None:
            root_path = get_music_path()

        if not os.path.exists(root_path):
            logger.error(f"Scan path not found: {root_path}")
            return

        self.stats = {"scanned": 0, "added": 0, "updated": 0, "errors": 0, "total_estimate": 0, "current_status": "Scanning"}
        self._stop_event.clear()
        
        logger.info(f"Starting scan of {root_path} (Force: {force_rescan})")
        
        # 1. Estimate
        # Counting files can be slow on huge libs, maybe skip or quick walk?
        # Let's do a quick count if not too huge, or dynamic.
        # For nice UI, a total is great.
        self.stats["current_status"] = "Counting files..."
        file_count = 0
        for _, _, files in os.walk(root_path):
             file_count += len([f for f in files if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS])
        self.stats["total_estimate"] = file_count
        logger.info(f"Estimated {file_count} files to scan.")

        # 2. Scanning
        self.stats["current_status"] = "Scanning Files"
        artist_mbids = set()
        seen_paths = set()
        
        async for db in get_db():
            await self._scan_recursive(root_path, db, artist_mbids, seen_paths, force_rescan)
            
            # 3. Cleanup
            self.stats["current_status"] = "Cleaning Orphans"
            await self._cleanup_orphans(db, root_path, seen_paths)
            
            # 4. Populate Artists Table
            # Ensure all referenced artists exist in the artists table (from current scan OR existing DB)
            async with db.execute("SELECT DISTINCT mbid FROM track_artists") as cursor:
                rows = await cursor.fetchall()
                db_mbids = {r[0] for r in rows if r[0]}
            
            # Merge known names from scan if available
            # We want to insert any missing artists
            all_mbids = db_mbids.union({m[0] for m in artist_mbids if m[0]})

            logger.info(f"Ensuring {len(all_mbids)} artists exist in database...")
            
            # Batch this if large? For now simple loop
            for mbid in all_mbids:
                 await db.execute("INSERT OR IGNORE INTO artists (mbid) VALUES (?)", (mbid,))
            
            # Update names if we have them from the scan
            for mbid, name in artist_mbids:
                 if mbid and name:
                     await db.execute("UPDATE artists SET name = ? WHERE mbid = ? AND (name IS NULL OR name = '')", (name, mbid))

            await db.commit()

            # Return discovered artists for next steps (optional chaining)
            return artist_mbids

    async def _scan_recursive(self, root, db, artist_mbids, seen_paths, force_rescan):
        if self._stop_event.is_set(): return

        try:
            for entry in os.scandir(root):
                if entry.is_dir():
                    await self._scan_recursive(entry.path, db, artist_mbids, seen_paths, force_rescan)
                elif entry.is_file():
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        seen_paths.add(entry.path)
                        self.stats["scanned"] += 1
                        
                        # Emit Progress
                        if self.scan_logger:
                             percent = (self.stats["scanned"] / self.stats["total_estimate"] * 100) if self.stats["total_estimate"] else 0
                             self.scan_logger.emit_progress(self.stats["scanned"], self.stats["total_estimate"], f"Scanning {entry.name}")
                        
                        await self._process_file(entry.path, db, artist_mbids, force_rescan)
        except OSError as e:
            logger.error(f"Error accessing {root}: {e}")
            self.stats["errors"] += 1

    async def _process_file(self, path, db, artist_mbids, force_rescan):
        try:
            # Check modification time
            mtime = os.path.getmtime(path)
            async with db.execute("SELECT id, mtime FROM tracks WHERE path = ?", (path,)) as cursor:
                row = await cursor.fetchone()
                if not force_rescan and row and row[1] == mtime:
                    return # Unchanged

            # Extract Tags
            tags = extract_tags(path)
            if not tags: return

            # Artwork
            art_hash = await extract_and_save_artwork(path)
            art_id = None
            if art_hash:
                async with db.execute("SELECT id FROM artwork WHERE sha1 = ?", (art_hash,)) as cursor:
                    if row := await cursor.fetchone():
                        art_id = row[0]
                    else:
                        await db.execute("INSERT INTO artwork (sha1, type) VALUES (?, ?)", (art_hash, 'album'))
                        await db.commit()
                        async with db.execute("SELECT last_insert_rowid()") as id_cursor:
                            art_id = (await id_cursor.fetchone())[0]

            # Upsert Track
            keys = ["path", "mtime", "title", "artist", "album", "album_artist", 
                    "track_no", "disc_no", "date", "genre", "duration_seconds", 
                    "codec", "sample_rate_hz", "bit_depth", "bitrate", "channels", "label", 
                    "mb_artist_id", "mb_album_artist_id", "mb_track_id", "mb_release_track_id", "mb_release_id", "mb_release_group_id", "art_id"]
            
            values = [
                path, mtime, tags.get("title"), tags.get("artist"), tags.get("album"), 
                tags.get("album_artist"), tags.get("track_no"), tags.get("disc_no"), 
                tags.get("date"), tags.get("genre"), tags.get("duration_seconds"),
                tags.get("codec"), tags.get("sample_rate_hz"), tags.get("bit_depth"),
                tags.get("bitrate"), tags.get("channels"), tags.get("label"),
                tags.get("mb_artist_id"), tags.get("mb_album_artist_id"), 
                tags.get("mb_track_id"), tags.get("mb_release_track_id"), tags.get("mb_release_id"), tags.get("mb_release_group_id"), art_id
            ]
            
            placeholders = ", ".join(["?"] * len(keys))
            columns = ", ".join(keys)
            
            sql = f"INSERT OR REPLACE INTO tracks ({columns}) VALUES ({placeholders})"
            cursor = await db.execute(sql, values)
            track_id = cursor.lastrowid
            await db.commit()
            
            if row: self.stats["updated"] += 1
            else: self.stats["added"] += 1

            # --- Populate Normalized Tables from Tags ---
            
            # 1. Albums
            mb_rg_id = tags.get("mb_release_group_id")
            album_title = tags.get("album")
            if mb_rg_id and album_title:
                 # Upsert Album
                 try:
                     await db.execute("""
                        INSERT INTO albums (mbid, title, release_date, secondary_types, art_id, last_updated)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(mbid) DO UPDATE SET
                            title=COALESCE(excluded.title, title),
                            release_date=COALESCE(excluded.release_date, release_date),
                            art_id=COALESCE(excluded.art_id, art_id)
                     """, (mb_rg_id, album_title, tags.get("date"), 'Album', art_id, time.time()))
                 except Exception as e:
                     logger.warning(f"Error upserting album {album_title}: {e}")

            # 2. Handle Artists & Junctions
            if track_id:
                await self._process_track_artists(db, track_id, tags, artist_mbids, mb_rg_id)

        except Exception as e:
            logger.error(f"Failed to process {path}: {e}")
            self.stats["errors"] += 1

    async def _process_track_artists(self, db, track_id, tags, artist_mbids, mb_rg_id=None):
        # Clear existing
        await db.execute("DELETE FROM track_artists WHERE track_id = ?", (track_id,))
        
        # Helper to extract IDs
        def extract_ids(raw):
            if not raw: return []
            cleaned = raw.replace("/", ";").replace("&", ";")
            return [x.strip() for x in cleaned.split(";") if x.strip()]

        ids = []
        if tags.get("mb_artist_id"):
            ids = extract_ids(tags["mb_artist_id"])

        # Enrichment (Credits) if needed
        mb_track_id = tags.get("mb_track_id") or tags.get("mb_release_track_id")
        artist_tag = tags.get("artist") or ""
        needs_enrichment = False
        
        if mb_track_id and (len(ids) <= 1):
            ids_check = ids if ids else []
            if "feat" in artist_tag.lower() or "&" in artist_tag or "," in artist_tag:
                 # Simple check: if we have IDs, do we match count?
                 # Actually, logic here was to detect if we likely missed features.
                 needs_enrichment = True

        if needs_enrichment:
             try:
                 credits = await fetch_track_credits(tags.get("mb_track_id"), tags.get("mb_release_track_id"))
                 if credits:
                     ids = [c[0] for c in credits]
                     for mbid, name in credits:
                         # Upsert Artist from credits name
                         await db.execute("""
                            INSERT INTO artists (mbid, name, last_updated) VALUES (?, ?, ?)
                            ON CONFLICT(mbid) DO UPDATE SET name=COALESCE(name, excluded.name)
                         """, (mbid, name, time.time()))
                         
                         # Create MusicBrainz external link
                         from app.config import get_musicbrainz_root_url
                         mb_url = f"{get_musicbrainz_root_url()}/artist/{mbid}"
                         await db.execute("""
                            INSERT OR IGNORE INTO external_links (entity_type, entity_id, type, url)
                            VALUES (?, ?, ?, ?)
                         """, ('artist', mbid, 'musicbrainz', mb_url))
                         
                         artist_mbids.add((mbid, name))
             except: pass

        for mbid in ids:
            await db.execute("INSERT INTO track_artists (track_id, mbid) VALUES (?, ?)", (track_id, mbid))
            
            # Upsert Artist (Track Artist)
            # Only use artist tag for single artists - multi-artist tags contain combined names
            # like "Artist A & Artist B" which we can't reliably split
            # For multi-artist tracks, metadata enrichment will fetch individual names from MusicBrainz
            name = tags.get("artist") if len(ids) == 1 else None
            
            await db.execute("""
                INSERT INTO artists (mbid, name, last_updated) VALUES (?, ?, ?)
                ON CONFLICT(mbid) DO UPDATE SET name=COALESCE(name, excluded.name)
            """, (mbid, name, time.time()))
            
            # Create MusicBrainz external link
            from app.config import get_musicbrainz_root_url
            mb_url = f"{get_musicbrainz_root_url()}/artist/{mbid}"
            await db.execute("""
                INSERT OR IGNORE INTO external_links (entity_type, entity_id, type, url)
                VALUES (?, ?, ?, ?)
            """, ('artist', mbid, 'musicbrainz', mb_url))

            artist_mbids.add((mbid, name))
        
        # Album Artist & Album Junction
        if tags.get("mb_album_artist_id"):
             aa_ids = extract_ids(tags["mb_album_artist_id"])
             aa_name = tags.get("album_artist") or tags.get("artist")
             # Only use album_artist tag for single artists - multi-artist tags contain combined names
             name = aa_name if len(aa_ids) == 1 else None
             
             for mbid in aa_ids:
                 # Upsert Artist (Album Artist)
                 await db.execute("""
                    INSERT INTO artists (mbid, name, last_updated) VALUES (?, ?, ?)
                    ON CONFLICT(mbid) DO UPDATE SET name=COALESCE(name, excluded.name)
                 """, (mbid, name, time.time()))
                 
                 # Create MusicBrainz external link
                 from app.config import get_musicbrainz_root_url
                 mb_url = f"{get_musicbrainz_root_url()}/artist/{mbid}"
                 await db.execute("""
                    INSERT OR IGNORE INTO external_links (entity_type, entity_id, type, url)
                    VALUES (?, ?, ?, ?)
                 """, ('artist', mbid, 'musicbrainz', mb_url))
                 
                 artist_mbids.add((mbid, name))
                 
                 # Junction: Artist-Album (Primary)
                 if mb_rg_id:
                     await db.execute("""
                        INSERT OR IGNORE INTO artist_albums (artist_mbid, album_mbid, type)
                        VALUES (?, ?, ?)
                     """, (mbid, mb_rg_id, 'primary'))

    async def _cleanup_orphans(self, db, root_path, seen_paths):
        scan_root_wildcard = root_path if root_path.endswith(os.sep) else root_path + os.sep
        scan_root_wildcard += "%"
        
        async with db.execute("SELECT path FROM tracks WHERE path LIKE ?", (scan_root_wildcard,)) as cursor:
            rows = await cursor.fetchall()
            db_paths = {row[0] for row in rows}
            
        orphans = db_paths - seen_paths
        if orphans:
            logger.info(f"Removing {len(orphans)} orphaned tracks.")
            for orphan in orphans:
                await db.execute("DELETE FROM tracks WHERE path = ?", (orphan,))
            await db.commit()

    async def prune_library(self):
        """
        Comprehensive cleanup of the database and filesystem.
        Removes:
        1. Tracks not on disk.
        2. Artists/Albums with no tracks.
        3. External links for deleted entities.
        4. Artwork not referenced in DB (Filesystem & DB).
        """
        self.stats["current_status"] = "Pruning Library"
        logger.info("Starting Library Prune...")
        
        async for db in get_db():
            # 1. Prune Tracks (DB -> FS check)
            logger.info("Checking for deleted files...")
            async with db.execute("SELECT id, path FROM tracks") as cursor:
                rows = await cursor.fetchall()
            
            deleted_tracks = 0
            for track_id, path in rows:
                if not os.path.exists(path):
                    # logger.debug(f"Pruning missing file: {path}")
                    await db.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
                    deleted_tracks += 1
            if deleted_tracks:
                await db.commit()
                logger.info(f"Removed {deleted_tracks} missing tracks.")
            
            # 2. Prune Orphaned Artists (No tracks in track_artists)
            # Find artists who are NOT in track_artists
            logger.info("Pruning orphaned artists...")
            await db.execute("""
                DELETE FROM artists 
                WHERE mbid NOT IN (SELECT DISTINCT mbid FROM track_artists)
            """)
            
            # 3. Prune Orphaned Albums (No tracks associated)
            # Based on tracks.mb_release_group_id
            logger.info("Pruning orphaned albums...")
            await db.execute("""
                DELETE FROM albums 
                WHERE mbid NOT IN (SELECT DISTINCT mb_release_group_id FROM tracks WHERE mb_release_group_id IS NOT NULL)
            """)
            
            # 4. Prune Orphaned Junctions (Artist-Albums)
            await db.execute("""
                DELETE FROM artist_albums
                WHERE artist_mbid NOT IN (SELECT mbid FROM artists)
                OR album_mbid NOT IN (SELECT mbid FROM albums)
            """)
            
            # 5. Prune External Links
            await db.execute("""
                DELETE FROM external_links
                WHERE (entity_type='artist' AND entity_id NOT IN (SELECT mbid FROM artists))
                OR (entity_type='album' AND entity_id NOT IN (SELECT mbid FROM albums))
            """)

            await db.commit()
            
            # 6. Prune Artwork (The big one)
            logger.info("Pruning orphaned artwork...")
            
            # Get all used SHA1s
            used_shas = set()
            
            # From Tracks
            async with db.execute("SELECT a.sha1 FROM tracks t JOIN artwork a ON t.art_id = a.id") as c:
                used_shas.update([r[0] for r in await c.fetchall()])
            # From Artists
            async with db.execute("SELECT a.sha1 FROM artists t JOIN artwork a ON t.art_id = a.id") as c:
                used_shas.update([r[0] for r in await c.fetchall()])
            # From Albums
            async with db.execute("SELECT a.sha1 FROM albums t JOIN artwork a ON t.art_id = a.id") as c:
                used_shas.update([r[0] for r in await c.fetchall()])
                
            # Delete from DB if not used
            await db.execute("DELETE FROM artwork WHERE sha1 NOT IN (SELECT sha1 FROM artwork WHERE sha1 IN (SELECT sha1 FROM artwork) AND sha1 IN (SELECT sha1 FROM artwork))") # Wait, easier:
            
            # Better: Select all artwork IDs, delete if not in used set? No, Artwork table is source of truth.
            # Delete unused rows
            # We can't easily pass a set to IN clause without placeholders.
            
            # Let's iterate Filesystem instead.
            art_paths = []
            for subdir in ["artist", "album"]:
                root = os.path.join(self.art_cache_path, subdir)
                if not os.path.exists(root): continue
                for folder in os.listdir(root):
                    folder_path = os.path.join(root, folder)
                    if not os.path.isdir(folder_path): continue
                    for file in os.listdir(folder_path):
                        art_paths.append(os.path.join(folder_path, file))
            
            deleted_art = 0
            for path in art_paths:
                # Filename (minus ext) is usually the hash?
                # Actually, our `download_and_save_artwork` saves as cache/art/type/xx/hash.ext
                # So filename without extension is NOT always the hash depending on naming?
                # Wait, save_artwork uses `sha1`. So yes.
                
                filename = os.path.basename(path)
                sha = os.path.splitext(filename)[0]
                
                if sha not in used_shas:
                    try:
                        os.remove(path)
                        deleted_art += 1
                    except: pass
            
            logger.info(f"Deleted {deleted_art} orphaned artwork files.")
            
            # Clean up DB rows now that files are gone (or just driven by used_shas)
            # Delete any artwork row where SHA1 is not in used_shas
            # Creating a temp table or passing massive list is hard.
            # Easier: Delete unused rows based on LEFT JOINs.
            await db.execute("""
                DELETE FROM artwork
                WHERE id NOT IN (SELECT art_id FROM tracks WHERE art_id IS NOT NULL)
                AND id NOT IN (SELECT art_id FROM artists WHERE art_id IS NOT NULL)
                AND id NOT IN (SELECT art_id FROM albums WHERE art_id IS NOT NULL)
            """)
            await db.commit()
            
            logger.info("Library Prune Complete.")

    async def update_metadata(self, artist_filter=None, mbid_filter=None, specific_fields=None, missing_only=False, bio_only=False):
        """
        Updates artist metadata.
        Can filter by artist name (--artist) or MusicBrainz ID (--mbid).
        """
        self.stats["current_status"] = "Updating Metadata"
        async for db in get_db():
            # Get artists
            query = """
                SELECT a.mbid, a.name, a.last_updated, a.sort_name, a.bio, a.image_url, 
                       COUNT(el.id) as link_count
                FROM artists a
                LEFT JOIN external_links el 
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
            elif missing_only:
                clauses.append(
                    "(name IS NULL OR name = '' OR sort_name IS NULL OR sort_name = '' OR bio IS NULL OR bio = '' OR image_url IS NULL OR image_url = '')"
                )
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " GROUP BY a.mbid"
            
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()

            def has_gaps(row):
                _, name, _, sort_name, bio, image_url, link_count = row
                return (
                    not name or not str(name).strip()
                    or not sort_name or not str(sort_name).strip()
                    or not bio or not str(bio).strip()
                    or not image_url or not str(image_url).strip()
                    or (link_count or 0) == 0
                )

            # If filtered query (artist/mbid) was used with missing_only, reapply gap check client-side
            if missing_only:
                rows = [r for r in rows if has_gaps(r)]
            
            total = len(rows)
            logger.info(f"Found {total} artists to update.")
            processed = 0
            
            for row in rows:
                if self._stop_event.is_set():
                    logger.info("Metadata update cancelled by stop signal.")
                    raise asyncio.CancelledError()

                mbid, name, last_updated, sort_name, bio, image_url, link_count = row
                if not mbid: continue

                if missing_only and not has_gaps(row):
                    continue
                
                # Emit initial "Fetching..." if name is unknown, or name if known
                display_name = name or "Fetching..."
                if self.scan_logger: self.scan_logger.emit_progress(processed, total, f"Metadata: {display_name}")
                
                # Check recent update?
                # if not force and last_updated ... logic here
                
                # Get local Release Group IDs for this artist to optimize link fetching
                # We only want to resolve links for EPs if we have them locally.
                async with db.execute("""
                    SELECT DISTINCT t.mb_release_group_id 
                    FROM tracks t
                    JOIN track_artists ta ON t.id = ta.track_id
                    WHERE ta.mbid = ? AND t.mb_release_group_id IS NOT NULL
                """, (mbid,)) as cursor:
                    local_rg_rows = await cursor.fetchall()
                    local_release_group_ids = {r[0] for r in local_rg_rows}

                meta = await fetch_artist_metadata(mbid, name, local_release_group_ids=local_release_group_ids, bio_only=bio_only)
                
                # Save Artwork if new
                art_id = None
                
                # Update progress with actual name if we have it now
                current_name = meta.get("name") or name or "Unknown"
                if self.scan_logger: self.scan_logger.emit_progress(processed, total, f"Metadata: {current_name}")

                if meta.get("image_url"):
                     art_hash = await download_and_save_artwork(meta["image_url"], art_type='artist')
                     if art_hash:
                         # Get ID
                         async with db.execute("SELECT id FROM artwork WHERE sha1 = ?", (art_hash,)) as cursor:
                             if r := await cursor.fetchone(): art_id = r[0]
                             else:
                                 await db.execute("INSERT INTO artwork (sha1, type) VALUES (?, ?)", (art_hash, 'artist'))
                                 await db.commit()
                                 async with db.execute("SELECT last_insert_rowid()") as id_cursor:
                                     art_id = (await id_cursor.fetchone())[0]

                # Update DB
                # Update Artists Table (Core Info)
                # Only update name/sort_name if they are currently NULL or empty (preserves tag-based names)
                # Always update bio, image_url, art_id if we have new values
                await db.execute("""
                    UPDATE artists SET 
                        name=CASE WHEN (name IS NULL OR name = '') THEN ? ELSE name END,
                        sort_name=CASE WHEN (sort_name IS NULL OR sort_name = '') THEN ? ELSE sort_name END,
                        bio=COALESCE(?, bio),
                        image_url=COALESCE(?, image_url),
                        art_id=COALESCE(?, art_id),
                        last_updated=?
                    WHERE mbid=?
                """, (
                    meta.get("name"), meta.get("sort_name"),
                    meta.get("bio"), meta.get("image_url"), art_id,
                    meta["last_updated"],
                    mbid
                ))

                # --- Update Normalized Tables ---
                
                # 1. External Links (Artist)
                # Clear existing for full refresh validity
                await db.execute("DELETE FROM external_links WHERE entity_type='artist' AND entity_id=?", (mbid,))
                
                artist_links = []
                # Always include MusicBrainz link for this artist using MBID
                try:
                    from app.config import get_musicbrainz_root_url
                    mb_url = f"{get_musicbrainz_root_url()}/artist/{mbid}"
                    artist_links.append(("musicbrainz", mb_url))
                except Exception:
                    logger.debug("Could not build MusicBrainz link for %s", mbid)
                if meta.get("spotify_url"): artist_links.append(("spotify", meta["spotify_url"]))
                if meta.get("tidal_url"): artist_links.append(("tidal", meta["tidal_url"]))
                if meta.get("qobuz_url"): artist_links.append(("qobuz", meta["qobuz_url"]))
                if meta.get("wikipedia_url"): artist_links.append(("wikipedia", meta["wikipedia_url"]))
                if meta.get("homepage"): artist_links.append(("homepage", meta["homepage"]))
                
                for l_type, l_url in artist_links:
                    await db.execute("INSERT OR IGNORE INTO external_links (entity_type, entity_id, type, url) VALUES (?, ?, ?, ?)", 
                                     ('artist', mbid, l_type, l_url))

                # 2. Top Tracks & Singles
                from app.scanner.metadata import match_track_to_library
                
                # Clear existing top tracks/singles for this artist
                await db.execute("DELETE FROM tracks_top WHERE artist_mbid=?", (mbid,))
                
                # Store top tracks
                for idx, track in enumerate(meta.get("top_tracks", [])):
                    track_id = await match_track_to_library(
                        db, mbid, track["name"], track.get("album")
                    )
                    
                    await db.execute("""
                        INSERT OR REPLACE INTO tracks_top 
                        (artist_mbid, type, track_id, external_name, external_album, 
                         external_date, external_duration_ms, popularity, rank, last_updated)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (mbid, 'top', track_id, track["name"], track.get("album"), 
                          track.get("date"), track.get("duration_ms"), track.get("popularity"), idx + 1, time.time()))
                
                # Store singles
                for single in meta.get("singles", []):
                    track_id = await match_track_to_library(
                        db, mbid, single["title"], None
                    )
                    
                    await db.execute("""
                        INSERT OR REPLACE INTO tracks_top 
                        (artist_mbid, type, track_id, external_name, external_album, 
                         external_date, external_mbid, last_updated)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (mbid, 'single', track_id, single["title"], single.get("album"),
                          single["date"], single.get("mbid"), time.time()))

                # 3. Similar Artists
                # Clear existing similar artists
                await db.execute("DELETE FROM similar_artists WHERE artist_mbid=?", (mbid,))
                
                # Debug: Check if similar_artists data exists
                similar_count = len(meta.get("similar_artists", []))
                logger.debug(f"Storing {similar_count} similar artists for {mbid}")
                
                # Store similar artists with library matching
                for idx, similar_name in enumerate(meta.get("similar_artists", [])):
                    # Try to find MBID if artist is in our library
                    async with db.execute(
                        "SELECT mbid FROM artists WHERE LOWER(TRIM(name)) = ? LIMIT 1",
                        (similar_name.lower().strip(),)
                    ) as cursor:
                        row = await cursor.fetchone()
                        similar_mbid = row[0] if row else None
                    
                    await db.execute("""
                        INSERT OR REPLACE INTO similar_artists 
                        (artist_mbid, similar_artist_name, similar_artist_mbid, rank, last_updated)
                        VALUES (?, ?, ?, ?, ?)
                    """, (mbid, similar_name, similar_mbid, idx + 1, time.time()))

                # 4. Albums & Singles (Release Groups)
                all_releases = meta.get("albums", []) + meta.get("singles", [])
                
                # Clear existing artist_albums junction for this artist? 
                # Safer to delete query-based? No, assume append/update or user wants cleanup?
                # Let's delete from artist_albums where artist_id = mbid
                await db.execute("DELETE FROM artist_albums WHERE artist_mbid=?", (mbid,))

                for release in all_releases:
                    r_mbid = release["mbid"]
                    r_title = release["title"]
                    r_date = release["date"]
                    r_links = release.get("links") or []
                    r_release_ids = release.get("release_ids") or []
                    r_primary_release = release.get("primary_release_id")
                    # Prefer release IDs from our tagged tracks
                    tagged_release_ids = []
                    async with db.execute(
                        "SELECT DISTINCT mb_release_id FROM tracks WHERE mb_release_group_id = ? AND mb_release_id IS NOT NULL",
                        (r_mbid,),
                    ) as cursor:
                        rows = await cursor.fetchall()
                        tagged_release_ids = [row[0] for row in rows if row and row[0]]
                    # Use tagged release IDs as highest priority
                    if tagged_release_ids:
                        r_primary_release = tagged_release_ids[0]
                        r_release_ids = tagged_release_ids
                    
                    # Upsert Album
                    await db.execute("""
                        INSERT INTO albums (mbid, title, release_date, primary_type, last_updated)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(mbid) DO UPDATE SET
                            title=excluded.title,
                            release_date=excluded.release_date,
                            last_updated=excluded.last_updated
                    """, (r_mbid, r_title, r_date, 'Album', time.time())) # Simplified type handling
                    
                    # Link Tracks to Album (Backfill missing release group tags)
                    if r_release_ids:
                        placeholders = ",".join("?" * len(r_release_ids))
                        await db.execute(f"UPDATE tracks SET mb_release_group_id=? WHERE mb_release_id IN ({placeholders})", (r_mbid, *r_release_ids))
                    
                    # Junction
                    await db.execute("INSERT OR IGNORE INTO artist_albums (artist_mbid, album_mbid, type) VALUES (?, ?, ?)",
                                     (mbid, r_mbid, 'primary'))
                    
                    # Album Links
                    from app.config import get_musicbrainz_root_url
                    mb_release_link = None
                    if r_primary_release:
                        mb_release_link = f"{get_musicbrainz_root_url()}/release/{r_primary_release}"
                    elif r_release_ids:
                        mb_release_link = f"{get_musicbrainz_root_url()}/release/{r_release_ids[0]}"
                    link_payloads = []
                    if mb_release_link:
                        link_payloads.append({"type": "musicbrainz", "url": mb_release_link})
                    link_payloads.extend(r_links)

                    await db.execute("DELETE FROM external_links WHERE entity_type='album' AND entity_id=?", (r_mbid,))
                    for link in link_payloads:
                        await db.execute(
                            "INSERT OR IGNORE INTO external_links (entity_type, entity_id, type, url) VALUES (?, ?, ?, ?)",
                            ("album", r_mbid, link["type"], link["url"]),
                        )
                await db.commit()
                processed += 1
                if self.scan_logger:
                    self.scan_logger.emit_progress(processed, total, f"Metadata: {current_name}")
                    # Allow UI to render
                    await asyncio.sleep(0.1)

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
        await self.update_metadata(artist_filter=artist_filter, mbid_filter=mbid_filter) 
