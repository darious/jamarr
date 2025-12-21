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
            a.mbid,
            a.name,
            a.image_url, 
            a.art_id,
            ar.sha1 as art_sha1,
            a.bio,
            a.sort_name,
            MAX(CASE WHEN el.type = 'homepage' THEN el.url END) as homepage,
            MAX(CASE WHEN el.type = 'spotify' THEN el.url END) as spotify_url,
            MAX(CASE WHEN el.type = 'wikipedia' THEN el.url END) as wikipedia_url,
            MAX(CASE WHEN el.type = 'qobuz' THEN el.url END) as qobuz_url,
            MAX(CASE WHEN el.type = 'musicbrainz' THEN el.url END) as musicbrainz_url,
            MAX(CASE WHEN el.type = 'tidal' THEN el.url END) as tidal_url
        FROM artists a
        JOIN track_artists ta ON a.mbid = ta.mbid
        LEFT JOIN artwork ar ON a.art_id = ar.id
        LEFT JOIN external_links el ON a.mbid = el.entity_id AND el.entity_type = 'artist'
        WHERE a.name IS NOT NULL 
        GROUP BY a.mbid
        ORDER BY a.sort_name COLLATE NOCASE
    """
    async with db.execute(query) as cursor:
        rows = await cursor.fetchall()
        
        artists = []
        for row in rows:
            mbid = row[0]
            
            # Fetch top tracks for this artist
            top_tracks_query = """
                SELECT tt.*, t.id as local_track_id, t.title, t.album, t.codec, 
                       t.bit_depth, t.sample_rate_hz, t.duration_seconds
                FROM tracks_top tt
                LEFT JOIN tracks t ON tt.track_id = t.id
                WHERE tt.artist_mbid = ? AND tt.type = 'top'
                ORDER BY tt.rank
                LIMIT 50
            """
            async with db.execute(top_tracks_query, (mbid,)) as tt_cursor:
                tt_rows = await tt_cursor.fetchall()
                top_tracks = [
                    {
                        "name": tt_row["external_name"],
                        "album": tt_row["external_album"],
                        "date": tt_row["external_date"],
                        "duration_ms": tt_row["external_duration_ms"],
                        "popularity": tt_row["popularity"],
                        "local_track_id": tt_row["local_track_id"],
                        "codec": tt_row["codec"],
                        "bit_depth": tt_row["bit_depth"],
                        "sample_rate_hz": tt_row["sample_rate_hz"],
                        "duration_seconds": tt_row["duration_seconds"]
                    }
                    for tt_row in tt_rows
                ]
            
            # Fetch singles for this artist
            singles_query = """
                SELECT tt.*, t.id as local_track_id, t.title, t.album, t.codec,
                       t.bit_depth, t.sample_rate_hz
                FROM tracks_top tt
                LEFT JOIN tracks t ON tt.track_id = t.id
                WHERE tt.artist_mbid = ? AND tt.type = 'single'
                ORDER BY tt.external_date DESC
            """
            async with db.execute(singles_query, (mbid,)) as s_cursor:
                s_rows = await s_cursor.fetchall()
                singles = [
                    {
                        "mbid": s_row["external_mbid"],
                        "title": s_row["external_name"],
                        "date": s_row["external_date"],
                        "artist": row[1],  # artist name
                        "local_track_id": s_row["local_track_id"],
                        "codec": s_row["codec"],
                        "bit_depth": s_row["bit_depth"],
                        "sample_rate_hz": s_row["sample_rate_hz"]
                    }
                    for s_row in s_rows
                ]
            
            # Fetch similar artists for this artist
            similar_query = """
                SELECT sa.similar_artist_name, sa.similar_artist_mbid, 
                       a.image_url, a.art_id, ar.sha1 as art_sha1
                FROM similar_artists sa
                LEFT JOIN artists a ON sa.similar_artist_mbid = a.mbid
                LEFT JOIN artwork ar ON a.art_id = ar.id
                WHERE sa.artist_mbid = ?
                ORDER BY sa.rank
                LIMIT 10
            """
            async with db.execute(similar_query, (mbid,)) as sim_cursor:
                sim_rows = await sim_cursor.fetchall()
                similar_artists = [
                    {
                        "name": sim_row["similar_artist_name"],
                        "mbid": sim_row["similar_artist_mbid"],
                        "image_url": sim_row["image_url"],
                        "art_id": sim_row["art_id"],
                        "art_sha1": sim_row["art_sha1"]
                    }
                    for sim_row in sim_rows
                ]
            
            artists.append({
                "name": row[1], 
                "image_url": row[2], 
                "art_id": row[3],
                "art_sha1": row[4],
                "bio": row[5], 
                "similar_artists": similar_artists,
                "top_tracks": top_tracks,
                "sort_name": row[6] or row[1], # Fallback to name
                "homepage": row[7],
                "spotify_url": row[8],
                "wikipedia_url": row[9],
                "qobuz_url": row[10],
                "musicbrainz_url": row[11],
                "tidal_url": row[12],
                "singles": singles,
                "albums": []  # Deprecated
            })
        
        return artists

@router.get("/api/albums")
async def get_albums(artist: str = None, album_mbid: str = None, db: aiosqlite.Connection = Depends(get_db)):
    # 1. If artist is provided, find their MBID to classify 'main' vs 'appears_on'
    target_mbid = None
    if artist:
        async with db.execute(
            """
            SELECT mbid 
            FROM artists 
            WHERE LOWER(REPLACE(name, '‐', '-')) = LOWER(REPLACE(?, '‐', '-'))
            LIMIT 1
            """,
            (artist,),
        ) as cursor:
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
            COALESCE(al_rg.mbid, al_title.mbid) as album_mbid,
            MAX(CASE WHEN el.type = 'musicbrainz' THEN el.url END) as mb_link,
            CASE 
                WHEN ? IS NOT NULL AND (t.mb_album_artist_id LIKE ? || '%' OR t.mb_album_artist_id = ?) THEN 'main'
                ELSE 'appears_on' 
            END as type
        FROM tracks t
        LEFT JOIN artwork a ON t.art_id = a.id
        LEFT JOIN albums al_rg ON al_rg.mbid = t.mb_release_group_id
        LEFT JOIN albums al_title ON al_title.title = t.album
        LEFT JOIN external_links el ON el.entity_type = 'album' AND el.entity_id = COALESCE(al_rg.mbid, al_title.mbid)
    """
    params = [target_mbid, target_mbid, target_mbid]
    
    filters = []
    if artist:
        # Filter by any artist associated with the tracks via track_artists
        query += """
            JOIN track_artists ta ON t.id = ta.track_id
            JOIN artists ar ON ta.mbid = ar.mbid
        """
        filters.append("LOWER(REPLACE(ar.name, '‐', '-')) = LOWER(REPLACE(?, '‐', '-'))")
        params.append(artist)
    if album_mbid:
        filters.append("(t.mb_release_group_id = ? OR t.mb_release_id = ?)")
        params.extend([album_mbid, album_mbid])
    if filters:
        query += " WHERE " + " AND ".join(filters)
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
            elif d.get("mb_link"):
                d["musicbrainz_url"] = d["mb_link"]
            elif d.get("album_mbid"):
                d["musicbrainz_url"] = f"{mb_root}/release-group/{d['album_mbid']}"
            results.append(d)
        return results

@router.get("/api/tracks")
async def get_tracks(album: str = None, artist: str = None, album_mbid: str = None, db: aiosqlite.Connection = Depends(get_db)):
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
    
    if album_mbid:
        query += " AND (t.mb_release_group_id = ? OR t.mb_release_id = ?)"
        params.extend([album_mbid, album_mbid])
    if artist:
        # Relaxed filtering: Match Album Artist (tag), Artist (tag), or Linked Artist (DB)
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
