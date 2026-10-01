import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, List

import asyncpg
from fastapi import APIRouter, Depends, Request, Response, Query
from pydantic import BaseModel, Field

from app.api.deps import get_current_user_jwt
from app.db import get_db
from app.api.library import sha1_to_hex
from app.security import get_client_ip
from app.services.player.history import play_threshold_seconds, scrobble_to_lastfm


router = APIRouter(dependencies=[Depends(get_current_user_jwt)])


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
    current_user: asyncpg.Record = Depends(get_current_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
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

    if scope == "mine":
        where_clauses.append(f"h.user_id = ${len(params_list) + 1}")
        params_list.append(current_user["id"])

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
    scope: str = "all",
    source: str = "all",
    artist_mbid: str | None = None,
    album_mbid: str | None = None,
    track_id: int | None = None,
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    current_user: asyncpg.Record = Depends(get_current_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

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
    if scope == "mine":
        where_clauses.append(f"h.user_id = ${len(params) + 1}")
        params.append(current_user["id"])
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

    # Define artist_join for other queries (albums/tracks)
    artist_join = "JOIN track_artist ta ON ta.track_id = t.id" if artist_mbid else ""
    artist_join_cond = "JOIN track_artist ta_filter ON ta_filter.track_id = t.id" if artist_mbid else ""
        
    artists_query = f"""
        SELECT 
            a.name as artist_name, 
            a.mbid as artist_mbid, 
            a.artwork_id, 
            ar.sha1 as art_sha1, 
            COUNT(*) as plays
        FROM combined_playback_history_mat h
        JOIN track t ON t.id = h.track_id
        JOIN track_artist ta ON ta.track_id = t.id
        JOIN artist a ON ta.artist_mbid = a.mbid
        LEFT JOIN artwork ar ON a.artwork_id = ar.id
        {artist_join_cond if 'ta.' not in locals().get('where_sql', '') else ''} 
        -- Note: where_sql might reference tables not in this join if we aren't careful.
        -- standard where_sql uses 'h', 't', 'ta' (if alias matches).
        -- original code used 'ta' for filter alias.
        -- I'll ensure filter alias compatibility below.
        WHERE {where_sql}
        GROUP BY a.name, a.mbid, a.artwork_id, ar.sha1
        ORDER BY plays DESC
        LIMIT 10
    """
        
    artists_query = f"""
        SELECT 
            a.name as artist_name, 
            a.mbid as artist_mbid,
            a.artwork_id, 
            w.sha1 as art_sha1,
            COUNT(*) as plays
        FROM combined_playback_history_mat h
        JOIN track t ON t.id = h.track_id
        JOIN track_artist ta ON ta.track_id = t.id
        JOIN artist a ON ta.artist_mbid = a.mbid
        LEFT JOIN artwork w ON a.artwork_id = w.id
        WHERE {where_sql}
        GROUP BY a.name, a.mbid, a.artwork_id, w.sha1
        ORDER BY plays DESC
        LIMIT 10
    """
    rows = await db.fetch(artists_query, *params)
    artists = [
        {
            "artist": row[0],
            "mbid": row[1], # Ensure frontend can handle this new field or mapped correctly
            "art_sha1": row[3],
            "plays": row[4],
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
              AND ph.timestamp < NOW() + INTERVAL '1 day'
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
              AND ph.timestamp < NOW() + INTERVAL '1 day'
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


# Last.fm refuses scrobbles timestamped more than 14 days ago.
LASTFM_MAX_SCROBBLE_AGE = timedelta(days=14)
# Slack for a phone clock running slightly ahead of the server's.
FUTURE_TOLERANCE = timedelta(minutes=5)


class OfflinePlay(BaseModel):
    track_id: int
    played_at: datetime = Field(description="When playback started; naive values are taken as UTC.")
    ms_played: int = Field(ge=0, description="How long the track actually played.")


class OfflinePlayBatch(BaseModel):
    client_id: str | None = None
    plays: List[OfflinePlay] = Field(max_length=1000)


class OfflinePlayResult(BaseModel):
    recorded: int = Field(description="New history rows written.")
    duplicates: int = Field(description="Already recorded by an earlier upload of the same play.")
    too_short: int = Field(description="Played for less than 30s or 20% of the track.")
    unknown_tracks: int = Field(description="Track no longer in the library.")
    invalid: int = Field(description="Timestamped in the future.")


@router.post(
    "/api/history/offline",
    response_model=OfflinePlayResult,
    summary="Record plays made while offline",
)
async def record_offline_plays(
    batch: OfflinePlayBatch,
    request: Request,
    current_user: asyncpg.Record = Depends(get_current_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
) -> OfflinePlayResult:
    """Upload plays the Android app logged with no server reachable.

    Each play is held to the same threshold as live playback (30s or 20% of
    the track, whichever is smaller) and recorded at the time it happened, not
    the time of upload. Uploading the same play twice is harmless: a play
    already on record for this user, track and start time is skipped, so a
    client can resend a batch whose response it never saw. Plays recent
    enough for Last.fm are scrobbled with their original timestamps.
    """
    user_id = current_user["id"]
    rows = await db.fetch(
        "SELECT id, duration_seconds FROM track WHERE id = ANY($1::bigint[])",
        list({play.track_id for play in batch.plays}),
    )
    durations = {row["id"]: row["duration_seconds"] for row in rows}
    client_ip = get_client_ip(request)
    now = datetime.now(timezone.utc)
    result = OfflinePlayResult(recorded=0, duplicates=0, too_short=0, unknown_tracks=0, invalid=0)
    to_scrobble: list[tuple[int, int]] = []

    for play in batch.plays:
        played_at = play.played_at
        if played_at.tzinfo is None:
            played_at = played_at.replace(tzinfo=timezone.utc)
        if played_at > now + FUTURE_TOLERANCE:
            result.invalid += 1
            continue
        if play.track_id not in durations:
            result.unknown_tracks += 1
            continue
        if play.ms_played / 1000 < play_threshold_seconds(durations[play.track_id]):
            result.too_short += 1
            continue
        inserted = await db.fetchval(
            """
            INSERT INTO playback_history (track_id, timestamp, client_ip, client_id, user_id)
            SELECT $1, $2, $3, $4, $5
            WHERE NOT EXISTS (
                SELECT 1 FROM playback_history
                WHERE track_id = $1 AND timestamp = $2 AND user_id = $5
            )
            RETURNING id
            """,
            play.track_id,
            played_at,
            client_ip,
            batch.client_id,
            user_id,
        )
        if inserted is None:
            result.duplicates += 1
            continue
        result.recorded += 1
        if now - played_at <= LASTFM_MAX_SCROBBLE_AGE:
            to_scrobble.append((play.track_id, int(played_at.timestamp())))

    if result.recorded:
        await db.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY combined_playback_history_mat")
        for track_id, played_at_unix in to_scrobble:
            asyncio.create_task(scrobble_to_lastfm(user_id, track_id, played_at=played_at_unix))

    return result
