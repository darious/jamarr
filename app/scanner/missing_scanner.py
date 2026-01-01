import logging
from app.db import get_pool
from app.scanner.services import musicbrainz
from app.scanner.core import get_shared_client

logger = logging.getLogger("scanner.missing")

class MissingAlbumsScanner:
    def __init__(self):
        self.db = get_pool()
    
    async def scan(self, artist_filter: str = None, mbid_filter: str = None):
        """
        Scans for missing albums (Release Groups) from MusicBrainz for local artists.
        """
        logger.info("Starting Missing Albums Scan...")

        try:
             # 1. Get Artists
             query = "SELECT DISTINCT a.mbid, a.name FROM artist a"
             params = []
             clauses = []
             joins = []
             
             if mbid_filter:
                 if isinstance(mbid_filter, (list, set, tuple)):
                     filtered = [m for m in mbid_filter if m]
                     if filtered:
                         clauses.append(f"a.mbid = ANY(${len(params) + 1}::text[])")
                         params.append(filtered)
                 else:
                     clauses.append(f"a.mbid = ${len(params) + 1}")
                     params.append(mbid_filter)
             elif artist_filter:
                 clauses.append(f"a.name ILIKE ${len(params) + 1}")
                 params.append(f"%{artist_filter}%")
             else:
                 # Default: Only Primary Artists
                 joins.append("JOIN artist_album aa ON a.mbid = aa.artist_mbid AND aa.type = 'primary'")
                 
             if joins:
                 query += " " + " ".join(joins)
             if clauses:
                 query += " WHERE " + " AND ".join(clauses)
                 
             async with self.db.acquire() as conn:
                 artists = await conn.fetch(query, *params)
             
             total = len(artists)
             processed = 0
             
             # Use shared client
             client = get_shared_client()
                 
             for row in artists:
                     processed += 1
                     mbid, name = row["mbid"], row["name"]
                     current_name = name or "Unknown"
                     
                     # Local RGs
                     async with self.db.acquire() as conn:
                         rows = await conn.fetch("""
                             SELECT al.release_group_mbid 
                             FROM artist_album aa 
                             JOIN album al ON aa.album_mbid = al.mbid 
                             WHERE aa.artist_mbid = $1
                         """, mbid)
                         local_rgs = {r[0] for r in rows}
                         
                         await conn.execute("DELETE FROM missing_album WHERE artist_mbid = $1", mbid)
                     
                     try:
                         # Fetch MB Albums (using clean logic)
                         mb_albums = await musicbrainz.fetch_release_groups(mbid, "album", client)
                         
                         for album in mb_albums:
                             rg_id = album["mbid"]
                             if rg_id in local_rgs:
                                 continue
                             
                             # Insert
                             async with self.db.acquire() as conn:
                                 await conn.execute("""
                                     INSERT INTO missing_album
                                     (artist_mbid, release_group_mbid, title, release_date, primary_type, musicbrainz_url, updated_at)
                                     VALUES ($1, $2, $3, $4, 'Album', $5, NOW())
                                     ON CONFLICT (artist_mbid, release_group_mbid) DO NOTHING
                                 """, mbid, rg_id, album["title"], album["date"], album.get("musicbrainz_url"))
                                 
                     except Exception as e:
                         logger.warning(f"Error checking missing albums for {current_name}: {e}")
                         
             logger.info(f"Missing albums scan complete. Checked {processed}/{total} artists.")
             
        except Exception as e:
            logger.error(f"Missing Album Scan Failed: {e}")
