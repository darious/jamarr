from fastapi import APIRouter, Depends, HTTPException
from app.db import get_db
import aiosqlite
import json
from typing import List, Optional

from typing import List, Optional
from app.config import get_musicbrainz_root_url

router = APIRouter()

@router.get("/api/artists")
async def get_artists(db: aiosqlite.Connection = Depends(get_db)):
    # Return distinct artists with metadata
    query = """
        SELECT DISTINCT 
            a.name,
            a.image_url, 
            a.art_id,
            ar.sha1 as art_sha1,
            a.bio, 
            a.similar_artists,
            a.top_tracks,
            a.sort_name,
            a.homepage,
            a.spotify_url,
            a.wikipedia_url,
            a.qobuz_url,
            a.musicbrainz_url,
            a.singles,
            a.albums
        FROM artists a
        JOIN track_artists ta ON a.mbid = ta.mbid
        LEFT JOIN artwork ar ON a.art_id = ar.id
        WHERE a.name IS NOT NULL 
        ORDER BY a.sort_name COLLATE NOCASE
    """
    async with db.execute(query) as cursor:
        rows = await cursor.fetchall()
        return [
            {
                "name": row[0], 
                "image_url": row[1], 
                "art_id": row[2],
                "art_sha1": row[3],
                "bio": row[4], 
                "similar_artists": json.loads(row[5]) if row[5] else [],
                "top_tracks": json.loads(row[6]) if row[6] else [],
                "sort_name": row[7] or row[0], # Fallback to name
                "homepage": row[8],
                "spotify_url": row[9],
                "wikipedia_url": row[10],
                "qobuz_url": row[11],
                "musicbrainz_url": row[12],
                "singles": json.loads(row[13]) if row[13] else [],
                "albums": json.loads(row[14]) if row[14] else []
            } 
            for row in rows
        ]

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
            MAX(a.sha1) as art_sha1,
            COALESCE(t.album_artist, t.artist) as artist_name,
            MAX(CASE WHEN t.bit_depth > 16 OR t.sample_rate_hz > 44100 THEN 1 ELSE 0 END) as is_hires,
            MIN(t.date) as year,
            COUNT(DISTINCT t.id) as track_count,
            SUM(t.duration_seconds) as total_duration,
            MAX(t.mb_release_id) as mb_release_id,
            CASE 
                WHEN ? IS NOT NULL AND (t.mb_album_artist_id LIKE ? || '%' OR t.mb_album_artist_id = ?) THEN 'main'
                ELSE 'appears_on' 
            END as type
        FROM tracks t
        LEFT JOIN artwork a ON t.art_id = a.id
    """
    params = [target_mbid, target_mbid, target_mbid]
    
    if artist:
        # Filter by any artist associated with the tracks via track_artists
        query += """
            JOIN track_artists ta ON t.id = ta.track_id
            JOIN artists ar ON ta.mbid = ar.mbid
            WHERE ar.name = ?
        """
        params.append(artist)
    else:
        query += " WHERE t.album IS NOT NULL"
        
    query += " GROUP BY t.album ORDER BY year ASC"
    

    async with db.execute(query, params) as cursor:
        rows = await cursor.fetchall()
        mb_root = get_musicbrainz_root_url()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("mb_release_id"):
                d["musicbrainz_url"] = f"{mb_root}/release/{d['mb_release_id']}"
            results.append(d)
        return results

@router.get("/api/tracks")
async def get_tracks(album: str = None, artist: str = None, db: aiosqlite.Connection = Depends(get_db)):
    # Base query
    # Use subquery to aggregate all artists for the track (Main + Feature)
    # This ensures "Taylor Swift, Ed Sheeran" is returned instead of just "Taylor Swift" tag
    query = """
        SELECT t.*, 
        a.sha1 as art_sha1,
        (SELECT GROUP_CONCAT(a2.name, ', ') 
         FROM track_artists ta2 
         JOIN artists a2 ON ta2.mbid = a2.mbid 
         WHERE ta2.track_id = t.id) as aggregated_artists
        FROM tracks t
        LEFT JOIN artwork a ON t.art_id = a.id
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

@router.get("/api/home/new-releases")
async def get_new_releases(limit: int = 20, db: aiosqlite.Connection = Depends(get_db)):
    query = """
        SELECT 
            t.album, 
            t.art_id, 
            MAX(a.sha1) as art_sha1,
            COALESCE(t.album_artist, t.artist) as artist_name,
            MAX(CASE WHEN t.bit_depth > 16 OR t.sample_rate_hz > 44100 THEN 1 ELSE 0 END) as is_hires,
            MIN(t.date) as year,
            COUNT(DISTINCT t.id) as track_count,
            SUM(t.duration_seconds) as total_duration,
            MAX(t.mb_release_id) as mb_release_id,
            'main' as type
        FROM tracks t
        LEFT JOIN artwork a ON t.art_id = a.id
        WHERE t.album IS NOT NULL
        GROUP BY t.album
        ORDER BY year DESC, t.mtime DESC
        LIMIT ?
    """
    async with db.execute(query, (limit,)) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

