"""Read listens back from ListenBrainz into Jamarr's history.

Replaces the Last.fm scrobble sync. Only listens from the user's cutover
(``user.listenbrainz_cutover``) on are read: everything before it is the Last.fm
history Jamarr already holds (and has sent to ListenBrainz with
``app.listenbrainz_import``). Listens Jamarr itself submitted are skipped,
because they are already local plays.

Each sync reads backwards from the newest listen until it reaches how far the
last sync read (``listenbrainz_synced_through``, Jamarr's own listens
included), minus a lookback window, so a scrobbler that uploads late (a phone
coming back online) is still picked up. Pages are stored as they arrive, so an
interrupted catch-up keeps its progress.

Matching uses only MBIDs the scrobbler submitted. ListenBrainz's own mapping
names a canonical release, not the edition played, so feeding it to the
matcher would let one edition's match leak onto another (issue #366); it is
stored in ``mapped_recording_mbid`` for reference only.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

from app import listenbrainz as lb
from app.db import db_conn
from app.history_events import refresh_history
from app.matching.matcher import LISTENBRAINZ_TARGET, match_and_store

logger = logging.getLogger(__name__)

PAGE_SIZE = 1000
MAX_PAGES = 500
LOOKBACK = timedelta(days=14)

_sync_lock = asyncio.Lock()

INSERT_SQL = """
    INSERT INTO listenbrainz_listen (
        user_id, listened_at, listened_at_uts, recording_msid, artist_name,
        track_name, release_name, recording_mbid, release_mbid, artist_mbids,
        mapped_recording_mbid, submission_client
    )
    VALUES ($1, to_timestamp($2), $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
    ON CONFLICT (user_id, listened_at_uts, artist_name, track_name) DO NOTHING
"""

# Aliased to the field names the matcher reads.
UNMATCHED_SQL = """
    SELECT l.id,
           l.recording_mbid AS track_mbid,
           l.track_name,
           l.release_mbid AS album_mbid,
           l.release_name AS album_name,
           l.artist_mbids[1] AS artist_mbid,
           l.artist_name
    FROM listenbrainz_listen l
    LEFT JOIN listenbrainz_listen_match m ON m.listen_id = l.id
    WHERE l.user_id = $1 AND m.id IS NULL
    ORDER BY l.listened_at DESC, l.id DESC
"""


def parse_listen(listen: dict) -> Optional[dict]:
    """Normalise one ListenBrainz listen, or None if it lacks what we need."""
    listened_at = listen.get("listened_at")
    md = listen.get("track_metadata") or {}
    artist = (md.get("artist_name") or "").strip()
    track = (md.get("track_name") or "").strip()
    if not isinstance(listened_at, int) or not artist or not track:
        return None
    info = md.get("additional_info") or {}
    mapping = md.get("mbid_mapping") or {}
    # Only what the scrobbler submitted feeds the matcher (see module doc).
    artist_mbids = _mbid_list(info.get("artist_mbids"))
    return {
        "listened_at_uts": listened_at,
        "recording_msid": listen.get("recording_msid") or info.get("recording_msid"),
        "artist_name": artist,
        "track_name": track,
        "release_name": (md.get("release_name") or "").strip() or None,
        "recording_mbid": lb._valid_mbid(info.get("recording_mbid")),
        "release_mbid": lb._valid_mbid(info.get("release_mbid")),
        "artist_mbids": artist_mbids or None,
        "mapped_recording_mbid": lb._valid_mbid(mapping.get("recording_mbid")),
        "submission_client": info.get("submission_client"),
    }


def _mbid_list(value: Any) -> list[str]:
    """artist_mbids as a list, or a string some scrobblers send instead."""
    if isinstance(value, str):
        return lb._mbid_list(value)
    if isinstance(value, list):
        return [m for m in (lb._valid_mbid(v) for v in value) if m]
    return []


async def fetch_listens_since(
    client: lb.ListenBrainzClient,
    username: str,
    lower_uts: int,
    token: Optional[str] = None,
    on_page: Optional[Callable[[list[dict]], Awaitable[None]]] = None,
) -> list[dict]:
    """Every listen at or after ``lower_uts``, newest first, paging backwards.

    ``on_page`` gets each page's in-range listens as it arrives. Paging ends
    on an empty page or one reaching below ``lower_uts``; a short page is not
    taken as the end, since ListenBrainz does not promise full pages.
    """
    collected: list[dict] = []
    seen: set[tuple] = set()
    max_ts: Optional[int] = None
    previous_oldest: Optional[int] = None
    for _ in range(MAX_PAGES):
        page = await client.get_listens(username, max_ts=max_ts, count=PAGE_SIZE, token=token)
        stamps = [item["listened_at"] for item in page if isinstance(item.get("listened_at"), int)]
        if not stamps:
            break
        in_range = []
        for item in page:
            if item.get("listened_at", 0) < lower_uts:
                continue
            md = item.get("track_metadata") or {}
            # The boundary second is fetched twice (max_ts = oldest + 1).
            key = (item.get("listened_at"), item.get("recording_msid"),
                   md.get("artist_name"), md.get("track_name"))
            if key in seen:
                continue
            seen.add(key)
            in_range.append(item)
        collected.extend(in_range)
        if on_page is not None and in_range:
            await on_page(in_range)
        oldest = min(stamps)
        if oldest < lower_uts or oldest == previous_oldest:
            break
        previous_oldest = oldest
        # max_ts is exclusive: +1 so listens sharing the boundary second are
        # not lost (the repeats are dropped on insert).
        max_ts = oldest + 1
    return collected


async def sync_user(user_id: int, client: Optional[lb.ListenBrainzClient] = None) -> dict[str, Any]:
    """Fetch, store and match new listens for one user."""
    client = client or lb.get_client()
    async with db_conn() as db:
        user = await db.fetchrow(
            """
            SELECT listenbrainz_username, listenbrainz_token, listenbrainz_cutover,
                   listenbrainz_auth_error, listenbrainz_synced_through
            FROM "user" WHERE id = $1
            """,
            user_id,
        )
        before = await db.fetchval(
            "SELECT COUNT(*) FROM listenbrainz_listen WHERE user_id = $1", user_id
        )
    if user is None or not user["listenbrainz_username"] or user["listenbrainz_cutover"] is None:
        return {"skipped": "ListenBrainz not connected"}

    cutover_uts = int(user["listenbrainz_cutover"].timestamp())
    through = user["listenbrainz_synced_through"]
    lower = cutover_uts if through is None else max(cutover_uts, int(through - LOOKBACK.total_seconds()))
    token = None if user["listenbrainz_auth_error"] else user["listenbrainz_token"]
    own_count = 0

    async def store(page: list[dict]) -> None:
        nonlocal own_count
        parsed = [p for p in (parse_listen(item) for item in page) if p is not None]
        others = [p for p in parsed if p["submission_client"] != lb.SUBMISSION_CLIENT]
        own_count += len(parsed) - len(others)
        newest = max(p["listened_at_uts"] for p in parsed) if parsed else None
        async with db_conn() as db:
            if others:
                await db.executemany(
                    INSERT_SQL,
                    [
                        (
                            user_id, p["listened_at_uts"], p["recording_msid"], p["artist_name"],
                            p["track_name"], p["release_name"], p["recording_mbid"],
                            p["release_mbid"], p["artist_mbids"], p["mapped_recording_mbid"],
                            p["submission_client"],
                        )
                        for p in others
                    ],
                )
            if newest is not None:
                await db.execute(
                    """
                    UPDATE "user" SET listenbrainz_synced_through =
                        GREATEST(COALESCE(listenbrainz_synced_through, 0), $1)
                    WHERE id = $2
                    """,
                    newest,
                    user_id,
                )

    listens = await fetch_listens_since(
        client, user["listenbrainz_username"], lower, token, on_page=store
    )

    async with db_conn() as db:
        after = await db.fetchval(
            "SELECT COUNT(*) FROM listenbrainz_listen WHERE user_id = $1", user_id
        )
        unmatched_rows = await db.fetch(UNMATCHED_SQL, user_id)
        matched, unmatched = (0, 0)
        if unmatched_rows:
            matched, unmatched = await match_and_store(
                db, unmatched_rows, target=LISTENBRAINZ_TARGET
            )
        await db.execute(
            'UPDATE "user" SET listenbrainz_synced_at = $1 WHERE id = $2',
            datetime.now(timezone.utc),
            user_id,
        )
        if after != before or matched:
            await refresh_history(db, user_id)

    stats = {
        "fetched": len(listens),
        "new": after - before,
        "own_skipped": own_count,
        "matched": matched,
        "unmatched": unmatched,
    }
    logger.info("ListenBrainz sync for user %s: %s", user_id, stats)
    return stats


async def sync_user_locked(user_id: int) -> dict[str, Any]:
    async with _sync_lock:
        return await sync_user(user_id)


async def sync_all_listenbrainz() -> int:
    """Scheduler job: sync every connected user. Returns how many were synced."""
    async with db_conn() as db:
        user_ids = [
            r["id"]
            for r in await db.fetch(
                """
                SELECT id FROM "user"
                WHERE listenbrainz_username IS NOT NULL AND listenbrainz_cutover IS NOT NULL
                ORDER BY id
                """
            )
        ]
    synced = 0
    async with _sync_lock:
        for user_id in user_ids:
            try:
                await sync_user(user_id)
                synced += 1
            except lb.ListenBrainzError as exc:
                logger.warning("ListenBrainz sync failed for user %s: %s", user_id, exc)
    return synced
