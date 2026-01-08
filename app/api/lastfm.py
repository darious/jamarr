"""
Last.fm API endpoints for authentication and account management.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel

from app.auth import require_current_user
from app.db import get_db
from app import lastfm
from app.lastfm_sync_manager import LastfmSyncManager

logger = logging.getLogger(__name__)

router = APIRouter()


class ToggleRequest(BaseModel):
    enabled: bool


@router.get("/api/lastfm/status")
async def get_lastfm_status(
    request: Request,
    db: asyncpg.Connection = Depends(get_db),
):
    """Get Last.fm connection status for current user."""
    user, _ = await require_current_user(request, db)
    
    return {
        "connected": bool(user.get("lastfm_session_key")),
        "username": user.get("lastfm_username"),
        "enabled": bool(user.get("lastfm_enabled", False)),
        "connected_at": user.get("lastfm_connected_at").isoformat() if user.get("lastfm_connected_at") else None,
    }


@router.get("/api/lastfm/auth/start")
async def start_lastfm_auth(
    request: Request,
    db: asyncpg.Connection = Depends(get_db),
):
    """Initiate Last.fm authentication flow."""
    # Verify user is logged in
    await require_current_user(request, db)
    
    try:
        auth_url = lastfm.get_auth_url()
        return {"auth_url": auth_url}
    except Exception as e:
        logger.info(f"Generated Last.fm auth URL: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate Last.fm authentication"
        )


@router.get("/api/lastfm/callback")
async def lastfm_callback(
    token: str,
    request: Request,
    db: asyncpg.Connection = Depends(get_db),
):
    """Handle Last.fm OAuth callback."""
    logger.info(f"Last.fm callback received with token: {token[:10]}...")
    
    try:
        user, _ = await require_current_user(request, db)
        logger.info(f"User authenticated: {user['username']}")
    except Exception as e:
        logger.error(f"Authentication failed in callback: {e}")
        return RedirectResponse(
            url="/settings/user?lastfm=auth_error",
            status_code=status.HTTP_302_FOUND
        )
    
    try:
        logger.info("Exchanging token for session key...")
        # Exchange token for session key
        session_key, username = await lastfm.get_session_key(token)
        logger.info(f"Got session key for Last.fm user: {username}")
        
        # Store session key in database and enable scrobbling by default
        await db.execute(
            """
            UPDATE "user"
            SET lastfm_session_key = $1,
                lastfm_username = $2,
                lastfm_enabled = TRUE,
                lastfm_connected_at = $3
            WHERE id = $4
            """,
            session_key,
            username,
            datetime.now(timezone.utc),
            user["id"]
        )
        
        logger.info(f"User {user['username']} connected Last.fm account: {username}")
        
        # Redirect to settings page with success message
        return RedirectResponse(
            url="/settings/user?lastfm=connected",
            status_code=status.HTTP_302_FOUND
        )
        
    except Exception as e:
        logger.error(f"Failed to complete Last.fm authentication: {e}", exc_info=True)
        # Redirect to settings with error
        return RedirectResponse(
            url="/settings/user?lastfm=error",
            status_code=status.HTTP_302_FOUND
        )


@router.post("/api/lastfm/disconnect")
async def disconnect_lastfm(
    request: Request,
    db: asyncpg.Connection = Depends(get_db),
):
    """Disconnect Last.fm account."""
    user, _ = await require_current_user(request, db)
    
    await db.execute(
        """
        UPDATE "user"
        SET lastfm_session_key = NULL,
            lastfm_username = NULL,
            lastfm_enabled = FALSE,
            lastfm_connected_at = NULL
        WHERE id = $1
        """,
        user["id"]
    )
    
    logger.info(f"User {user['username']} disconnected Last.fm account")
    
    return {"ok": True}


@router.post("/api/lastfm/toggle")
async def toggle_lastfm(
    payload: ToggleRequest,
    request: Request,
    db: asyncpg.Connection = Depends(get_db),
):
    """Enable or disable Last.fm scrobbling."""
    user, _ = await require_current_user(request, db)
    
    # Verify user has connected Last.fm
    if not user.get("lastfm_session_key"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Last.fm account not connected"
        )
    
    await db.execute(
        'UPDATE "user" SET lastfm_enabled = $1 WHERE id = $2',
        payload.enabled,
        user["id"]
    )
    
    logger.info(f"User {user['username']} {'enabled' if payload.enabled else 'disabled'} Last.fm scrobbling")
    
    return {"ok": True, "enabled": payload.enabled}


class SyncRequest(BaseModel):
    fetch_new: bool = True
    rematch_all: bool = False
    limit: Optional[int] = None
    fuzzy: bool = True
    fuzzy_title_threshold: int = 92


def _retry_delay(
    attempt: int,
    backoff_base: float,
    backoff_max: float,
    retry_after: Optional[str] = None,
) -> float:
    if retry_after:
        try:
            return min(backoff_max, float(retry_after))
        except ValueError:
            pass
    return min(backoff_max, backoff_base * (2**attempt))


async def _fetch_lastfm_page(
    client: "httpx.AsyncClient",
    api_key: str,
    username: str,
    page: int,
    limit: int,
    from_timestamp: Optional[int],
    max_retries: int,
    backoff_base: float,
    backoff_max: float,
) -> dict:
    url = "https://ws.audioscrobbler.com/2.0/"
    params = {
        "method": "user.getrecenttracks",
        "user": username,
        "api_key": api_key,
        "format": "json",
        "limit": str(limit),
        "page": str(page),
        "extended": "1",
    }
    if from_timestamp:
        params["from"] = str(from_timestamp)
    for attempt in range(max_retries + 1):
        try:
            response = await client.get(url, params=params)
            if response.status_code == 429:
                delay = _retry_delay(
                    attempt,
                    backoff_base,
                    backoff_max,
                    response.headers.get("Retry-After"),
                )
                logger.warning("Last.fm rate limit (HTTP 429). Sleeping %.1fs", delay)
                await asyncio.sleep(delay)
                continue
            response.raise_for_status()
            data = response.json()
            if data.get("error"):
                error_code = str(data.get("error"))
                if error_code == "29":
                    delay = _retry_delay(attempt, backoff_base, backoff_max, None)
                    logger.warning(
                        "Last.fm rate limit (API error 29). Sleeping %.1fs", delay
                    )
                    await asyncio.sleep(delay)
                    continue
                raise RuntimeError(
                    f"Last.fm API error {data.get('error')}: {data.get('message')}"
                )
            return data
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status not in (500, 502, 503, 504):
                raise
            delay = _retry_delay(
                attempt,
                backoff_base,
                backoff_max,
                exc.response.headers.get("Retry-After"),
            )
            logger.warning("Last.fm HTTP %s. Sleeping %.1fs", status, delay)
            await asyncio.sleep(delay)
        except httpx.RequestError as exc:
            delay = _retry_delay(attempt, backoff_base, backoff_max, None)
            logger.warning("Last.fm network error: %s. Sleeping %.1fs", exc, delay)
            await asyncio.sleep(delay)
    raise RuntimeError("Exceeded max retries while fetching Last.fm data.")


@router.post("/api/lastfm/sync")
async def sync_scrobbles(
    payload: SyncRequest,
    request: Request,
    db: asyncpg.Connection = Depends(get_db),
):
    """Fetch new scrobbles from Last.fm and match them to library tracks."""
    import os
    from app.matching.matcher import (
        preload_artist_lookup,
        preload_skip_artists,
        preload_tracks,
        match_scrobble,
        _build_artist_volume,
    )
    from app.matching import build_cache_key
    
    user, _ = await require_current_user(request, db)
    manager = LastfmSyncManager.get_instance()
    manager.start_sync()
    
    # Verify user has Last.fm username configured
    lastfm_username = user.get("lastfm_username")
    if not lastfm_username:
        logger.warning(f"User {user.get('username')} attempted sync without Last.fm username configured")
        manager.complete_sync("error", "Last.fm account not connected")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Last.fm account not connected. Please connect your Last.fm account in settings."
        )
    
    logger.info(
        "Starting Last.fm sync for user %s (fetch_new=%s, rematch_all=%s, limit=%s)",
        lastfm_username,
        payload.fetch_new,
        payload.rematch_all,
        payload.limit,
    )
    
    logs: List[str] = []
    def add_log(message: str) -> None:
        logs.append(message)
        manager.log_message(message)
    fetched = 0
    matched = 0
    skipped = 0
    unmatched = 0
    
    # Fetch new scrobbles if requested
    if payload.fetch_new:
        add_log("Fetching new scrobbles from Last.fm...")
        logger.info(f"Fetching new scrobbles for {lastfm_username}")
        
        api_key = os.environ.get("LASTFM_API_KEY")
        if not api_key:
            logger.error("LASTFM_API_KEY not configured in environment")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="LASTFM_API_KEY not configured"
            )
        
        # Get newest scrobble timestamp to fetch only newer ones
        newest_uts = await db.fetchval(
            """
            SELECT MAX(played_at_uts) FROM lastfm_scrobble
            WHERE lastfm_username = $1
            """,
            lastfm_username
        )
        
        # Fetch scrobbles from Last.fm API
        page = 1
        total_pages: Optional[int] = None
        sleep_between_pages = 0.2
        max_retries = 6
        backoff_base = 1.0
        backoff_max = 30.0
        from_timestamp = newest_uts + 1 if newest_uts else None

        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                try:
                    data = await _fetch_lastfm_page(
                        client,
                        api_key,
                        lastfm_username,
                        page,
                        200,
                        from_timestamp,
                        max_retries,
                        backoff_base,
                        backoff_max,
                    )

                    recent = data.get("recenttracks", {})
                    tracks = recent.get("track", [])
                    if isinstance(tracks, dict):
                        tracks = [tracks]

                    # Parse scrobbles
                    scrobbles_to_insert = []
                    for track in tracks:
                        if not isinstance(track, dict):
                            continue

                        date = track.get("date")
                        if not isinstance(date, dict) or "uts" not in date:
                            continue

                        played_at_uts = int(date["uts"])

                        # Skip if older than newest we have
                        if newest_uts and played_at_uts <= newest_uts:
                            continue

                        # Parse artist
                        artist = track.get("artist", {})
                        if isinstance(artist, dict):
                            artist_name = artist.get("name") or artist.get("#text")
                            artist_mbid = artist.get("mbid")
                        else:
                            artist_name = str(artist) if artist else None
                            artist_mbid = None

                        # Parse album
                        album = track.get("album", {})
                        if isinstance(album, dict):
                            album_mbid = album.get("mbid")
                            album_name = album.get("#text")
                        else:
                            album_mbid = None
                            album_name = str(album) if album else None

                        if not artist_name or not track.get("name"):
                            continue

                        scrobbles_to_insert.append(
                            (
                                lastfm_username,
                                played_at_uts,
                                track.get("mbid"),
                                track.get("name"),
                                track.get("url"),
                                artist_mbid,
                                artist_name,
                                artist.get("url") if isinstance(artist, dict) else None,
                                album_mbid,
                                album_name,
                            )
                        )

                    # Insert scrobbles
                    if scrobbles_to_insert:
                        await db.executemany(
                            """
                            INSERT INTO lastfm_scrobble (
                                lastfm_username, played_at, played_at_uts,
                                track_mbid, track_name, track_url,
                                artist_mbid, artist_name, artist_url,
                                album_mbid, album_name
                            )
                            VALUES (
                                $1, to_timestamp($2), $2,
                                $3, $4, $5,
                                $6, $7, $8,
                                $9, $10
                            )
                            ON CONFLICT DO NOTHING
                            """,
                            scrobbles_to_insert,
                        )
                        fetched += len(scrobbles_to_insert)
                        log_msg = f"Fetched page {page}: {len(scrobbles_to_insert)} new scrobbles"
                        add_log(log_msg)
                        logger.debug(log_msg)

                    if total_pages is None:
                        attrs = recent.get("@attr") or {}
                        try:
                            total_pages = int(attrs.get("totalPages") or 0)
                        except (TypeError, ValueError):
                            total_pages = 0

                    if not total_pages or page >= total_pages:
                        break
                    page += 1
                    if sleep_between_pages > 0:
                        await asyncio.sleep(sleep_between_pages)
                except Exception as e:
                    error_msg = f"Error fetching page {page}: {str(e)}"
                    add_log(error_msg)
                    logger.error(error_msg, exc_info=True)
                    break
        
        log_msg = f"Fetched {fetched} new scrobbles"
        add_log(log_msg)
        logger.info(log_msg)
    
    # Match scrobbles
    log_msg = "Matching scrobbles to library tracks..."
    add_log(log_msg)
    logger.info(log_msg)
    
    # Get unmatched scrobbles
    limit_clause = ""
    limit_params: List[Any] = []
    if payload.limit is not None:
        limit_clause = "LIMIT $2"
        limit_params.append(payload.limit)

    if payload.rematch_all:
        # Clear all matches and re-match
        await db.execute(
            "DELETE FROM lastfm_scrobble_match WHERE scrobble_id IN (SELECT id FROM lastfm_scrobble WHERE lastfm_username = $1)",
            user["lastfm_username"]
        )
        scrobbles = await db.fetch(
            f"""
            SELECT id, lastfm_username, track_mbid, track_name, album_mbid, album_name,
                   artist_mbid, artist_name
            FROM lastfm_scrobble
            WHERE lastfm_username = $1
            ORDER BY played_at DESC
            {limit_clause}
            """,
            user["lastfm_username"],
            *limit_params,
        )
    else:
        # Only match unmatched scrobbles
        scrobbles = await db.fetch(
            f"""
            SELECT s.id, s.lastfm_username, s.track_mbid, s.track_name, s.album_mbid, s.album_name,
                   s.artist_mbid, s.artist_name
            FROM lastfm_scrobble s
            LEFT JOIN lastfm_scrobble_match m ON m.scrobble_id = s.id
            WHERE s.lastfm_username = $1
              AND m.scrobble_id IS NULL
            ORDER BY s.played_at DESC
            {limit_clause}
            """,
            user["lastfm_username"],
            *limit_params,
        )
    
    if not scrobbles:
        add_log("No scrobbles to match")
        manager.complete_sync("success")
        return {
            "fetched": fetched,
            "matched": matched,
            "skipped": skipped,
            "unmatched": unmatched,
            "logs": logs,
        }
    
    log_msg = f"Found {len(scrobbles)} scrobbles to match"
    add_log(log_msg)
    logger.info(log_msg)
    
    # Preload data
    artist_lookup = await preload_artist_lookup(db)
    skip_artists = await preload_skip_artists(db)
    
    # Process in batches
    BATCH_SIZE = 1000
    for i in range(0, len(scrobbles), BATCH_SIZE):
        batch = scrobbles[i:i + BATCH_SIZE]
        log_msg = f"Processing batch {i // BATCH_SIZE + 1} ({len(batch)} scrobbles)..."
        add_log(log_msg)
        logger.debug(log_msg)
        
        # Preload tracks for this batch
        indexes = await preload_tracks(db, batch, artist_lookup)
        artist_volume = _build_artist_volume(batch)
        
        # Check cache for existing matches
        cache_keys = [build_cache_key(s) for s in batch]
        cache_keys = [k for k in cache_keys if k]
        cached_matches = {}
        if cache_keys:
            cache_rows = await db.fetch(
                """
                SELECT cache_key, track_id, match_score, match_method, match_reason
                FROM lastfm_scrobble_match
                WHERE cache_key = ANY($1::text[])
                ORDER BY matched_at DESC
                """,
                cache_keys,
            )
            # Use most recent match for each cache key
            for row in cache_rows:
                if row["cache_key"] not in cached_matches:
                    cached_matches[row["cache_key"]] = row
        
        # Match each scrobble
        match_rows = []
        for scrobble in batch:
            cache_key = build_cache_key(scrobble)
            
            # Check cache first
            if cache_key and cache_key in cached_matches:
                cached = cached_matches[cache_key]
                match_rows.append((
                    scrobble["id"],
                    cached["track_id"],
                    cached["match_score"],
                    cached["match_method"],
                    cached["match_reason"],
                    cache_key,
                ))
                matched += 1
                continue
            
            # Try to match
            result = match_scrobble(
                scrobble,
                indexes,
                artist_lookup,
                artist_volume,
                skip_artists,
                fuzzy=payload.fuzzy,
                fuzzy_title_threshold=payload.fuzzy_title_threshold,
            )
            
            if result:
                track_id, score, method, reason = result
                match_rows.append((
                    scrobble["id"],
                    track_id,
                    score,
                    method,
                    reason,
                    cache_key,
                ))
                matched += 1
            else:
                unmatched += 1
        
        # Insert matches
        if match_rows:
            await db.executemany(
                """
                INSERT INTO lastfm_scrobble_match (scrobble_id, track_id, match_score, match_method, match_reason, cache_key)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (scrobble_id) DO UPDATE SET
                    track_id = EXCLUDED.track_id,
                    match_score = EXCLUDED.match_score,
                    match_method = EXCLUDED.match_method,
                    match_reason = EXCLUDED.match_reason,
                    cache_key = EXCLUDED.cache_key,
                    matched_at = NOW()
                """,
                match_rows,
            )
    
    log_msg = f"Matching complete: {matched} matched, {unmatched} unmatched"
    add_log(log_msg)
    logger.info(log_msg)

    manager.complete_sync("success")
    
    return {
        "fetched": fetched,
        "matched": matched,
        "skipped": skipped,
        "unmatched": unmatched,
        "logs": logs,
    }


@router.get("/api/lastfm/events")
async def lastfm_events():
    manager = LastfmSyncManager.get_instance()

    async def event_generator():
        yield ": connected\n\n"
        async for event in manager.subscribe():
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
