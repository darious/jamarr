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
            COALESCE(t.album_artist, t.artist) as name,
            a.image_url, 
            a.bio, 
            a.similar_artists,
            a.top_tracks,
            a.sort_name
        FROM tracks t
        LEFT JOIN artists a ON t.mb_artist_id = a.mbid
        WHERE name IS NOT NULL 
        ORDER BY COALESCE(a.sort_name, name) COLLATE NOCASE
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
                "sort_name": row[5] or row[0] # Fallback to name
            } 
            for row in rows
        ]

@router.get("/api/albums")
async def get_albums(artist: str = None, db: aiosqlite.Connection = Depends(get_db)):
    query = """
        SELECT 
            album, 
            art_id, 
            COALESCE(album_artist, artist) as artist_name,
            MAX(CASE WHEN bit_depth > 16 OR sample_rate_hz > 44100 THEN 1 ELSE 0 END) as is_hires,
            MIN(date) as year,
            COUNT(*) as track_count,
            SUM(duration_seconds) as total_duration
        FROM tracks
        WHERE album IS NOT NULL
    """
    params = []
    
    if artist:
        query += " AND COALESCE(album_artist, artist) = ?"
        params.append(artist)
        
    query += " GROUP BY album ORDER BY year ASC"
    
    async with db.execute(query, params) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

@router.get("/api/tracks")
async def get_tracks(album: str = None, artist: str = None, db: aiosqlite.Connection = Depends(get_db)):
    query = "SELECT * FROM tracks WHERE 1=1"
    params = []
    
    if artist:
        query += " AND COALESCE(album_artist, artist) = ?"
        params.append(artist)
        
    if album:
        query += " AND album = ?"
        params.append(album)
        
    query += " ORDER BY disc_no, track_no"
    
    async with db.execute(query, params) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
