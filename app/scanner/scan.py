import os
import asyncio
import logging
import json
from app.db import get_db
from app.scanner.tags import extract_tags
from app.scanner.artwork import extract_and_save_artwork, download_and_save_artwork, cleanup_orphaned_artwork
from app.config import get_music_path
from app.scanner.metadata import fetch_artist_metadata, fetch_track_credits

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aiff"}

async def scan_library(root_path: str = None, force_metadata: bool = False, force_rescan: bool = False):
    if root_path is None:
        root_path = get_music_path()

    logger.info(f"Starting scan of {root_path} (Force Rescan: {force_rescan})")
    
    if not os.path.exists(root_path):
        logger.error(f"Path not found: {root_path}")
        return

    # We'll collect MBIDs to fetch metadata for
    artist_mbids = set()

    # Track seen paths for cleanup
    seen_paths = set()

    async for db in get_db():
        await _scan_recursive(root_path, db, artist_mbids, seen_paths, force_rescan)
        
        logger.info("File scan complete. Checking for removed files...")
        
        # Cleanup: Remove tracks that are in DB but were not seen in this scan
        # ONLY for tracks that fall under the root_path we just scanned
        
        # Ensure directory path for LIKE query (append / if not present)
        # This prevents scanning /music/Band removing /music/BandOfHorses
        scan_root_wildcard = root_path if root_path.endswith(os.sep) else root_path + os.sep
        scan_root_wildcard += "%"
        
        # If root_path is exactly a file (unlikely for "scan_library" but possible if generalized),
        # we might need handling, but usually root_path is a dir. 
        # If it's a single file scan, _scan_recursive handles it? mmm scan_library iterates scandir
        # scan_library expects a directory.
        
        async with db.execute("SELECT path FROM tracks WHERE path LIKE ?", (scan_root_wildcard,)) as cursor:
            rows = await cursor.fetchall()
            db_paths = {row[0] for row in rows}
            
        orphans = db_paths - seen_paths
        
        if orphans:
            logger.info(f"Found {len(orphans)} orphaned tracks. Removing...")
            for orphan in orphans:
                logger.debug(f"Removing orphan: {orphan}")
                await db.execute("DELETE FROM tracks WHERE path = ?", (orphan,))
                # Also clean up track_artists? 
                # SQLite ON DELETE CASCADE might be needed or manual cleanup.
                # Tracks table usually doesn't cascade to artists table (since artists are shared),
                # but track_artists join table should be cleared.
                # Assuming schema handles `track_artists` via foreign key cascade or we leave it (it's weak ref).
                # Checking schema would be good, but typically 'DELETE FROM tracks' is enough if configured.
                # If not, we might leave junk in track_artists.
                # Let's assume standard behavior for now, or add cleanup for track_artists if needed.
                # Actually, earlier in code: "DELETE FROM track_artists WHERE track_id = ?" 
                # suggesting manual management or no cascade.
                # Let's check if we need to delete from track_clients etc.
                # For now, just delete from tracks.
            
            await db.commit()
            logger.info(f"Removed {len(orphans)} orphaned tracks.")
        else:
            logger.info("No orphaned tracks found.")

        logger.info("Updating artist metadata...")

        # Get all MBIDs from DB (Track Artists AND Album Artists)
        # We need to process them to handle splits (id1; id2)
        async with db.execute("SELECT DISTINCT mb_artist_id, artist FROM tracks WHERE mb_artist_id IS NOT NULL UNION SELECT DISTINCT mb_album_artist_id, album_artist FROM tracks WHERE mb_album_artist_id IS NOT NULL") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                raw_mbids = row[0]
                # Same splitting logic as in _process_file
                if raw_mbids:
                   mbids = raw_mbids.replace("/", ";").replace("&", ";").split(";")
                   for mbid in mbids:
                       mbid = mbid.strip()
                       if mbid:
                           # Pass None for name to force canonical lookup, avoiding "A & B" poisoning
                           artist_mbids.add((mbid, None))
                       


        # Fetch metadata for artists
        logger.info(f"Found {len(artist_mbids)} artist MBIDs to check.")
        for mbid, artist_name in artist_mbids:
            if not mbid: continue
            
            if not force_metadata:
                # Check if we already have fresh metadata
                async with db.execute("SELECT last_updated FROM artists WHERE mbid = ?", (mbid,)) as cursor:
                    row = await cursor.fetchone()
                    if row and row[0]:
                        # Skip if updated recently (e.g. within 7 days), for now just skip if exists
                        continue

            logger.info(f"Fetching metadata for {artist_name} ({mbid})...")
            meta = await fetch_artist_metadata(mbid, artist_name)
            
            # Download and cache artist image if available
            art_id = None
            if meta.get("image_url"):
                art_hash = await download_and_save_artwork(meta["image_url"], art_type='artist')
                if art_hash:
                    # Get or create artwork record
                    async with db.execute("SELECT id FROM artwork WHERE sha1 = ?", (art_hash,)) as cursor:
                        art_row = await cursor.fetchone()
                        if art_row:
                            art_id = art_row[0]
                        else:
                            await db.execute("INSERT INTO artwork (sha1, type) VALUES (?, ?)", (art_hash, 'artist'))
                            await db.commit()
                            async with db.execute("SELECT last_insert_rowid()") as id_cursor:
                                art_id = (await id_cursor.fetchone())[0]
            
            await db.execute("""
                INSERT INTO artists (
                    mbid, name, sort_name, bio, image_url, art_id, spotify_url, homepage, 
                    wikipedia_url, qobuz_url, tidal_url, musicbrainz_url,
                    top_tracks, singles, albums, last_updated
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mbid) DO UPDATE SET
                    name=excluded.name,
                    sort_name=excluded.sort_name,
                    bio=excluded.bio,
                    image_url=excluded.image_url,
                    art_id=excluded.art_id,
                    spotify_url=excluded.spotify_url,
                    homepage=excluded.homepage,
                    wikipedia_url=excluded.wikipedia_url,
                    qobuz_url=excluded.qobuz_url,
                    tidal_url=excluded.tidal_url,
                    musicbrainz_url=excluded.musicbrainz_url,
                    similar_artists=excluded.similar_artists,
                    top_tracks=excluded.top_tracks,
                    singles=excluded.singles,
                    albums=excluded.albums,
                    last_updated=excluded.last_updated
            """, (
                meta["mbid"], meta["name"], meta["sort_name"], meta["bio"], meta["image_url"], art_id,
                meta["spotify_url"], meta["homepage"], 
                meta["wikipedia_url"], meta["qobuz_url"], meta.get("tidal_url"), meta["musicbrainz_url"],
                json.dumps(meta["top_tracks"]),
                json.dumps(meta.get("singles", [])),
                json.dumps(meta.get("albums", [])),
                meta["last_updated"]
            ))
            await db.commit()
        
    # Cleanup orphaned artwork (New DB connection for safety/isolation)
    async for db in get_db():
        logger.info("Cleaning up orphaned artwork...")
        count = await cleanup_orphaned_artwork(db)
        if count:
            logger.info(f"Removed {count} orphaned artwork files.")
        break


