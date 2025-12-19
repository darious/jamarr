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
    query = """
        SELECT 
            t.album, 
            t.art_id, 
            COALESCE(t.album_artist, t.artist) as artist_name,
            MAX(CASE WHEN t.bit_depth > 16 OR t.sample_rate_hz > 44100 THEN 1 ELSE 0 END) as is_hires,
            MIN(t.date) as year,
            COUNT(DISTINCT t.id) as track_count,
            SUM(t.duration_seconds) as total_duration
        FROM tracks t
    """
    params = []
    
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
    query = "SELECT t.* FROM tracks t"
    params = []
    
    # Joins for filtering
    if artist:
        query += """
            JOIN track_artists ta ON t.id = ta.track_id
            JOIN artists a ON ta.mbid = a.mbid
        """
    
    query += " WHERE 1=1"
    
    if artist:
        # Normalize quotes for comparison (handling smart quotes vs straight quotes)
        # This is a bit hacky in SQL, but effective
        query += " AND (REPLACE(REPLACE(a.name, '’', ''''), '`', '''') = REPLACE(REPLACE(?, '’', ''''), '`', '''') OR a.name = ?)"
        # Also try to match against track tags if canonical match fails? 
        # Actually, if we are filtering by artist, we really want the canonical artist.
        # But if the user navigated from an album page where the artist string came from a tag...
        params.append(artist)
        params.append(artist)
        
    if album:
        query += " AND t.album = ?"
        params.append(album)
        
    query += " ORDER BY t.disc_no, t.track_no"
    
    async with db.execute(query, params) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
