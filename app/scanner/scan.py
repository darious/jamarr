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

        # Get all MBIDs from DB
        async with db.execute("SELECT DISTINCT mb_artist_id, artist FROM tracks WHERE mb_artist_id IS NOT NULL") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                artist_mbids.add((row[0], row[1]))
    
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
                INSERT INTO artists (mbid, name, sort_name, bio, image_url, spotify_url, homepage, similar_artists, top_tracks, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mbid) DO UPDATE SET
                    name=excluded.name,
                    sort_name=excluded.sort_name,
                    bio=excluded.bio,
                    image_url=excluded.image_url,
                    spotify_url=excluded.spotify_url,
                    homepage=excluded.homepage,
                    similar_artists=excluded.similar_artists,
                    top_tracks=excluded.top_tracks,
                    last_updated=excluded.last_updated
            """, (
                meta["mbid"], meta["name"], meta["sort_name"], meta["bio"], meta["image_url"], 
                meta["spotify_url"], meta["homepage"], 
                json.dumps(meta["similar_artists"]), 
                json.dumps(meta["top_tracks"]),
                meta["last_updated"]
            ))
            await db.commit()
        break

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

        # Collect MBID
        if tags.get("mb_artist_id"):
            artist_mbids.add((tags["mb_artist_id"], tags.get("artist")))

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
        
        await db.execute(sql, values)
        await db.commit()

    except Exception as e:
        logger.error(f"Error processing {path}: {e}")