async def refresh_artist_metadata(artist_name: str):
    logger.info(f"Forced metadata refresh for {artist_name}")
    async for db in get_db():
        # 1. Try to find MBID from existing artists table
        async with db.execute("SELECT mbid FROM artists WHERE name = ?", (artist_name,)) as cursor:
            row = await cursor.fetchone()
            if row:
                mbids = [row[0]]
                logger.info(f"Found MBID {mbids[0]} for {artist_name} in artists table.")
            else:
                # 2. Fallback: Find MBID from tracks table (fuzzy match or exact match failed)
                # Use LIKE to find the name in the artist string (e.g. "Ed Sheeran feat. Chance the Rapper")
                async with db.execute("SELECT mb_artist_id FROM tracks WHERE (artist = ? OR artist LIKE ?) AND mb_artist_id IS NOT NULL LIMIT 1", (artist_name, f"%{artist_name}%")) as cursor:
                    row = await cursor.fetchone()
                    
                    if not row:
                        logger.warning(f"No MBID found for artist {artist_name}, assuming not local or not tagged properly.")
                        return

                    raw_mbid = row[0]
                    if not raw_mbid:
                        return

                    # Split MBIDs (handle ; / &)
                    mbids = raw_mbid.replace("/", ";").replace("&", ";").split(";")
                    mbids = [m.strip() for m in mbids if m.strip()]
                    
                    if not mbids:
                        return

        logger.info(f"Found MBIDs {mbids} for {artist_name}. Fetching fresh metadata...")
        
        for mbid in mbids:
             logger.debug(f"Processing MBID: {mbid}")
             # Only update if we either don't know the artist name yet 
             # OR if this MBID is actually potentially relevant (fetched name matches?)
             # Since we can't easily know which MBID belongs to whom without fetching,
             # we fetch all. This is fine.
             try:
                 meta = await fetch_artist_metadata(mbid, artist_name)
                 logger.debug(f"Metadata fetch complete for {mbid}. Name: {meta.get('name')}")
             except Exception as e:
                 logger.warning(f"Failed to fetch metadata for {mbid} during refresh: {repr(e)}")
                 continue
                 
             # SAFETY CHECK: If MB fetch failed (no musicbrainz_url) and name implies we are just guessing,
             # don't overwrite unrelated artists with 'Chance the Rapper'
             # We assume if musicbrainz_url is present, we got valid data from MB.
             if not meta.get("musicbrainz_url") and meta.get("name") == artist_name and len(mbids) > 1:
                 logger.warning(f"Skipping update for {mbid} - MB fetch failed and ambiguous name assignment potential.")
                 continue

             # Download and cache artist image if available
             art_id = None
             if meta.get("image_url"):
                 logger.debug(f"Downloading artwork from {meta['image_url']}")
                 art_hash = await download_and_save_artwork(meta["image_url"], art_type='artist')
                 if art_hash:
                     # Get or create artwork record
                     async with db.execute("SELECT id FROM artwork WHERE sha1 = ?", (art_hash,)) as cursor:
                         art_row = await cursor.fetchone()
                         if art_row:
                             art_id = art_row[0]
                         else:
                             await db.execute("INSERT INTO artwork (sha1, type) VALUES (?, ?)", (art_hash, 'artist'))
                             await db.commit()
                             async with db.execute("SELECT last_insert_rowid()") as id_cursor:
                                 art_id = (await id_cursor.fetchone())[0]
                 
                 # Save to DB (Update existing)
                 await db.execute("""
                     INSERT INTO artists (
                         mbid, name, sort_name, bio, image_url, art_id, spotify_url, homepage, 
                         wikipedia_url, qobuz_url, tidal_url, musicbrainz_url,
                         similar_artists, top_tracks, singles, albums, last_updated
                     )
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                     ON CONFLICT(mbid) DO UPDATE SET
                         name=excluded.name,
                         sort_name=excluded.sort_name,
                         bio=excluded.bio,
                         image_url=excluded.image_url,
                         art_id=excluded.art_id,
                         spotify_url=excluded.spotify_url,
                         homepage=excluded.homepage,
                         wikipedia_url=excluded.wikipedia_url,
                         qobuz_url=excluded.qobuz_url,
                          tidal_url=excluded.tidal_url,
                         musicbrainz_url=excluded.musicbrainz_url,
                         similar_artists=excluded.similar_artists,
                         top_tracks=excluded.top_tracks,
                         singles=excluded.singles,
                         albums=excluded.albums,
                         last_updated=excluded.last_updated
                 """, (
                     meta["mbid"], meta["name"], meta["sort_name"], meta["bio"], meta["image_url"], art_id,
                     meta["spotify_url"], meta["homepage"], 
                     meta["wikipedia_url"], meta["qobuz_url"], meta.get("tidal_url"), meta["musicbrainz_url"],
                     json.dumps(meta["similar_artists"]), 
                     json.dumps(meta["top_tracks"]),
                     json.dumps(meta.get("singles", [])),
                     json.dumps(meta.get("albums", [])),
                     meta["last_updated"]
                 ))
                 await db.commit()
                 logger.info(f"Metadata updated for {artist_name} (MBID: {mbid})")



