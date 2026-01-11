from fastapi import APIRouter, Depends, HTTPException
from app.db import get_db, optimize_db
import asyncpg
from typing import Optional

from app.config import get_musicbrainz_root_url, get_pearlarr_url
from app.scanner.scan_manager import ScanManager
from app.media.image_lookup import fetch_primary_images
from pydantic import BaseModel
import httpx
import logging

logger = logging.getLogger("api.library")

router = APIRouter()


def sha1_to_hex(sha1_value):
    """Convert binary SHA1 to hex string if needed"""
    if sha1_value and isinstance(sha1_value, bytes):
        return sha1_value.hex()
    return sha1_value


class PearlarrDownloadRequest(BaseModel):
    mbid: str

@router.post("/api/scan/missing")
async def scan_missing_albums(artist: str = None, mbid: str = None):
    try:
        scan_manager = ScanManager.get_instance()
        await scan_manager.start_missing_albums_scan(
            artist_filter=artist, mbid_filter=mbid
        )
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
            ma.release_group_mbid as mbid,
            ma.title,
            ma.release_date,
            ma.primary_type,
            ma.musicbrainz_url
        FROM missing_album ma
        LEFT JOIN album a ON ma.release_group_mbid = a.release_group_mbid
        WHERE ma.artist_mbid = $1 AND a.mbid IS NULL
        ORDER BY ma.release_date DESC
    """
    rows = await db.fetch(query, mbid)
    return [dict(row) for row in rows]


@router.post("/api/download/pearlarr")
async def download_pearlarr(req: PearlarrDownloadRequest):
    pearlarr_url = get_pearlarr_url()
    if not pearlarr_url:
        raise HTTPException(status_code=500, detail="Pearlarr URL not configured")

    try:
        async with httpx.AsyncClient() as client:
            # Pearlarr expects {"url": "MBID"}
            payload = {"url": req.mbid}
            resp = await client.post(pearlarr_url, json=payload, timeout=5.0)
            
            if resp.status_code >= 400:
                 logger.error(f"Pearlarr returned {resp.status_code}: {resp.text}")
                 raise HTTPException(status_code=500, detail=f"Pearlarr error: {resp.status_code}")
                 
            return {"status": "queued", "message": "Download queued via Pearlarr"}
    except Exception as e:
        logger.error(f"Failed to trigger Pearlarr download: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/artists/index")
async def get_artist_index(
    db: asyncpg.Connection = Depends(get_db),
):
    query = """
        SELECT DISTINCT letter
        FROM artist
        WHERE name IS NOT NULL AND letter IS NOT NULL
        ORDER BY letter
    """
    rows = await db.fetch(query)
    return [row["letter"] for row in rows]


@router.get("/api/artists")
async def get_artists(
    limit: int = 1000,
    offset: int = 0,
    name: Optional[str] = None,
    mbid: Optional[str] = None,
    starts_with: Optional[str] = None,
    db: asyncpg.Connection = Depends(get_db),
):
    if not name and not mbid:
        query = """
            SELECT 
                a.mbid,
                a.name,
                a.sort_name,
                a.bio,
                ar.sha1 as art_sha1,
                COALESCE(ac.primary_album_count, 0) as primary_album_count,
                COALESCE(ac.appears_on_album_count, 0) as appears_on_album_count
            FROM artist a
            LEFT JOIN artwork ar ON a.artwork_id = ar.id
            LEFT JOIN (
                SELECT 
                    artist_mbid,
                    COUNT(DISTINCT CASE WHEN type = 'primary' THEN album_mbid END) as primary_album_count,
                    COUNT(DISTINCT CASE WHEN type = 'contributor' THEN album_mbid END) as appears_on_album_count
                FROM artist_album
                GROUP BY artist_mbid
            ) ac ON ac.artist_mbid = a.mbid
            WHERE a.name IS NOT NULL
        """
        params = []
        if starts_with:
            letter = "#" if starts_with == "#" else starts_with.upper()
            query += " AND a.letter = $1"
            params.append(letter)
        query += " ORDER BY LOWER(COALESCE(a.sort_name, a.name)), a.sort_name, a.name"

        rows = await db.fetch(query, *params)
        return [
            {
                "mbid": row["mbid"],
                "name": row["name"],
                "sort_name": row["sort_name"],
                "bio": row["bio"],
                "art_sha1": sha1_to_hex(row["art_sha1"]),
                "primary_album_count": row["primary_album_count"],
                "appears_on_album_count": row["appears_on_album_count"],
            }
            for row in rows
        ]

    # Base query for artist info
    query = """
        SELECT 
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
            COALESCE(ac.appears_on_album_count, 0) as appears_on_album_count,
            COALESCE(lp.listens, 0) as listens
        FROM artist a
        LEFT JOIN artwork ar ON a.artwork_id = ar.id
        LEFT JOIN external_link el ON a.mbid = el.entity_id AND el.entity_type = 'artist'
        LEFT JOIN (
            SELECT 
                artist_mbid,
                COUNT(DISTINCT CASE WHEN type = 'primary' THEN album_mbid END) as primary_album_count,
                COUNT(DISTINCT CASE WHEN type = 'contributor' THEN album_mbid END) as appears_on_album_count
                FROM artist_album
                GROUP BY artist_mbid
        ) ac ON ac.artist_mbid = a.mbid
        LEFT JOIN (
            SELECT ta.artist_mbid, COUNT(DISTINCT source_id) as listens
            FROM combined_playback_history h
            JOIN track_artist ta ON ta.track_id = h.track_id
            GROUP BY ta.artist_mbid
        ) lp ON lp.artist_mbid = a.mbid
        WHERE a.name IS NOT NULL 
          AND (
              EXISTS (SELECT 1 FROM track_artist ta WHERE ta.artist_mbid = a.mbid)
              OR EXISTS (SELECT 1 FROM artist_album aa WHERE aa.artist_mbid = a.mbid)
          )
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
    if starts_with:
        if starts_with == "#":
            # Filter for non-alphabetic, allowing for common punctuation/numbers
            query += " AND a.sort_name !~* '^[a-z]'"
        elif len(starts_with) == 1:
            query += f" AND a.sort_name ILIKE ${param_num} || '%'"
            params.append(starts_with)
            param_num += 1

    query += (
        " GROUP BY a.mbid, a.name, a.image_url, a.artwork_id, ar.sha1, a.bio, a.sort_name, ac.primary_album_count, ac.appears_on_album_count, lp.listens"
        " ORDER BY LOWER(a.sort_name), a.sort_name"
    )

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
        artist_backgrounds = await fetch_primary_images(
            db, "artist", artist_ids, "artistbackground"
        )

    artists = []
    for row in rows:
        mbid_val = row["mbid"]
        art_info = artist_images.get(mbid_val, {})
        bg_info = artist_backgrounds.get(mbid_val, {})

        artist_data = {
            "mbid": row["mbid"],
            "name": row["name"],
            "image_url": row["image_url"],
            "art_sha1": sha1_to_hex(art_info.get("art_sha1") or row["art_sha1"]),
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
            "listens": row["listens"],
            "albums": [],  # Deprecated
            "background_sha1": sha1_to_hex(bg_info.get("art_sha1")),
        }

        # If we are fetching a specific artist, populate the heavy details
        # Or if the result set is very small (1), we can assume it's a detail fetch
        if len(rows) == 1:
            # Fetch top tracks
            top_tracks_query = """
                SELECT tt.*, t.id as local_track_id, t.title, t.album, t.codec, 
                    t.bit_depth, t.sample_rate_hz, t.duration_seconds,
                    a.sha1 as art_sha1, t.artwork_id, t.release_mbid as mb_release_id
                FROM top_track tt
                LEFT JOIN track t ON tt.track_id = t.id
                LEFT JOIN artwork a ON t.artwork_id = a.id
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
                    "duration_seconds": tt_row["duration_seconds"],
                    "art_sha1": sha1_to_hex(tt_row["art_sha1"]),
                    "mb_release_id": tt_row["mb_release_id"],
                }
                for tt_row in tt_rows
            ]

            # Fetch singles
            singles_query = """
                SELECT tt.*, t.id as local_track_id, t.title, t.album, t.codec,
                    t.bit_depth, t.sample_rate_hz,
                    a.sha1 as art_sha1, t.artwork_id, t.release_mbid as mb_release_id
                FROM top_track tt
                LEFT JOIN track t ON tt.track_id = t.id
                LEFT JOIN artwork a ON t.artwork_id = a.id
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
                    "sample_rate_hz": s_row["sample_rate_hz"],
                    "art_sha1": sha1_to_hex(s_row["art_sha1"]),
                    "album": s_row["album"],
                    "mb_release_id": s_row["mb_release_id"],
                }
                for s_row in s_rows
            ]

            # Fetch similar artists
            similar_query = """
                SELECT sa.similar_artist_name, sa.similar_artist_mbid, 
                    a.mbid as joined_mbid, a.image_url, a.artwork_id, ar.sha1 as art_sha1
                FROM similar_artist sa
                LEFT JOIN artist a ON sa.similar_artist_mbid = a.mbid
                LEFT JOIN artwork ar ON a.artwork_id = ar.id
                WHERE sa.artist_mbid = $1
                ORDER BY sa.rank
                LIMIT 10
            """
            sim_rows = await db.fetch(similar_query, mbid_val)
            sim_mbids = [
                r["similar_artist_mbid"] for r in sim_rows if r["similar_artist_mbid"]
            ]
            sim_images = (
                await fetch_primary_images(db, "artist", sim_mbids, "artistthumb")
                if sim_mbids
                else {}
            )
            artist_data["similar_artists"] = []
            mb_root = get_musicbrainz_root_url()
            for sim_row in sim_rows:
                sim_mbid = sim_row["similar_artist_mbid"]
                sim_art = sim_images.get(sim_mbid, {}) if sim_mbid else {}
                
                # Check if artist exists in our local library (joined_mbid not null)
                in_library = sim_row["joined_mbid"] is not None
                
                # Construct external/fallback URLs
                external_url = None
                if not in_library:
                    if sim_mbid:
                        external_url = f"{mb_root}/artist/{sim_mbid}"
                    else:
                        # Fallback to Google Search if no MBID
                        from urllib.parse import quote
                        external_url = f"https://www.google.com/search?q={quote(sim_row['similar_artist_name'])}"
                
                artist_data["similar_artists"].append(
                    {
                        "name": sim_row["similar_artist_name"],
                        "mbid": sim_mbid,
                        "image_url": sim_row["image_url"],
                        "art_sha1": sha1_to_hex(sim_art.get("art_sha1") or sim_row["art_sha1"]),
                        "in_library": in_library,
                        "external_url": external_url
                    }
                )

            # Fetch genres
            genres_query = """
                SELECT genre, count 
                FROM artist_genre 
                WHERE artist_mbid = $1
                ORDER BY count DESC
            """
            g_rows = await db.fetch(genres_query, mbid_val)
            artist_data["genres"] = [
                {"name": r["genre"], "count": r["count"]} for r in g_rows
            ]

        else:
            # Lightweight response for lists
            artist_data["top_tracks"] = []
            artist_data["singles"] = []
            artist_data["similar_artists"] = []
            artist_data["genres"] = []

        artists.append(artist_data)

    return artists


