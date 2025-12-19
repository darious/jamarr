from fastapi import APIRouter, Depends
from app.db import get_db
import aiosqlite
import json

router = APIRouter()

@router.get("/api/artists")
async def get_artists(db: aiosqlite.Connection = Depends(get_db)):
    # Return distinct artists with metadata
    query = """
        SELECT DISTINCT 
            a.name,
            a.image_url, 
            a.bio, 
            a.similar_artists,
            a.top_tracks,
            a.sort_name,
            a.homepage,
            a.spotify_url,
            a.wikipedia_url,
            a.qobuz_url,
            a.musicbrainz_url
        FROM artists a
        JOIN track_artists ta ON a.mbid = ta.mbid
        WHERE a.name IS NOT NULL 
        ORDER BY a.sort_name COLLATE NOCASE
    """
    async with db.execute(query) as cursor:
        rows = await cursor.fetchall()
        return [
            {
                "name": row[0], 
                "image_url": row[1], 
                "bio": row[2], 
                "similar_artists": json.loads(row[3]) if row[3] else [],
                "top_tracks": json.loads(row[4]) if row[4] else [],
                "sort_name": row[5] or row[0], # Fallback to name
                "homepage": row[6],
                "spotify_url": row[7],
                "wikipedia_url": row[8],
                "qobuz_url": row[9],
                "musicbrainz_url": row[10]
            } 
            for row in rows
        ]

@router.get("/api/albums")
@router.get("/api/albums")
async def get_albums(artist: str = None, db: aiosqlite.Connection = Depends(get_db)):
    # 1. If artist is provided, find their MBID to classify 'main' vs 'appears_on'
    target_mbid = None
    if artist:
        async with db.execute("SELECT mbid FROM artists WHERE name = ?", (artist,)) as cursor:
            row = await cursor.fetchone()
            if row:
                target_mbid = row[0]

    query = """
        SELECT 
            t.album, 
            t.art_id, 
            COALESCE(t.album_artist, t.artist) as artist_name,
            MAX(CASE WHEN t.bit_depth > 16 OR t.sample_rate_hz > 44100 THEN 1 ELSE 0 END) as is_hires,
            MIN(t.date) as year,
            COUNT(DISTINCT t.id) as track_count,
            SUM(t.duration_seconds) as total_duration,
            CASE 
                WHEN ? IS NOT NULL AND (t.mb_album_artist_id LIKE ? || '%' OR t.mb_album_artist_id = ?) THEN 'main'
                ELSE 'appears_on' 
            END as type
        FROM tracks t
    """
    params = [target_mbid, target_mbid, target_mbid]
    
    if artist:
        # Filter by any artist associated with the tracks via track_artists
        query += """
            JOIN track_artists ta ON t.id = ta.track_id
            JOIN artists a ON ta.mbid = a.mbid
            WHERE a.name = ?
        """
        params.append(artist)
    else:
        query += " WHERE t.album IS NOT NULL"
        
    query += " GROUP BY t.album ORDER BY year ASC"
    
    async with db.execute(query, params) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

@router.get("/api/tracks")
async def get_tracks(album: str = None, artist: str = None, db: aiosqlite.Connection = Depends(get_db)):
    # Base query
    # Use subquery to aggregate all artists for the track (Main + Feature)
    # This ensures "Taylor Swift, Ed Sheeran" is returned instead of just "Taylor Swift" tag
    query = """
        SELECT t.*, 
        (SELECT GROUP_CONCAT(a2.name, ', ') 
         FROM track_artists ta2 
         JOIN artists a2 ON ta2.mbid = a2.mbid 
         WHERE ta2.track_id = t.id) as aggregated_artists
        FROM tracks t
    """
    params = []
    
    query += " WHERE 1=1"
    
    if artist:
        # Relaxed filtering: Match Album Artist (tag), Artist (tag), or Linked Artist (DB)
        # This ensures tracks where the main artist is just the 'Album Artist' (e.g. tracks by guests) are included.
        query += """ AND (
            t.album_artist = ? 
            OR t.artist = ?
            OR EXISTS (
                SELECT 1 FROM track_artists ta 
                JOIN artists a ON ta.mbid = a.mbid 
                WHERE ta.track_id = t.id 
                AND (REPLACE(REPLACE(a.name, '’', ''''), '`', '''') = REPLACE(REPLACE(?, '’', ''''), '`', '''') OR a.name = ?)
            )
        )"""
        params.extend([artist, artist, artist, artist])
        
    if album:
        query += " AND t.album = ?"
        params.append(album)
        
    query += " ORDER BY t.disc_no, t.track_no"
    
    async with db.execute(query, params) as cursor:
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            d = dict(row)
            # Override artist tag with aggregated list if available
            if d.get("aggregated_artists"):
                d["artist"] = d["aggregated_artists"]
            results.append(d)
        return results
