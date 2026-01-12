from typing import Any, List

import asyncpg
from fastapi import APIRouter, Depends, Request, Response, Query

from app.auth import get_session_user
from app.db import get_db
from app.api.library import sha1_to_hex


router = APIRouter()


@router.get("/api/history/tracks")
async def get_playback_history(
    response: Response,
    scope: str = "all",
    source: str = "all",
    artist_mbid: str | None = None,
    album_mbid: str | None = None,
    track_id: int | None = None,
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    page: int = 1,
    limit: int = 20,
    request: Request = None,
):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    async for db in get_db():
        user_row, _ = (
            await get_session_user(db, request.cookies.get("jamarr_session"))
            if request
            else (None, None)
        )
        from datetime import date, timedelta

        today = date.today()
        default_from = today - timedelta(days=6)
        default_to = today

        try:
            from_date = date.fromisoformat(date_from) if date_from else default_from
        except ValueError:
            from_date = default_from
        try:
            to_date = date.fromisoformat(date_to) if date_to else default_to
        except ValueError:
            to_date = default_to

        where_clauses = [
            "h.played_at >= $1::date",
            "h.played_at < ($2::date + INTERVAL '1 day')",
        ]
        params_list = [from_date, to_date]

        if scope == "mine" and user_row:
            where_clauses.append(f"h.user_id = ${len(params_list) + 1}")
            params_list.append(user_row["id"])

        if source != "all":
            where_clauses.append(f"h.source = ${len(params_list) + 1}")
            params_list.append(source)

        if artist_mbid:
            where_clauses.append(f"ta.artist_mbid = ${len(params_list) + 1}")
            params_list.append(artist_mbid)

        if album_mbid:
            where_clauses.append(
                f"(t.release_mbid = ${len(params_list) + 1} OR t.release_group_mbid = ${len(params_list) + 1})"
            )
            params_list.append(album_mbid)

        if track_id:
            where_clauses.append(f"h.track_id = ${len(params_list) + 1}")
            params_list.append(track_id)

        where_sql = "WHERE " + " AND ".join(where_clauses)

        page = max(1, page)
        limit = max(1, min(limit, 100))
        offset = (page - 1) * limit

        params_list.append(limit)
        params_list.append(offset)

        limit_idx = len(params_list) - 1
        offset_idx = len(params_list)

        artist_join = "JOIN track_artist ta ON ta.track_id = t.id" if artist_mbid else ""
        query = f"""
            SELECT 
                h.source_id as id, h.played_at as timestamp, h.client_ip, h.client_id, h.user_id,
                t.id, t.title, t.artist, t.album, t.artwork_id, t.duration_seconds,
                t.codec, t.bit_depth, t.sample_rate_hz, t.release_date,
                t.release_mbid,
                u.username, u.display_name, u.email,
                a.sha1 as art_sha1
                , h.source
            FROM combined_playback_history_mat h
            JOIN track t ON h.track_id = t.id
            {artist_join}
            LEFT JOIN artwork a ON t.artwork_id = a.id
            LEFT JOIN "user" u ON u.id = h.user_id
            {where_sql}
            ORDER BY h.played_at DESC
            LIMIT ${limit_idx} OFFSET ${offset_idx}
        """
        rows = await db.fetch(query, *params_list)
        history = []
        for row in rows:
            history.append(
                {
                    "id": row[0],
                    "timestamp": row[1],
                    "client_ip": row[2],
                    "client_id": row[3],
                    "source": row[20],
                    "user": {
                        "id": row[4],
                        "username": row[15],
                        "display_name": row[16],
                        "email": row[17],
                    }
                    if row[4]
                    else None,
                    "track": {
                        "id": row[5],
                        "title": row[6],
                        "artist": row[7],
                        "album": row[8],
                        "art_sha1": row[19],
                        "duration_seconds": row[10],
                        "codec": row[11],
                        "bit_depth": row[12],
                        "sample_rate_hz": row[13],
                        "release_date": row[14],
                        "mb_release_id": row[15],
                    },
                }
            )
        return history
    return []