@router.get("/api/albums")
async def get_albums(
    artist: str = None,
    artist_mbid: str = None,
    album_mbid: str = None,
    db: asyncpg.Connection = Depends(get_db),
):
    # 1. If artist is provided, find their MBID to classify 'main' vs 'appears_on'
    # Resolve Artist Name to MBID if needed
    target_mbid = artist_mbid
    if artist and not target_mbid:
        # Try to resolve artist name to MBID via simple lookup
        rows = await db.fetch("SELECT mbid FROM artist WHERE name ILIKE $1 LIMIT 1", artist)
        if rows:
            target_mbid = rows[0]['mbid']

    # Unified Query rooted in artist_album
    query = """
        SELECT
            al.title as album,
            al.release_date,
            al.release_date as year, -- Alias for frontend compatibility
            al.release_type,
            al.description,
            al.peak_chart_position,
            aa.album_mbid as album_mbid,
            aa.album_mbid as mb_release_id,
            
            -- Dynamic Type Logic
            MAX(CASE 
                WHEN $1::text IS NOT NULL THEN
                    CASE WHEN aa.type = 'contributor' THEN 'appears_on' ELSE 'main' END
                ELSE 'main'
            END) as type,
            
            -- Track Aggregates (from track table)
            COUNT(t.id) as track_count,
            SUM(t.duration_seconds) as total_duration,
            MAX(CASE WHEN t.bit_depth > 16 OR t.sample_rate_hz > 44100 THEN 1 ELSE 0 END) as is_hires,
            MAX(t.label) as label,
            
            -- Display Artist Name (from track tags)
            COALESCE(MAX(t.album_artist), MAX(t.artist)) as artist_name,

            -- Multi-Artist Links (Subquery)
            (
                SELECT jsonb_agg(DISTINCT jsonb_build_object('name', a2.name, 'mbid', a2.mbid))
                FROM artist_album aa2
                JOIN artist a2 ON aa2.artist_mbid = a2.mbid
                WHERE aa2.album_mbid = aa.album_mbid AND aa2.type = 'primary'
            ) as artists,

            -- Art
            COALESCE(MAX(art.sha1), MAX(tart.sha1)) as art_sha1,

            -- Links
            COALESCE(
                jsonb_agg(DISTINCT jsonb_build_object('type', el.type, 'url', el.url)) FILTER (WHERE el.url IS NOT NULL),
                '[]'::jsonb
            ) as external_links,
            COALESCE(lp.listens, 0) as listens

        FROM artist_album aa
        JOIN album al ON aa.album_mbid = al.mbid
        LEFT JOIN track t ON t.release_mbid = aa.album_mbid
        LEFT JOIN artwork art ON al.artwork_id = art.id
        LEFT JOIN artwork tart ON t.artwork_id = tart.id
        LEFT JOIN external_link el ON el.entity_type = 'album' AND (el.entity_id = al.release_group_mbid OR el.entity_id = t.release_group_mbid)
        LEFT JOIN (
            SELECT t.release_mbid as album_mbid, COUNT(DISTINCT h.source_id) as listens
            FROM combined_playback_history h
            JOIN track t ON t.id = h.track_id
            GROUP BY t.release_mbid
        ) lp ON lp.album_mbid = aa.album_mbid

        WHERE 
            ($1::text IS NULL OR aa.artist_mbid = $1)
            AND ($2::text IS NULL OR aa.album_mbid = $2)

        GROUP BY aa.album_mbid, aa.type, al.mbid, lp.listens
        ORDER BY al.release_date DESC
    """
    
    # Execute
    rows = await db.fetch(query, target_mbid, album_mbid)
    
    results = []
    for row in rows:
        d = dict(row)
        # Ensure jsonb fields are handled if asyncpg returns string (usually returns loaded json for jsonb)
        if d.get("artists") and isinstance(d["artists"], str):
             import json
             try:
                 d["artists"] = json.loads(d["artists"])
             except Exception:
                 d["artists"] = []
                 
        if d.get("external_links") and isinstance(d["external_links"], str):
             import json
             try:
                 d["external_links"] = json.loads(d["external_links"])
             except Exception:
                 d["external_links"] = []
                 
        results.append(d)

    return results


