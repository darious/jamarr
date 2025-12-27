from fastapi import APIRouter, Depends, HTTPException
from app.db import get_db, optimize_db
import asyncpg
import json
from typing import List, Optional

from app.config import get_musicbrainz_root_url
from app.scanner.scan_manager import ScanManager
from app.media.image_lookup import fetch_primary_images

router = APIRouter()

@router.post("/api/scan/missing")
async def scan_missing_albums(artist: str = None, mbid: str = None):
    try:
        scan_manager = ScanManager.get_instance()
        await scan_manager.start_missing_albums_scan(artist_filter=artist, mbid_filter=mbid)
        return {"status": "started", "message": "Missing albums scan started"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/library/optimize")
async def trigger_optimize():
    try:
        await optimize_db()
        return {"status": "success", "message": "Database optimized"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/artists/{mbid}/missing")
async def get_missing_albums(mbid: str, db: asyncpg.Connection = Depends(get_db)):
    query = """
        SELECT 
            release_group_mbid as mbid,
            title,
            release_date,
            primary_type,
            image_url,
            musicbrainz_url,
            tidal_url,
            qobuz_url
        FROM missing_album
        WHERE artist_mbid = $1
        ORDER BY release_date DESC
    """
    rows = await db.fetch(query, mbid)
    return [dict(row) for row in rows]

@router.get("/api/artists")
async def get_artists(
    limit: int = 1000, 
    offset: int = 0, 
    name: Optional[str] = None, 
    mbid: Optional[str] = None, 
    db: asyncpg.Connection = Depends(get_db)
):
    # Base query for artist info
    query = """
        SELECT DISTINCT 
            a.mbid,
            a.name,
            a.image_url, 
            a.artwork_id,
            ar.sha1 as art_sha1,
            a.bio,
            a.sort_name,
            MAX(CASE WHEN el.type = 'homepage' THEN el.url END) as homepage,
            MAX(CASE WHEN el.type = 'spotify' THEN el.url END) as spotify_url,
            MAX(CASE WHEN el.type = 'wikipedia' THEN el.url END) as wikipedia_url,
            MAX(CASE WHEN el.type = 'qobuz' THEN el.url END) as qobuz_url,
            MAX(CASE WHEN el.type = 'musicbrainz' THEN el.url END) as musicbrainz_url,
            MAX(CASE WHEN el.type = 'tidal' THEN el.url END) as tidal_url,
            MAX(CASE WHEN el.type = 'lastfm' THEN el.url END) as lastfm_url,
            MAX(CASE WHEN el.type = 'discogs' THEN el.url END) as discogs_url,
            COALESCE(ac.primary_album_count, 0) as primary_album_count,
            COALESCE(ac.appears_on_album_count, 0) as appears_on_album_count
        FROM artist a
        JOIN track_artist ta ON a.mbid = ta.artist_mbid
        LEFT JOIN artwork ar ON a.artwork_id = ar.id
        LEFT JOIN external_link el ON a.mbid = el.entity_id AND el.entity_type = 'artist'
        LEFT JOIN (
            SELECT 
                ta.artist_mbid,
                COUNT(DISTINCT CASE WHEN t.album_artist_mbid LIKE ta.artist_mbid || '%' OR t.album_artist_mbid = ta.artist_mbid THEN t.album END) as primary_album_count,
                COUNT(DISTINCT CASE WHEN NOT (t.album_artist_mbid LIKE ta.artist_mbid || '%' OR t.album_artist_mbid = ta.artist_mbid) THEN t.album END) as appears_on_album_count
            FROM track t
            JOIN track_artist ta ON t.id = ta.track_id
            WHERE t.album IS NOT NULL
            GROUP BY ta.artist_mbid
        ) ac ON ac.artist_mbid = a.mbid
        WHERE a.name IS NOT NULL 
    """
    
    params = []
    param_num = 1
    if name:
        # citext handles case-insensitivity
        query += f" AND REPLACE(a.name, '‐', '-') = REPLACE(${param_num}, '‐', '-')"
        params.append(name)
        param_num += 1
    if mbid:
        query += f" AND a.mbid = ${param_num}"
        params.append(mbid)
        param_num += 1
        
    query += " GROUP BY a.mbid, a.name, a.image_url, a.artwork_id, ar.sha1, a.bio, a.sort_name, ac.primary_album_count, ac.appears_on_album_count ORDER BY a.sort_name"
    
    # Apply limit/offset only if not filtering by specific artist (which usually returns 1)
    if not name and not mbid:
        query += f" LIMIT ${param_num} OFFSET ${param_num + 1}"
        params.extend([limit, offset])
        param_num += 2

    rows = await db.fetch(query, *params)

    artist_ids = [r["mbid"] for r in rows]
    if not artist_ids:
        return []

    # Optimization: Only fetch primary images if we are returning a list
    # For single artist details, we might want backgrounds too
    artist_images = await fetch_primary_images(db, "artist", artist_ids, "artistthumb")
    
    # Only fetch background art if we are fetching a single artist or small number
    artist_backgrounds = {}
    if len(rows) <= 1: 
         artist_backgrounds = await fetch_primary_images(db, "artist", artist_ids, "artistbackground")

    artists = []
    for row in rows:
        mbid_val = row["mbid"]
        art_info = artist_images.get(mbid_val, {})
        bg_info = artist_backgrounds.get(mbid_val, {})
        
        artist_data = {
            "mbid": row["mbid"],
            "name": row["name"], 
            "image_url": row["image_url"], 
            "artwork_id": art_info.get("artwork_id") or row["artwork_id"],
            "art_sha1": art_info.get("art_sha1") or row["art_sha1"],
            "bio": row["bio"], 
            "sort_name": row["sort_name"] or row["name"],
            "homepage": row["homepage"],
            "spotify_url": row["spotify_url"],
            "wikipedia_url": row["wikipedia_url"],
            "qobuz_url": row["qobuz_url"],
            "lastfm_url": row["lastfm_url"],
            "discogs_url": row["discogs_url"],
            "musicbrainz_url": row["musicbrainz_url"],
            "tidal_url": row["tidal_url"],
            "primary_album_count": row["primary_album_count"],
            "appears_on_album_count": row["appears_on_album_count"],
            "albums": [],  # Deprecated
            "background_art_id": bg_info.get("artwork_id"),
            "background_sha1": bg_info.get("art_sha1"),
        }

        # If we are fetching a specific artist, populate the heavy details
        # Or if the result set is very small (1), we can assume it's a detail fetch
        if len(rows) == 1:
            # Fetch top tracks
            top_tracks_query = """
                SELECT tt.*, t.id as local_track_id, t.title, t.album, t.codec, 
                    t.bit_depth, t.sample_rate_hz, t.duration_seconds
                FROM top_track tt
                LEFT JOIN track t ON tt.track_id = t.id
                WHERE tt.artist_mbid = $1 AND tt.type = 'top'
                ORDER BY tt.rank
                LIMIT 50
            """
            tt_rows = await db.fetch(top_tracks_query, mbid_val)
            artist_data["top_tracks"] = [
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
            
            # Fetch singles
            singles_query = """
                SELECT tt.*, t.id as local_track_id, t.title, t.album, t.codec,
                    t.bit_depth, t.sample_rate_hz
                FROM top_track tt
                LEFT JOIN track t ON tt.track_id = t.id
                WHERE tt.artist_mbid = $1 AND tt.type = 'single'
                ORDER BY tt.external_date DESC
            """
            s_rows = await db.fetch(singles_query, mbid_val)
            artist_data["singles"] = [
                {
                    "mbid": s_row["external_mbid"],
                    "title": s_row["external_name"],
                    "date": s_row["external_date"],
                    "artist": row["name"],
                    "local_track_id": s_row["local_track_id"],
                    "codec": s_row["codec"],
                    "bit_depth": s_row["bit_depth"],
                    "sample_rate_hz": s_row["sample_rate_hz"]
                }
                for s_row in s_rows
            ]
            
            # Fetch similar artists
            similar_query = """
                SELECT sa.similar_artist_name, sa.similar_artist_mbid, 
                    a.image_url, a.artwork_id, ar.sha1 as art_sha1
                FROM similar_artist sa
                LEFT JOIN artist a ON sa.similar_artist_mbid = a.mbid
                LEFT JOIN artwork ar ON a.artwork_id = ar.id
                WHERE sa.artist_mbid = $1
                ORDER BY sa.rank
                LIMIT 10
            """
            sim_rows = await db.fetch(similar_query, mbid_val)
            sim_mbids = [r["similar_artist_mbid"] for r in sim_rows if r["similar_artist_mbid"]]
            sim_images = await fetch_primary_images(db, "artist", sim_mbids, "artistthumb") if sim_mbids else {}
            artist_data["similar_artists"] = []
            for sim_row in sim_rows:
                sim_mbid = sim_row["similar_artist_mbid"]
                sim_art = sim_images.get(sim_mbid, {}) if sim_mbid else {}
                artist_data["similar_artists"].append({
                    "name": sim_row["similar_artist_name"],
                    "mbid": sim_mbid,
                    "image_url": sim_row["image_url"],
                    "artwork_id": sim_art.get("artwork_id") or sim_row["artwork_id"],
                    "art_sha1": sim_art.get("art_sha1") or sim_row["art_sha1"],
                })

            # Fetch genres
            genres_query = """
                SELECT genre, count 
                FROM artist_genre 
                WHERE artist_mbid = $1
                ORDER BY count DESC
            """
            g_rows = await db.fetch(genres_query, mbid_val)
            artist_data["genres"] = [{"name": r["genre"], "count": r["count"]} for r in g_rows]
        
        else:
            # Lightweight response for lists
            artist_data["top_tracks"] = []
            artist_data["singles"] = []
            artist_data["similar_artists"] = []
            artist_data["genres"] = []
        
        artists.append(artist_data)
    
    return artists

@router.get("/api/albums")
async def get_albums(artist: str = None, album_mbid: str = None, db: asyncpg.Connection = Depends(get_db)):
    # 1. If artist is provided, find their MBID to classify 'main' vs 'appears_on'
    target_mbid = None
    if artist:
        row = await db.fetchrow(
            """
            SELECT mbid 
            FROM artist 
            WHERE REPLACE(name, '‐', '-') = REPLACE($1, '‐', '-')
            LIMIT 1
            """,
            artist,
        )
        if row:
            target_mbid = row["mbid"]

    query = """
        SELECT 
            t.album, 
            MAX(t.artwork_id) as artwork_id,
            MAX(a.sha1) as art_sha1,
            COALESCE(MAX(t.album_artist), MAX(t.artist)) as artist_name,
            MAX(CASE WHEN t.bit_depth > 16 OR t.sample_rate_hz > 44100 THEN 1 ELSE 0 END) as is_hires,
            MIN(t.date) as year,
            COUNT(DISTINCT t.id) as track_count,
            SUM(t.duration_seconds) as total_duration,
            MAX(t.release_mbid) as release_mbid,
            MAX(COALESCE(al_rg.mbid, al_title.mbid)) as album_mbid,
            MAX(CASE WHEN el.type = 'musicbrainz' THEN el.url END) as mb_link,
            MAX(CASE 
                WHEN $1::text IS NOT NULL AND (t.album_artist_mbid LIKE $1 || '%' OR t.album_artist_mbid = $1) THEN 'main'
                ELSE 'appears_on' 
            END) as type
        FROM track t
        LEFT JOIN artwork a ON t.artwork_id = a.id
        LEFT JOIN album al_rg ON al_rg.mbid = t.release_group_mbid
        LEFT JOIN album al_title ON al_title.title = t.album
        LEFT JOIN external_link el ON el.entity_type = 'album' AND el.entity_id = COALESCE(al_rg.mbid, al_title.mbid)
    """
    params = [target_mbid]
    param_num = 2
    
    filters = []
    if artist:
        # Filter by any artist associated with the tracks via track_artists
        query += """
            JOIN track_artist ta ON t.id = ta.track_id
            JOIN artist ar ON ta.artist_mbid = ar.mbid
        """
        filters.append(f"REPLACE(ar.name, '‐', '-') = REPLACE(${param_num}, '‐', '-')")
        params.append(artist)
        param_num += 1
    if album_mbid:
        filters.append(f"(t.release_group_mbid = ${param_num} OR t.release_mbid = ${param_num + 1})")
        params.extend([album_mbid, album_mbid])
        param_num += 2
    if filters:
        query += " WHERE " + " AND ".join(filters)
    else:
        query += " WHERE t.album IS NOT NULL"

    query += " GROUP BY t.album ORDER BY year ASC"
    

    rows = await db.fetch(query, *params)
    mb_root = get_musicbrainz_root_url()
    results = []
    for row in rows:
        d = dict(row)
        if d.get("release_mbid"):
            d["musicbrainz_url"] = f"{mb_root}/release/{d['release_mbid']}"
        elif d.get("mb_link"):
            d["musicbrainz_url"] = d["mb_link"]
        elif d.get("album_mbid"):
            d["musicbrainz_url"] = f"{mb_root}/release-group/{d['album_mbid']}"
        
        # Frontend compatibility: expects art_id
        if d.get("artwork_id"):
            d["art_id"] = d["artwork_id"]
            
        results.append(d)
    return results

@router.get("/api/tracks")
async def get_tracks(album: str = None, artist: str = None, album_mbid: str = None, db: asyncpg.Connection = Depends(get_db)):
    # Base query
    # Use subquery to aggregate all artists for the track (Main + Feature)
    # This ensures "Taylor Swift, Ed Sheeran" is returned instead of just "Taylor Swift" tag
    query = """
        SELECT t.*, 
        a.sha1 as art_sha1,
        (SELECT STRING_AGG(a2.name, ', ' ORDER BY a2.name) 
         FROM track_artist ta2 
         JOIN artist a2 ON ta2.artist_mbid = a2.mbid 
         WHERE ta2.track_id = t.id) as aggregated_artists
        FROM track t
        LEFT JOIN artwork a ON t.artwork_id = a.id
    """
    params = []
    param_num = 1
    
    query += " WHERE 1=1"
    
    if album_mbid:
        query += f" AND (t.release_group_mbid = ${param_num} OR t.release_mbid = ${param_num + 1})"
        params.extend([album_mbid, album_mbid])
        param_num += 2
    if artist:
        # Relaxed filtering: Match Album Artist (tag), Artist (tag), or Linked Artist (DB)
        query += f""" AND (
            t.album_artist = ${param_num}
            OR t.artist = ${param_num + 1}
            OR EXISTS (
                SELECT 1 FROM track_artist ta 
                JOIN artist a ON ta.artist_mbid = a.mbid 
                WHERE ta.track_id = t.id 
                AND (REPLACE(REPLACE(a.name, ''', ''''), '`', '''') = REPLACE(REPLACE(${param_num + 2}, ''', ''''), '`', '''') OR a.name = ${param_num + 3})
            )
        )"""
        params.extend([artist, artist, artist, artist])
        param_num += 4
    
    if album:
        query += f" AND t.album = ${param_num}"
        params.append(album)
        param_num += 1
        
    query += " ORDER BY t.disc_no, t.track_no"
    
    rows = await db.fetch(query, *params)
    results = []
    for row in rows:
        d = dict(row)
        # Override artist tag with aggregated list if available
        if d.get("aggregated_artists"):
            d["artist"] = d["aggregated_artists"]
        results.append(d)
    return results

@router.get("/api/home/new-releases")
async def get_new_releases(limit: int = 20, db: asyncpg.Connection = Depends(get_db)):
    query = """
        SELECT 
            t.album, 
            MAX(t.artwork_id) as artwork_id, 
            MAX(a.sha1) as art_sha1,
            COALESCE(MAX(t.album_artist), MAX(t.artist)) as artist_name,
            MAX(CASE WHEN t.bit_depth > 16 OR t.sample_rate_hz > 44100 THEN 1 ELSE 0 END) as is_hires,
            MIN(t.date) as year,
            COUNT(DISTINCT t.id) as track_count,
            SUM(t.duration_seconds) as total_duration,
            MAX(t.release_mbid) as release_mbid,
            'main' as type
        FROM track t
        LEFT JOIN artwork a ON t.artwork_id = a.id
        WHERE t.album IS NOT NULL
        GROUP BY t.album
        ORDER BY year DESC, MAX(t.updated_at) DESC
        LIMIT $1
    """
    rows = await db.fetch(query, limit)
    return [dict(row) for row in rows]

@router.get("/api/home/recently-added-albums")
async def get_recently_added_albums(limit: int = 20, db: asyncpg.Connection = Depends(get_db)):
    query = """
        SELECT 
            t.album, 
            MAX(t.artwork_id) as artwork_id, 
            MAX(a.sha1) as art_sha1,
            COALESCE(MAX(t.album_artist), MAX(t.artist)) as artist_name,
            MAX(CASE WHEN t.bit_depth > 16 OR t.sample_rate_hz > 44100 THEN 1 ELSE 0 END) as is_hires,
            MIN(t.date) as year,
            COUNT(DISTINCT t.id) as track_count,
            SUM(t.duration_seconds) as total_duration,
            MAX(t.release_mbid) as release_mbid,
            'main' as type
        FROM track t
        LEFT JOIN artwork a ON t.artwork_id = a.id
        WHERE t.album IS NOT NULL
        GROUP BY t.album
        ORDER BY MAX(t.id) DESC
        LIMIT $1
    """
    rows = await db.fetch(query, limit)
    return [dict(row) for row in rows]

@router.get("/api/home/recently-played-albums")
async def get_recently_played_albums(limit: int = 20, db: asyncpg.Connection = Depends(get_db)):
    # Join playback_history to get specific albums
    query = """
        SELECT 
            t.album, 
            MAX(t.artwork_id) as artwork_id, 
            MAX(a.sha1) as art_sha1,
            COALESCE(MAX(t.album_artist), MAX(t.artist)) as artist_name,
            MAX(CASE WHEN t.bit_depth > 16 OR t.sample_rate_hz > 44100 THEN 1 ELSE 0 END) as is_hires,
            MIN(t.date) as year,
            COUNT(DISTINCT t.id) as track_count,
            SUM(t.duration_seconds) as total_duration,
            MAX(t.release_mbid) as release_mbid,
            MAX(ph.timestamp) as last_played
        FROM playback_history ph
        JOIN track t ON ph.track_id = t.id
        LEFT JOIN artwork a ON t.artwork_id = a.id
        WHERE t.album IS NOT NULL
        GROUP BY t.album
        ORDER BY last_played DESC
        LIMIT $1
    """
    rows = await db.fetch(query, limit)
    return [dict(row) for row in rows]

@router.get("/api/home/recently-played-artists")
async def get_recently_played_artists(limit: int = 20, db: asyncpg.Connection = Depends(get_db)):
    query = """
        SELECT DISTINCT 
            a.name,
            a.image_url, 
            a.artwork_id,
            ar.sha1 as art_sha1,
            a.bio, 
            MAX(ph.timestamp) as last_played
        FROM playback_history ph
        JOIN track t ON ph.track_id = t.id
        JOIN track_artist ta ON t.id = ta.track_id
        JOIN artist a ON ta.artist_mbid = a.mbid
        LEFT JOIN artwork ar ON a.artwork_id = ar.id
        WHERE a.name IS NOT NULL AND a.name != '' AND a.name != 'null'
        GROUP BY a.mbid, a.name, a.image_url, a.artwork_id, ar.sha1, a.bio
        ORDER BY last_played DESC
        LIMIT $1
    """
    rows = await db.fetch(query, limit)
    return [
        {
            "name": row["name"], 
            "image_url": row["image_url"], 
            "artwork_id": row["artwork_id"],
            "art_sha1": row["art_sha1"],
            "bio": row["bio"]
        } 
        for row in rows
    ]

@router.get("/api/home/discover-artists")
async def get_discover_artists(limit: int = 20, db: asyncpg.Connection = Depends(get_db)):
    # Newly added artists (based on track mtime)
    query = """
        SELECT DISTINCT 
            a.name,
            a.image_url, 
            a.artwork_id,
            ar.sha1 as art_sha1,
            a.bio,
            MAX(t.id) as last_added
        FROM artist a
        JOIN track_artist ta ON a.mbid = ta.artist_mbid
        JOIN track t ON ta.track_id = t.id
        LEFT JOIN artwork ar ON a.artwork_id = ar.id
        WHERE a.name IS NOT NULL AND a.name != '' AND a.name != 'null'
        GROUP BY a.mbid, a.name, a.image_url, a.artwork_id, ar.sha1, a.bio
        ORDER BY last_added DESC
        LIMIT $1
    """
    rows = await db.fetch(query, limit)
    return [
        {
            "name": row["name"], 
            "image_url": row["image_url"], 
            "artwork_id": row["artwork_id"],
            "art_sha1": row["art_sha1"],
            "bio": row["bio"]
        } 
        for row in rows
    ]
