import logging
from app.db import get_pool
from app.scanner.services import musicbrainz
from app.scanner.core import get_shared_client

logger = logging.getLogger("scanner.missing")

class MissingAlbumsScanner:
    def __init__(self, progress_callback=None):
        self.db = get_pool()
        self.progress_callback = progress_callback
    
    async def scan(self, artist_filter: str = None, mbid_filter: str = None, path_filter: str = None):
        """
        Scans for missing albums (Release Groups) from MusicBrainz for local artists.
        
        Args:
            artist_filter: Filter by artist name
            mbid_filter: Filter by artist MBID(s)
            path_filter: Filter by music path (will resolve to MBIDs)
        """
        logger.info("Starting Missing Albums Scan...")

        try:
            # 1. Resolve path filter to MBIDs if provided
            path_mbids = None
            if path_filter:
                # Normalize path: strip music root if present
                from app.config import get_music_path
                import os
                
                music_root = get_music_path()
                if path_filter.startswith(music_root):
                    # Strip music root to get relative path
                    relative_path = os.path.relpath(path_filter, music_root)
                    logger.info(f"Normalized path '{path_filter}' to '{relative_path}'")
                    path_filter = relative_path
                
                async with self.db.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT DISTINCT ta.artist_mbid 
                        FROM track_artist ta
                        JOIN track t ON ta.track_id = t.id
                        WHERE t.path LIKE $1
                    """, f"{path_filter}%")
                    path_mbids = {r[0] for r in rows if r[0]}
                    logger.info(f"Path filter '{path_filter}' resolved to {len(path_mbids)} artists")
            
            # 2. Get Artists
            query = "SELECT DISTINCT a.mbid, a.name FROM artist a"
            params = []
            clauses = []
            joins = []
            
            # Apply path filter first (most restrictive)
            if path_mbids is not None:
                if not path_mbids:
                    logger.info("No artists found in specified path")
                    return
                clauses.append(f"a.mbid = ANY(${len(params) + 1}::text[])")
                params.append(list(path_mbids))
            elif mbid_filter:
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
            found_missing = 0
            
            logger.info(f"Scanning {total} artists for missing albums")
            
            # Use shared client
            client = get_shared_client()
                
            for row in artists:
                processed += 1
                mbid, name = row["mbid"], row["name"]
                current_name = name or "Unknown"
                
                # Update progress
                if self.progress_callback:
                    self.progress_callback(
                        processed, 
                        total, 
                        f"Checking {current_name}"
                    )
                
                # Skip Various Artists to avoid performance issues
                if mbid == "89ad4ac3-39f7-470e-963a-56509c546377" or current_name == "Various Artists":
                    logger.info(f"Skipping scanning for {current_name} (Various Artists) - too many releases.")
                    continue

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
                    
                    artist_missing_count = 0
                    for album in mb_albums:
                        rg_id = album["mbid"]
                        if rg_id in local_rgs:
                            continue
                        
                        artist_missing_count += 1
                        
                        # Insert
                        async with self.db.acquire() as conn:
                            await conn.execute("""
                                INSERT INTO missing_album
                                (artist_mbid, release_group_mbid, title, release_date, primary_type, musicbrainz_url, updated_at)
                                VALUES ($1, $2, $3, $4, 'Album', $5, NOW())
                                ON CONFLICT (artist_mbid, release_group_mbid) DO NOTHING
                            """, mbid, rg_id, album["title"], album["date"], album.get("musicbrainz_url"))
                    
                    if artist_missing_count > 0:
                        found_missing += artist_missing_count
                        logger.info(f"{current_name}: Found {artist_missing_count} missing albums")
                            
                except Exception as e:
                    logger.warning(f"Error checking missing albums for {current_name}: {e}")
                        
            logger.info(f"Missing albums scan complete. Checked {processed}/{total} artists, found {found_missing} missing albums.")
            
        except Exception as e:
            logger.error(f"Missing Album Scan Failed: {e}")
