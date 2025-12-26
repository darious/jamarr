
import asyncio
import aiosqlite
import os
import shutil
import logging
import argparse
import sys

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clean_artist")

DB_PATH = "cache/library.sqlite"
ART_CACHE = "cache/art"

async def clean_artist_data(name=None, mbid=None):
    if not name and not mbid:
        logger.error("Must provide either Artist Name or MBID")
        return

    logger.info(f"Connecting to {DB_PATH}...")
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        artist_mbids = []
        
        # 1. Find Artist MBID(s)
        if mbid:
            artist_mbids = [mbid]
            # Verify existence
            async with db.execute("SELECT name FROM artists WHERE mbid = ?", (mbid,)) as c:
               row = await c.fetchone()
               if row:
                   logger.info(f"Identified artist: {row['name']} ({mbid})")
               else:
                   logger.warning(f"Artist MBID {mbid} not found in artists table. Proceeding to checking tracks...")

        elif name:
            async with db.execute("SELECT mbid, name, art_id FROM artists WHERE name LIKE ?", (f"%{name}%",)) as c:
                artists = await c.fetchall()
            
            if not artists:
                logger.info(f"No artist found matching '{name}' in artists table.")
            else:
                for row in artists:
                    logger.info(f"Found match: {row['name']} ({row['mbid']})")
                    artist_mbids.append(row["mbid"])

        if not artist_mbids:
            # Fallback: Check tracks if artist table is empty
            if name:
                 logger.info(f"Checking tracks for artist '{name}'...")
                 async with db.execute("SELECT DISTINCT mb_album_artist_id, album_artist FROM tracks WHERE album_artist LIKE ?", (f"%{name}%",)) as c:
                     rows = await c.fetchall()
                     for r in rows:
                         if r['mb_album_artist_id']:
                             logger.info(f"Found track artist: {r['album_artist']} ({r['mb_album_artist_id']})")
                             if r['mb_album_artist_id'] not in artist_mbids:
                                 artist_mbids.append(r['mb_album_artist_id'])

        if not artist_mbids:
            logger.error("No Artist MBIDs found. Aborting.")
            return

        logger.info(f"Targeting MBIDs: {artist_mbids}")
        
        # 2. Find Linked Albums
        album_mbids = set()
        # Via artist_albums
        for target_mbid in artist_mbids:
            async with db.execute("SELECT album_mbid FROM artist_albums WHERE artist_mbid = ?", (target_mbid,)) as c:
                rows = await c.fetchall()
                for r in rows: album_mbids.add(r[0])
        
        # Via tracks
        for target_mbid in artist_mbids:
             async with db.execute("SELECT DISTINCT mb_release_group_id FROM tracks WHERE mb_album_artist_id LIKE ?", (f"%{target_mbid}%",)) as c:
                rows = await c.fetchall()
                for r in rows: 
                    if r[0]: album_mbids.add(r[0])
                    
        logger.info(f"Found {len(album_mbids)} related Album MBIDs")

        # 3. Find Artwork to Delete
        art_ids = set()
        
        # Artist Art
        placeholders = ",".join("?" * len(artist_mbids))
        async with db.execute(f"SELECT art_id FROM artists WHERE mbid IN ({placeholders})", artist_mbids) as c:
            rows = await c.fetchall()
            for r in rows:
                if r[0]: art_ids.add(r[0])

        # Album Art
        for q_mbid in album_mbids:
            async with db.execute("SELECT art_id FROM albums WHERE mbid = ?", (q_mbid,)) as c:
                row = await c.fetchone()
                if row and row[0]: art_ids.add(row[0])
        
        # Track Art
        track_ids = []
        for target_mbid in artist_mbids:
             async with db.execute("SELECT id, art_id FROM tracks WHERE mb_artist_id LIKE ? OR mb_album_artist_id LIKE ?", (f"%{target_mbid}%", f"%{target_mbid}%")) as c:
                 rows = await c.fetchall()
                 for r in rows:
                     track_ids.append(r["id"])
                     if r["art_id"]: art_ids.add(r["art_id"])

        logger.info(f"Found {len(art_ids)} artwork IDs to verify/delete")
        
        # Resolve SHAs
        shas_to_delete = set()
        if art_ids:
            placeholders = ",".join("?" * len(art_ids))
            async with db.execute(f"SELECT sha1 FROM artwork WHERE id IN ({placeholders})", list(art_ids)) as c:
                rows = await c.fetchall()
                for r in rows: shas_to_delete.add(r[0])

        # 4. DELETE FILES
        files_deleted = 0
        if os.path.exists(ART_CACHE):
             # cache/art/ab/abcdef...
             for sha in shas_to_delete:
                 prefix = sha[:2]
                 path = os.path.join(ART_CACHE, prefix, sha)
                 if os.path.exists(path):
                     try:
                         os.remove(path)
                         files_deleted += 1
                     except Exception as e:
                         logger.error(f"Failed to delete {path}: {e}")
        
        logger.info(f"Deleted {files_deleted} artwork files from cache.")

        # 5. DELETE DB RECORDS
        logger.info("Deleting Database Records...")
        
        # Tracks
        if track_ids:
            t_placeholders = ",".join("?" * len(track_ids))
            await db.execute(f"DELETE FROM tracks WHERE id IN ({t_placeholders})", track_ids)
            await db.execute(f"DELETE FROM track_artists WHERE track_id IN ({t_placeholders})", track_ids)
        
        # Artist Data
        for target_mbid in artist_mbids:
             await db.execute("DELETE FROM artists WHERE mbid = ?", (target_mbid,))
             await db.execute("DELETE FROM artist_albums WHERE artist_mbid = ?", (target_mbid,))
             await db.execute("DELETE FROM external_links WHERE entity_type='artist' AND entity_id = ?", (target_mbid,))
             await db.execute("DELETE FROM tracks_top WHERE artist_mbid = ?", (target_mbid,))
             await db.execute("DELETE FROM similar_artists WHERE artist_mbid = ?", (target_mbid,))
             await db.execute("DELETE FROM artist_genres WHERE artist_mbid = ?", (target_mbid,))
             await db.execute("DELETE FROM missing_albums WHERE artist_mbid = ?", (target_mbid,))
             await db.execute("DELETE FROM image_mapping WHERE entity_type='artist' AND entity_id = ?", (target_mbid,))

        # Album Data
        for target_mbid in album_mbids:
            await db.execute("DELETE FROM albums WHERE mbid = ?", (target_mbid,))
            await db.execute("DELETE FROM external_links WHERE entity_type='album' AND entity_id = ?", (target_mbid,))
            await db.execute("DELETE FROM artist_albums WHERE album_mbid = ?", (target_mbid,))
            await db.execute("DELETE FROM missing_albums WHERE release_group_mbid = ?", (target_mbid,))
            await db.execute("DELETE FROM image_mapping WHERE entity_type='album' AND entity_id = ?", (target_mbid,))

        # Artwork records
        if art_ids:
            placeholders = ",".join("?" * len(art_ids))
            await db.execute(f"DELETE FROM artwork WHERE id IN ({placeholders})", list(art_ids))

        await db.commit()
        logger.info("Cleanup Complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean all data for a specific artist.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--name", type=str, help="Artist Name (partial match)")
    group.add_argument("--mbid", type=str, help="Artist MusicBrainz ID")
    
    args = parser.parse_args()
    
    asyncio.run(clean_artist_data(name=args.name, mbid=args.mbid))
