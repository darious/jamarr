import logging
import sys
import os
from typing import List, Dict, Any, Tuple

# Add project root to path if needed (might be handled by caller, but safe to ensure)
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import db
from app.matching import matcher

logger = logging.getLogger(__name__)

async def match_playlist_items(items: List[Dict[str, Any]], db_host: str = None) -> List[Tuple[str, str]]:
    """
    Match a list of playlist items against the database.
    
    Args:
        items: List of dicts with keys: 'artist', 'title', 'position', 'album' (optional)
        db_host: Optional database host override
        
    Returns:
        List of tuples (track_id, position)
    """
    if db_host:
        db.DB_HOST = db_host

    logger.info(f"Starting matching for {len(items)} tracks...")
    
    await db.init_db()
    
    matched_count = 0
    results = []
    
    try:
        conn = await db.get_pool().acquire()
        try:
            # Preload matcher data
            logger.info("Preloading match indexes...")
            artist_lookup = await matcher.preload_artist_lookup(conn)
            skip_artists = await matcher.preload_skip_artists(conn)
            
            # Prepare "scrobbles" for batch preloading
            scrobbles = []
            for item in items:
                scr = {
                    "artist_name": item["artist"],
                    "track_name": item["title"],
                    "album_name": item.get("album", ""),
                    "track_mbid": None,
                    "artist_mbid": None,
                    "album_mbid": None,
                    "id": item["position"]
                }
                scrobbles.append(scr)
            
            # Preload tracks
            indexes = await matcher.preload_tracks(conn, scrobbles, artist_lookup)
            
            # Perform matching
            logger.info("Matching tracks...")
            
            for scr in scrobbles:
                position = scr["id"]
                artist = scr["artist_name"]
                title = scr["track_name"]
                
                # Mock volume
                artist_volume = {matcher.normalize_artist(artist): 10} 
                
                match = matcher.match_scrobble(
                    scr,
                    indexes,
                    artist_lookup,
                    artist_volume,
                    skip_artists
                )
                
                if match:
                    track_id, score, method, reason = match
                    logger.info(f"#{position}: {title} - {artist} => MATCHED ({track_id}) [{method}]")
                    results.append((track_id, position))
                    matched_count += 1
                else:
                    logger.info(f"#{position}: {title} - {artist} => NO MATCH")

        finally:
            await db.get_pool().release(conn)
            
    finally:
        await db.close_db()
        
    logger.info(f"Done. Matched {matched_count}/{len(items)}.")
    return results