@router.get("/api/history/stats")
async def get_playback_history_stats(
    response: Response,
    request: Request,
    scope: str = "all",
    source: str = "all",
    artist_mbid: str | None = None,
    album_mbid: str | None = None,
    track_id: int | None = None,
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    async for db in get_db():
        user_row, _ = await get_session_user(db, request.cookies.get("jamarr_session"))
        from datetime import date, timedelta

        today = date.today()
        default_from = today - timedelta(days=6)
        default_to = today

        try:
            from_date = date.fromisoformat(date_from) if date_from else default_from
        except ValueError:
            from_date = default_from
        try:
            to_date = date.fromisoformat(date_to) if date_to else default_to
        except ValueError:
            to_date = default_to

        where_clauses = [
            "h.played_at >= $1::date",
            "h.played_at < ($2::date + INTERVAL '1 day')",
        ]
        params: List[Any] = [from_date, to_date]
        if scope == "mine" and user_row:
            where_clauses.append(f"h.user_id = ${len(params) + 1}")
            params.append(user_row["id"])
        if source != "all":
            where_clauses.append(f"h.source = ${len(params) + 1}")
            params.append(source)
        if artist_mbid:
            where_clauses.append(f"ta.artist_mbid = ${len(params) + 1}")
            params.append(artist_mbid)
        if album_mbid:
            where_clauses.append(
                f"(t.release_mbid = ${len(params) + 1} OR t.release_group_mbid = ${len(params) + 1})"
            )
            params.append(album_mbid)
        if track_id:
            where_clauses.append(f"h.track_id = ${len(params) + 1}")
            params.append(track_id)
        where_sql = " AND ".join(where_clauses)

        needs_track_join = bool(artist_mbid or album_mbid)
        daily_artist_join = ""
        if needs_track_join:
            daily_artist_join = "JOIN track t ON t.id = h.track_id"
            if artist_mbid:
                daily_artist_join += " JOIN track_artist ta ON ta.track_id = t.id"
        daily_query = f"""
            SELECT DATE(played_at) as day, COUNT(*) as plays
            FROM combined_playback_history_mat h
            {daily_artist_join}
            WHERE {where_sql}
            GROUP BY day
            ORDER BY day DESC
        """
        rows = await db.fetch(daily_query, *params)
        daily = [{"day": row[0], "plays": row[1]} for row in rows]

        artist_join = "JOIN track_artist ta ON ta.track_id = t.id" if artist_mbid else ""
        artists_query = f"""
            SELECT 
                COALESCE(NULLIF(t.album_artist, ''), t.artist) as artist_name, 
                MIN(t.artwork_id) as artwork_id, 
                MAX(a.sha1) as art_sha1, 
                COUNT(*) as plays
            FROM combined_playback_history_mat h
            JOIN track t ON t.id = h.track_id
            {artist_join}
            LEFT JOIN artwork a ON t.artwork_id = a.id
            WHERE {where_sql}
            GROUP BY COALESCE(NULLIF(t.album_artist, ''), t.artist)
            ORDER BY plays DESC
            LIMIT 10
        """
        rows = await db.fetch(artists_query, *params)
        artists = [
            {
                "artist": row[0],
                "art_sha1": row[2],
                "plays": row[3],
            }
            for row in rows
            if row[0]
        ]

        albums_query = f"""
            SELECT 
                t.album, 
                COALESCE(NULLIF(t.album_artist, ''), t.artist) as artist_name, 
                MIN(t.artwork_id) as artwork_id, 
                MAX(a.sha1) as art_sha1, 
                MAX(t.release_mbid) as mb_release_id,
                COUNT(*) as plays
            FROM combined_playback_history_mat h
            JOIN track t ON t.id = h.track_id
            {artist_join}
            LEFT JOIN artwork a ON t.artwork_id = a.id
            WHERE {where_sql}
            GROUP BY t.album, COALESCE(NULLIF(t.album_artist, ''), t.artist)
            ORDER BY plays DESC
            LIMIT 10
        """
        rows = await db.fetch(albums_query, *params)
        albums = [
            {
                "album": row[0],
                "artist": row[1],
                "art_sha1": row[3],
                "mb_release_id": row[4],
                "plays": row[5],
            }
            for row in rows
            if row[0]
        ]

        tracks_query = f"""
        SELECT t.id, t.title, t.artist, t.album, t.release_mbid, t.artwork_id, MAX(a.sha1) as art_sha1, COUNT(*) as plays
        FROM combined_playback_history_mat h
        JOIN track t ON t.id = h.track_id
        {artist_join}
        LEFT JOIN artwork a ON t.artwork_id = a.id
        WHERE {where_sql}
            GROUP BY t.id, t.title, t.artist, t.album, t.release_mbid, t.artwork_id
            ORDER BY plays DESC
            LIMIT 10
        """
        rows = await db.fetch(tracks_query, *params)
        tracks = [
            {
                "id": row[0],
                "title": row[1],
                "artist": row[2],
                "album": row[3],
                "mb_release_id": row[4],
                "art_sha1": row[6],
                "plays": row[7],
            }
            for row in rows
        ]

        return {
            "daily": daily,
            "artists": artists,
            "albums": albums,
            "tracks": tracks,
        }
    return {"daily": [], "artists": [], "albums": [], "tracks": []}


@router.get("/api/history/albums")
async def get_recently_played_albums(
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
            t.release_mbid as release_mbid,
            MAX(t.release_mbid) as mbid,
            MAX(t.release_mbid) as mb_release_id,
            MAX(t.release_group_mbid) as album_mbid,
            (SELECT mbid FROM artist WHERE name = COALESCE(MAX(t.album_artist), MAX(t.artist)) LIMIT 1) as artist_mbid,
            MAX(ph.timestamp) as last_played
        FROM playback_history ph
        JOIN track t ON ph.track_id = t.id
        LEFT JOIN artwork a ON t.artwork_id = a.id
        WHERE t.album IS NOT NULL
        GROUP BY t.album, t.release_mbid
        ORDER BY last_played DESC
        LIMIT $1
    """
    rows = await db.fetch(query, limit)
    results = []
    for row in rows:
        d = dict(row)
        d.pop("artwork_id", None)
        results.append(d)
    return results


@router.get("/api/history/artists")
async def get_recently_played_artists(
    limit: int = 20, db: asyncpg.Connection = Depends(get_db)
):
    query = """
        SELECT DISTINCT 
            a.mbid,
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
            "mbid": row["mbid"],
            "name": row["name"],
            "image_url": row["image_url"],
            "art_sha1": sha1_to_hex(row["art_sha1"]),
            "bio": row["bio"],
        }
        for row in rows
    ]
