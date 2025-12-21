
import asyncio
import logging
import sys
from app.db import get_db
from app.scanner.metadata import fetch_artist_metadata
import app.config as config

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def backfill_tidal():
    logger.info("Starting Tidal URL backfill...")
    
    conn_gen = get_db()
    db = await conn_gen.__anext__()
    
    try:
        # Get all artists with MBID
        async with db.execute("SELECT mbid, name, tidal_url FROM artists WHERE mbid IS NOT NULL") as cursor:
            artists = await cursor.fetchall()
            
        logger.info(f"Found {len(artists)} artists to check.")
        
        count = 0
        updated = 0
        
        for row in artists:
            mbid = row[0]
            name = row[1]
            existing_tidal = row[2]
            
            count += 1
            if existing_tidal:
                logger.debug(f"[{count}/{len(artists)}] Skipping {name} - Already has Tidal URL")
                continue
                
            logger.info(f"[{count}/{len(artists)}] Checking {name} ({mbid})...")
            
            try:
                # Reuse fetch_artist_metadata which now has Tidal logic
                # Note: We don't want to re-download images or anything, just get links.
                # fetch_artist_metadata does HTTP requests.
                
                meta = await fetch_artist_metadata(mbid, name)
                
                new_tidal = meta.get("tidal_url")
                if new_tidal:
                    logger.info(f"Found Tidal URL for {name}: {new_tidal}")
                    await db.execute("UPDATE artists SET tidal_url = ? WHERE mbid = ?", (new_tidal, mbid))
                    await db.commit()
                    updated += 1
                else:
                    logger.debug(f"No Tidal URL found for {name}")
                    
                # Rate limit
                await asyncio.sleep(1.1)
                
            except Exception as e:
                logger.error(f"Error processing {name}: {e}")
                
        logger.info(f"Backfill complete. Updated {updated} artists.")
        
    finally:
        await db.close()

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    asyncio.run(backfill_tidal())
