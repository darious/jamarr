"""Artist top tracks and similar artists from ListenBrainz (replaces Last.fm).

Both are looked up by artist MBID. Counts are ListenBrainz-wide listens: a
smaller audience than Last.fm's, so lesser-known artists can come back thin
or empty. An empty or failed lookup returns [], and the stage then keeps
whatever the artist already has. Top tracks need a ListenBrainz token (see
metadata_token).
"""

import logging
import re
import time
import unicodedata
from typing import Optional

from app import listenbrainz as lb
from app.config import get_listenbrainz_token
from app.scanner.stats import get_api_tracker

logger = logging.getLogger("scanner.services.listenbrainz")

TOP_TRACKS = 10
SIMILAR_ARTISTS = 10
TOKEN_CACHE_SECONDS = 300

# (fetched at, token); None until the first lookup. Not a 0.0 timestamp:
# time.monotonic() counts from boot, so shortly after a reboot 0.0 would
# look fresh and the token would never be fetched.
_token_cache: Optional[tuple[float, Optional[str]]] = None


async def metadata_token() -> Optional[str]:
    """Token for lookups: LISTENBRAINZ_TOKEN, else a connected user's (admins first).

    ListenBrainz requires one for top tracks since 2026-11-19.
    """
    global _token_cache
    configured = get_listenbrainz_token()
    if configured:
        return configured
    if _token_cache is not None:
        fetched_at, token = _token_cache
        if time.monotonic() - fetched_at < TOKEN_CACHE_SECONDS:
            return token
    token = None
    try:
        from app.db import db_conn

        async with db_conn() as db:
            token = await db.fetchval(
                """
                SELECT listenbrainz_token FROM "user"
                WHERE listenbrainz_token IS NOT NULL AND listenbrainz_auth_error IS NULL
                ORDER BY is_admin DESC, id LIMIT 1
                """
            )
    except Exception as exc:  # no pool (tests, odd CLI paths) or DB trouble
        logger.debug("No ListenBrainz token from the DB: %s", exc)
    _token_cache = (time.monotonic(), token)
    return token


def _title_key(title: str) -> str:
    """Fold versions of one song together ("Creep", "Creep (Remastered)")."""
    text = unicodedata.normalize("NFKC", title or "").casefold()
    text = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", text)
    text = re.sub(r"\s+-\s+.*$", "", text)
    return re.sub(r"[^\w]+", " ", text).strip()


async def fetch_top_tracks(artist_mbid: str, artist_name: str, client=None) -> list[dict]:
    """Up to 10 most-listened songs, one recording per song.

    Shape matches what the pipeline stores: name, mbid (recording), rank,
    playcount, popularity, album.
    """
    if not artist_mbid:
        return []
    try:
        get_api_tracker().increment("listenbrainz")
        recordings = await lb.get_client().top_recordings_for_artist(
            artist_mbid, token=await metadata_token()
        )
    except lb.ListenBrainzError as exc:
        logger.warning("[%s] ListenBrainz top tracks failed: %s", artist_name, exc)
        return []

    results: list[dict] = []
    seen: set[str] = set()
    for rec in recordings:
        name = (rec.get("recording_name") or "").strip()
        listens = rec.get("total_listen_count") or 0
        mbid = lb._valid_mbid(rec.get("recording_mbid"))
        key = _title_key(name)
        if not name or not mbid or listens <= 0 or not key or key in seen:
            continue
        seen.add(key)
        results.append(
            {
                "name": name,
                "mbid": mbid,
                "rank": len(results) + 1,
                "playcount": listens,
                "popularity": listens,
                "album": (rec.get("release_name") or "").strip() or None,
            }
        )
        if len(results) >= TOP_TRACKS:
            break
    return results


async def fetch_similar_artists(artist_mbid: str, artist_name: str, client=None) -> list[dict]:
    """Up to 10 similar artists, best first: name, mbid, match (0..1)."""
    if not artist_mbid:
        return []
    try:
        get_api_tracker().increment("listenbrainz")
        ranked = await lb.get_client().similar_artists(artist_mbid, token=await metadata_token())
    except lb.ListenBrainzError as exc:
        logger.info("[%s] ListenBrainz Labs similar artists failed (%s); trying lb-radio", artist_name, exc)
        return await _radio_similar_artists(artist_mbid, artist_name)

    results: list[dict] = []
    top_score: Optional[float] = None
    for row in ranked:
        mbid = lb._valid_mbid(row.get("artist_mbid"))
        name = (row.get("name") or "").strip()
        if not mbid or not name or mbid == artist_mbid:
            continue
        score = float(row.get("score") or 0)
        top_score = top_score or score or 1.0
        results.append({"name": name, "mbid": mbid, "match": round(score / top_score, 4)})
        if len(results) >= SIMILAR_ARTISTS:
            break
    if not results:
        return await _radio_similar_artists(artist_mbid, artist_name)
    return results


async def _radio_similar_artists(artist_mbid: str, artist_name: str) -> list[dict]:
    try:
        get_api_tracker().increment("listenbrainz")
        by_artist = await lb.get_client().radio_similar_artists(
            artist_mbid, SIMILAR_ARTISTS + 1, token=await metadata_token()
        )
    except lb.ListenBrainzError as exc:
        logger.warning("[%s] ListenBrainz similar artists failed: %s", artist_name, exc)
        return []
    results = []
    for mbid, recordings in by_artist.items():
        mbid = lb._valid_mbid(mbid)
        first = recordings[0] if isinstance(recordings, list) and recordings else {}
        name = (first.get("similar_artist_name") or "").strip() if isinstance(first, dict) else ""
        if not mbid or not name or mbid == artist_mbid:
            continue
        results.append({"name": name, "mbid": mbid, "match": None})
    return results[:SIMILAR_ARTISTS]