@router.get("/api/home/recently-added-albums")
async def get_recently_added_albums(limit: int = 20, db: aiosqlite.Connection = Depends(get_db)):
    query = """
        SELECT 
            t.album, 
            t.art_id, 
            MAX(a.sha1) as art_sha1,
            COALESCE(t.album_artist, t.artist) as artist_name,
            MAX(CASE WHEN t.bit_depth > 16 OR t.sample_rate_hz > 44100 THEN 1 ELSE 0 END) as is_hires,
            MIN(t.date) as year,
            COUNT(DISTINCT t.id) as track_count,
            SUM(t.duration_seconds) as total_duration,
            MAX(t.mb_release_id) as mb_release_id,
            'main' as type
        FROM tracks t
        LEFT JOIN artwork a ON t.art_id = a.id
        WHERE t.album IS NOT NULL
        GROUP BY t.album
        ORDER BY MAX(t.id) DESC
        LIMIT ?
    """
    async with db.execute(query, (limit,)) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

@router.get("/api/home/recently-played-albums")
async def get_recently_played_albums(limit: int = 20, db: aiosqlite.Connection = Depends(get_db)):
    # Join playback_history to get specific albums
    query = """
        SELECT 
            t.album, 
            t.art_id, 
            MAX(a.sha1) as art_sha1,
            COALESCE(t.album_artist, t.artist) as artist_name,
            MAX(CASE WHEN t.bit_depth > 16 OR t.sample_rate_hz > 44100 THEN 1 ELSE 0 END) as is_hires,
            MIN(t.date) as year,
            COUNT(DISTINCT t.id) as track_count,
            SUM(t.duration_seconds) as total_duration,
            MAX(t.mb_release_id) as mb_release_id,
            MAX(ph.timestamp) as last_played
        FROM playback_history ph
        JOIN tracks t ON ph.track_id = t.id
        LEFT JOIN artwork a ON t.art_id = a.id
        WHERE t.album IS NOT NULL
        GROUP BY t.album
        ORDER BY last_played DESC
        LIMIT ?
    """
    async with db.execute(query, (limit,)) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

@router.get("/api/home/recently-played-artists")
async def get_recently_played_artists(limit: int = 20, db: aiosqlite.Connection = Depends(get_db)):
    query = """
        SELECT DISTINCT 
            a.name,
            a.image_url, 
            a.art_id,
            ar.sha1 as art_sha1,
            a.bio, 
            MAX(ph.timestamp) as last_played
        FROM playback_history ph
        JOIN tracks t ON ph.track_id = t.id
        JOIN track_artists ta ON t.id = ta.track_id
        JOIN artists a ON ta.mbid = a.mbid
        LEFT JOIN artwork ar ON a.art_id = ar.id
        WHERE a.name IS NOT NULL AND a.name != '' AND a.name != 'null'
        GROUP BY a.mbid
        ORDER BY last_played DESC
        LIMIT ?
    """
    async with db.execute(query, (limit,)) as cursor:
        rows = await cursor.fetchall()
        return [
            {
                "name": row[0], 
                "image_url": row[1], 
                "art_id": row[2],
                "art_sha1": row[3],
                "bio": row[4]
            } 
            for row in rows
        ]

@router.get("/api/home/discover-artists")
async def get_discover_artists(limit: int = 20, db: aiosqlite.Connection = Depends(get_db)):
    # Newly added artists (based on track mtime)
    query = """
        SELECT DISTINCT 
            a.name,
            a.image_url, 
            a.art_id,
            ar.sha1 as art_sha1,
            a.bio,
            MAX(t.id) as last_added
        FROM artists a
        JOIN track_artists ta ON a.mbid = ta.mbid
        JOIN tracks t ON ta.track_id = t.id
        LEFT JOIN artwork ar ON a.art_id = ar.id
        WHERE a.name IS NOT NULL AND a.name != '' AND a.name != 'null'
        GROUP BY a.mbid
        ORDER BY last_added DESC
        LIMIT ?
    """
    async with db.execute(query, (limit,)) as cursor:
        rows = await cursor.fetchall()
        return [
            {
                "name": row[0], 
                "image_url": row[1], 
                "art_id": row[2],
                "art_sha1": row[3],
                "bio": row[4]
            } 
            for row in rows
        ]