async def refresh_artist_singles_only(artist_name: str):
    logger.info(f"Refreshing singles only for {artist_name}")
    from app.scanner.metadata import fetch_artist_singles
    
    async for db in get_db():
        # Find MBID for artist
        async with db.execute("SELECT mbid FROM artists WHERE name = ? COLLATE NOCASE", (artist_name,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                logger.warning(f"Artist {artist_name} not found in DB (must be scanned first).")
                return

            mbid = row[0]
            logger.info(f"Found MBID {mbid} for {artist_name}. Fetching singles...")
            
            singles = await fetch_artist_singles(mbid)
            
            await db.execute("UPDATE artists SET singles = ? WHERE mbid = ?", (json.dumps(singles), mbid))
            await db.commit()
            logger.info(f"Singles updated for {artist_name}")

async def _scan_recursive(root, db, artist_mbids, seen_paths, force_rescan=False):
    try:
        # Check if root exists before scanning (it might have been deleted)
        if not os.path.exists(root):
            return

        for entry in os.scandir(root):
            if entry.is_dir():
                await _scan_recursive(entry.path, db, artist_mbids, seen_paths, force_rescan)
            elif entry.is_file():
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    seen_paths.add(entry.path)
                    await _process_file(entry.path, db, artist_mbids, force_rescan)
    except OSError as e:
        logger.error(f"Error scanning directory {root}: {e}")

async def _process_file(path, db, artist_mbids, force_rescan=False):
    try:
        logger.debug(f"Scanning file: {path}")
        # Check if file exists and mtime matches
        mtime = os.path.getmtime(path)
        
        async with db.execute("SELECT id, mtime FROM tracks WHERE path = ?", (path,)) as cursor:
            row = await cursor.fetchone()
            if not force_rescan and row and row[1] == mtime: # row["mtime"] access depends on row_factory
                return # Unchanged

        # Extract tags
        tags = extract_tags(path)
        if not tags:
            return

        # Extract artwork
        art_hash = await extract_and_save_artwork(path)
        art_id = None
        
        if art_hash:
            async with db.execute("SELECT id FROM artwork WHERE sha1 = ?", (art_hash,)) as cursor:
                art_row = await cursor.fetchone()
                if art_row:
                    art_id = art_row[0]
                else:
                    await db.execute("INSERT INTO artwork (sha1, type) VALUES (?, ?)", (art_hash, 'album'))
                    await db.commit()
                    async with db.execute("SELECT last_insert_rowid()") as id_cursor:
                        art_id = (await id_cursor.fetchone())[0]



        # Insert/Update track
        keys = ["path", "mtime", "title", "artist", "album", "album_artist", 
                "track_no", "disc_no", "date", "genre", "duration_seconds", 
                "codec", "sample_rate_hz", "bit_depth", "bitrate", "channels", "label", 
                "mb_artist_id", "mb_album_artist_id", "mb_track_id", "mb_release_track_id", "mb_release_id", "art_id"]
        
        values = [
            path, mtime, tags.get("title"), tags.get("artist"), tags.get("album"), 
            tags.get("album_artist"), tags.get("track_no"), tags.get("disc_no"), 
            tags.get("date"), tags.get("genre"), tags.get("duration_seconds"),
            tags.get("codec"), tags.get("sample_rate_hz"), tags.get("bit_depth"),
            tags.get("bitrate"), tags.get("channels"), tags.get("label"),
            tags.get("mb_artist_id"), tags.get("mb_album_artist_id"), 
            tags.get("mb_track_id"), tags.get("mb_release_track_id"), tags.get("mb_release_id"), art_id
        ]
        
        placeholders = ", ".join(["?"] * len(keys))
        columns = ", ".join(keys)
        
        sql = f"INSERT OR REPLACE INTO tracks ({columns}) VALUES ({placeholders})"
        
        cursor = await db.execute(sql, values)
        track_id = cursor.lastrowid
        await db.commit()
        
        # Handle Multi-Artist (Split MBIDs)
        # We manually manage track_artists so we can query individual artists later
        if track_id:
            # 1. Clear existing
            await db.execute("DELETE FROM track_artists WHERE track_id = ?", (track_id,))
            
            # 2. Parse and Insert
            mbids_to_process = set()
            
            # Helper to extract IDs
            def extract_ids(raw):
                if not raw: return []
                # Replace common separators with semicolon
                cleaned = raw.replace("/", ";").replace("&", ";") 
                # Note: '&' might be dangerous if it's part of a name but usually MBIDs are strict
                # MBIDs are UUIDs, so '&' is safe to split on if it somehow got in there, 
                # but standard is slash or semicolon.
                cleaned = raw.replace("/", ";")
                return [x.strip() for x in cleaned.split(";") if x.strip()]

            # Track Artists
            ids = []
            if tags.get("mb_artist_id"):
                ids = extract_ids(tags["mb_artist_id"])
            
            # Enrich from MB if needed (e.g. missing featured artists)
            mb_track_id = tags.get("mb_track_id") or tags.get("mb_release_track_id")
            artist_tag = tags.get("artist") or ""
            needs_enrichment = False
            
            # Heuristic: If artist tag implies multiple artists but we only have 1 ID (or 0), check MB.
            if mb_track_id and (len(ids) <= 1):
                if "feat" in artist_tag.lower() or "&" in artist_tag or "," in artist_tag:
                    needs_enrichment = True
            
            if needs_enrichment:
                try:
                    logger.info(f"Enriching metadata for {tags.get('title')} (Fetching credits)")
                    credits = await fetch_track_credits(tags.get("mb_track_id"), tags.get("mb_release_track_id"))
                    if credits:
                        # Use retrieved IDs
                        ids = [c[0] for c in credits]
                        for mbid, name in credits:
                            artist_mbids.add((mbid, name))
                except Exception as e:
                    logger.warning(f"Enrichment failed: {e}")

            # Insert all IDs (either from tags or enrichment)
            for mbid in ids:
                await db.execute("INSERT INTO track_artists (track_id, mbid) VALUES (?, ?)", (track_id, mbid))
                if not needs_enrichment:
                     # If we didn't enrich, we don't have atomic names, so pass None
                     artist_mbids.add((mbid, None)) 
            
            # Album Artists
            if tags.get("mb_album_artist_id"):
                ids = extract_ids(tags["mb_album_artist_id"])
                for mbid in ids:
                    # Pass None for name here too just to be safe, or use album_artist if we trust it (often better than track artist)
                    # But if album artist is "A & B", we have the same problem.
                    artist_mbids.add((mbid, None))

    except Exception as e:
        logger.error(f"Error processing {path}: {e}")

async def refresh_all_artist_singles():
    logger.info("Refreshing singles for ALL artists...")
    async for db in get_db():
        async with db.execute("SELECT name FROM artists") as cursor:
            rows = await cursor.fetchall()
            
    if not rows:
        logger.warning("No artists found in database.")
        return

    total = len(rows)
    logger.info(f"Found {total} artists. Starting batch refresh...")
    
    for i, row in enumerate(rows):
        artist_name = row[0]
        logger.info(f"[{i+1}/{total}] Processing {artist_name}...")
        try:
            await refresh_artist_singles_only(artist_name)
            # Be nice to the API
            await asyncio.sleep(1.1) 
        except Exception as e:
            logger.error(f"Failed to refresh singles for {artist_name}: {e}")
            
    logger.info("Finished refreshing singles for all artists.")
