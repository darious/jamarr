import os
import asyncio
import logging
import json
from app.db import get_db
from app.scanner.tags import extract_tags
from app.scanner.artwork import extract_and_save_artwork
from app.config import get_music_path
from app.scanner.metadata import fetch_artist_metadata

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aiff"}

async def scan_library(root_path: str = None, force_metadata: bool = False):
    if root_path is None:
        root_path = get_music_path()

    logger.info(f"Starting scan of {root_path}")
    
    if not os.path.exists(root_path):
        logger.error(f"Path not found: {root_path}")
        return

    # We'll collect MBIDs to fetch metadata for
    artist_mbids = set()

    async for db in get_db():
        await _scan_recursive(root_path, db, artist_mbids)
        
        logger.info("File scan complete. Updating artist metadata...")

        # Get all MBIDs from DB (Track Artists AND Album Artists)
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
    
        logger.info(f"Found {len(artist_mbids)} artists with MBIDs.")
    
        # Fetch metadata for artists
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
            
            # Save to DB
            await db.execute("""
                INSERT INTO artists (
                    mbid, name, sort_name, bio, image_url, spotify_url, homepage, 
                    wikipedia_url, qobuz_url, musicbrainz_url,
                    similar_artists, top_tracks, last_updated
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mbid) DO UPDATE SET
                    name=excluded.name,
                    sort_name=excluded.sort_name,
                    bio=excluded.bio,
                    image_url=excluded.image_url,
                    spotify_url=excluded.spotify_url,
                    homepage=excluded.homepage,
                    wikipedia_url=excluded.wikipedia_url,
                    qobuz_url=excluded.qobuz_url,
                    musicbrainz_url=excluded.musicbrainz_url,
                    similar_artists=excluded.similar_artists,
                    top_tracks=excluded.top_tracks,
                    last_updated=excluded.last_updated
            """, (
                meta["mbid"], meta["name"], meta["sort_name"], meta["bio"], meta["image_url"], 
                meta["spotify_url"], meta["homepage"], 
                meta["wikipedia_url"], meta["qobuz_url"], meta["musicbrainz_url"],
                json.dumps(meta["similar_artists"]), 
                json.dumps(meta["top_tracks"]),
                meta["last_updated"]
            ))
            await db.commit()
            await db.commit()
        break

async def refresh_artist_metadata(artist_name: str):
    logger.info(f"Forced metadata refresh for {artist_name}")
    async for db in get_db():
        # Find MBID for artist
        async with db.execute("SELECT mb_artist_id FROM tracks WHERE artist = ? AND mb_artist_id IS NOT NULL LIMIT 1", (artist_name,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                logger.warning(f"No MBID found for artist {artist_name}, assuming not local or not tagged properly.")
                # We could try to fetch by name, but for now strict MBID match is safer
                return

            mbid = row[0]
            logger.info(f"Found MBID {mbid} for {artist_name}. Fetching fresh metadata...")
            
            meta = await fetch_artist_metadata(mbid, artist_name)
            
            # Save to DB (Update existing)
            await db.execute("""
                INSERT INTO artists (
                    mbid, name, sort_name, bio, image_url, spotify_url, homepage, 
                    wikipedia_url, qobuz_url, musicbrainz_url,
                    similar_artists, top_tracks, last_updated
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mbid) DO UPDATE SET
                    name=excluded.name,
                    sort_name=excluded.sort_name,
                    bio=excluded.bio,
                    image_url=excluded.image_url,
                    spotify_url=excluded.spotify_url,
                    homepage=excluded.homepage,
                    wikipedia_url=excluded.wikipedia_url,
                    qobuz_url=excluded.qobuz_url,
                    musicbrainz_url=excluded.musicbrainz_url,
                    similar_artists=excluded.similar_artists,
                    top_tracks=excluded.top_tracks,
                    last_updated=excluded.last_updated
            """, (
                meta["mbid"], meta["name"], meta["sort_name"], meta["bio"], meta["image_url"], 
                meta["spotify_url"], meta["homepage"], 
                meta["wikipedia_url"], meta["qobuz_url"], meta["musicbrainz_url"],
                json.dumps(meta["similar_artists"]), 
                json.dumps(meta["top_tracks"]),
                meta["last_updated"]
            ))
            await db.commit()
            logger.info(f"Metadata updated for {artist_name}")

async def _scan_recursive(root, db, artist_mbids):
    for entry in os.scandir(root):
        if entry.is_dir():
            await _scan_recursive(entry.path, db, artist_mbids)
        elif entry.is_file():
            ext = os.path.splitext(entry.name)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                await _process_file(entry.path, db, artist_mbids)

async def _process_file(path, db, artist_mbids):
    try:
        logger.debug(f"Scanning file: {path}")
        # Check if file exists and mtime matches
        mtime = os.path.getmtime(path)
        
        async with db.execute("SELECT id, mtime FROM tracks WHERE path = ?", (path,)) as cursor:
            row = await cursor.fetchone()
            if row and row[1] == mtime: # row["mtime"] access depends on row_factory
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
                    await db.execute("INSERT INTO artwork (sha1) VALUES (?)", (art_hash,))
                    await db.commit()
                    async with db.execute("SELECT last_insert_rowid()") as id_cursor:
                        art_id = (await id_cursor.fetchone())[0]



        # Insert/Update track
        keys = ["path", "mtime", "title", "artist", "album", "album_artist", 
                "track_no", "disc_no", "date", "genre", "duration_seconds", 
                "codec", "sample_rate_hz", "bit_depth", "bitrate", "channels", "label", 
                "mb_artist_id", "mb_album_artist_id", "art_id"]
        
        values = [
            path, mtime, tags.get("title"), tags.get("artist"), tags.get("album"), 
            tags.get("album_artist"), tags.get("track_no"), tags.get("disc_no"), 
            tags.get("date"), tags.get("genre"), tags.get("duration_seconds"),
            tags.get("codec"), tags.get("sample_rate_hz"), tags.get("bit_depth"),
            tags.get("bitrate"), tags.get("channels"), tags.get("label"),
            tags.get("mb_artist_id"), tags.get("mb_album_artist_id"), art_id
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
            if tags.get("mb_artist_id"):
                ids = extract_ids(tags["mb_artist_id"])
                for mbid in ids:
                    await db.execute("INSERT INTO track_artists (track_id, mbid) VALUES (?, ?)", (track_id, mbid))
                    # Pass None for name so we fetch canonical name from MB instead of using the compound track artist string
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