@router.get("/api/tracks")
async def get_tracks(
    album: str = None,
    artist: str = None,
    album_mbid: str = None,
    db: asyncpg.Connection = Depends(get_db),
):
    # Base query
    # Use subquery to aggregate all artists for the track (Main + Feature)
    # This ensures "Taylor Swift, Ed Sheeran" is returned instead of just "Taylor Swift" tag
    query = """
        SELECT 
            t.id,
            t.path,
            t.title,
            t.artist,
            t.album,
            t.album_artist,
            t.track_no,
            t.disc_no,
            t.release_date,
            t.duration_seconds,
            t.codec,
            t.sample_rate_hz,
            t.bit_depth,
            t.bitrate,
            t.release_mbid,
            t.release_group_mbid,
            t.artwork_id,
            t.artist_mbid,
            t.album_artist_mbid,
            t.release_group_mbid as album_mbid,
            a.sha1 as art_sha1,
            COALESCE(tp.plays, 0) as plays,
            (SELECT STRING_AGG(a2.name, ', ' ORDER BY a2.name) 
             FROM track_artist ta2 
             JOIN artist a2 ON ta2.artist_mbid = a2.mbid 
             WHERE ta2.track_id = t.id) as aggregated_artists,
            (SELECT jsonb_agg(jsonb_build_object('name', a2.name, 'mbid', a2.mbid) ORDER BY a2.name) 
             FROM track_artist ta2 
             JOIN artist a2 ON ta2.artist_mbid = a2.mbid 
             WHERE ta2.track_id = t.id) as aggregated_artists_json
        FROM track t
        LEFT JOIN artwork a ON t.artwork_id = a.id
        LEFT JOIN (
            SELECT h.track_id, COUNT(*) as plays
            FROM combined_playback_history h
            GROUP BY h.track_id
        ) tp ON tp.track_id = t.id
    """
    params = []
    param_num = 1

    query += " WHERE 1=1"

    if album_mbid:
        query += f" AND (t.release_group_mbid = ${param_num} OR t.release_mbid = ${param_num + 1})"
        params.extend([album_mbid, album_mbid])
        param_num += 2
    if artist:
        # Simple artist filtering by tag or database link
        query += f""" AND (
            t.album_artist = ${param_num}
            OR t.artist = ${param_num + 1}
            OR EXISTS (
                SELECT 1 FROM track_artist ta 
                JOIN artist a ON ta.artist_mbid = a.mbid 
                WHERE ta.track_id = t.id AND a.name = ${param_num + 2}
            )
        )"""
        params.extend([artist, artist, artist])
        param_num += 3

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

        # Parse aggregated artists JSON
        if d.get("aggregated_artists_json"):
            import json
            val = d["aggregated_artists_json"]
            if isinstance(val, str):
                try:
                    d["artists"] = json.loads(val)
                except Exception:
                    d["artists"] = []
            else:
                d["artists"] = val
        else:
             # Fallback if no specific artists linked
             d["artists"] = [{"name": d["artist"]}] if d.get("artist") else []
        
        # Remove internal helper field
        d.pop("aggregated_artists_json", None)

        d.pop("artwork_id", None)

        # Frontend compatibility: MusicBrainz IDs
        if d.get("release_mbid"):
            d["mb_release_id"] = d["release_mbid"]
        if d.get("release_group_mbid"):
            d["mb_release_group_id"] = d["release_group_mbid"]

        # Convert binary SHA1 to hex
        if d.get("art_sha1"):
            d["art_sha1"] = sha1_to_hex(d["art_sha1"])

        # Convert binary quick_hash (BLAKE3) to hex for JSON serialization
        if d.get("quick_hash"):
            qh = d["quick_hash"]
            d["quick_hash"] = qh.hex() if isinstance(qh, (bytes, bytearray, memoryview)) else qh

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
            MIN(t.release_date) as year,
            COUNT(DISTINCT t.id) as track_count,
            SUM(t.duration_seconds) as total_duration,
            t.release_mbid,
            MAX(t.release_mbid) as mbid,
            MAX(t.release_mbid) as mb_release_id,
            MAX(t.release_group_mbid) as album_mbid,
            (SELECT mbid FROM artist WHERE name = COALESCE(MAX(t.album_artist), MAX(t.artist)) LIMIT 1) as artist_mbid,
            'main' as type
        FROM track t
        LEFT JOIN artwork a ON t.artwork_id = a.id
        WHERE t.album IS NOT NULL
        GROUP BY t.album, t.release_mbid
        ORDER BY year DESC, MAX(t.updated_at) DESC
        LIMIT $1
    """
    rows = await db.fetch(query, limit)
    results = []
    for row in rows:
        d = dict(row)
        d.pop("artwork_id", None)
        results.append(d)
    return results


@router.get("/api/home/recently-added-albums")
async def get_recently_added_albums(
    limit: int = 20, db: asyncpg.Connection = Depends(get_db)
):
    query = """
        SELECT 
            t.album, 
            MAX(t.artwork_id) as artwork_id, 
            MAX(a.sha1) as art_sha1,
            COALESCE(MAX(t.album_artist), MAX(t.artist)) as artist_name,
            MAX(CASE WHEN t.bit_depth > 16 OR t.sample_rate_hz > 44100 THEN 1 ELSE 0 END) as is_hires,
            MIN(t.release_date) as year,
            COUNT(DISTINCT t.id) as track_count,
            SUM(t.duration_seconds) as total_duration,
            t.release_mbid,
            MAX(t.release_mbid) as mbid,
            MAX(t.release_mbid) as mb_release_id,
            MAX(t.release_group_mbid) as album_mbid,
            (SELECT mbid FROM artist WHERE name = COALESCE(MAX(t.album_artist), MAX(t.artist)) LIMIT 1) as artist_mbid,
            'main' as type
        FROM track t
        LEFT JOIN artwork a ON t.artwork_id = a.id
        WHERE t.album IS NOT NULL
        GROUP BY t.album, t.release_mbid
        ORDER BY MAX(t.id) DESC
        LIMIT $1
    """
    rows = await db.fetch(query, limit)
    results = []
    for row in rows:
        d = dict(row)
        d.pop("artwork_id", None)
        results.append(d)
    return results


@router.get("/api/home/discover-artists")
async def get_discover_artists(
    limit: int = 20, db: asyncpg.Connection = Depends(get_db)
):
    # Newly added artists (based on track mtime)
    query = """
        SELECT DISTINCT 
            a.mbid,
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
            "mbid": row["mbid"],
            "name": row["name"],
            "image_url": row["image_url"],
            "art_sha1": sha1_to_hex(row["art_sha1"]),
            "bio": row["bio"],
        }
        for row in rows
    ]
