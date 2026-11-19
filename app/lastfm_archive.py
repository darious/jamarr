"""The stored Last.fm scrobbles, kept as a read-only history archive.

Last.fm's API needs a paid subscription from 2026-12-01, so Jamarr no longer
talks to it: scrobbling and the scrobble sync moved to ListenBrainz. The
scrobbles already fetched stay in ``lastfm_scrobble`` and keep showing in
history up to each user's ListenBrainz cutover. They still need matching to
library tracks as the library changes, which this module does:

- ``match_archive`` matches unmatched scrobbles (the daily ListenBrainz job
  runs it), or all of them with ``rematch_all`` (after a matcher change).
- ``python -m app.lastfm_archive --user NAME [--all]`` does the same by hand.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Callable, Optional, Sequence

import asyncpg

from app.matching.matcher import match_and_store

logger = logging.getLogger(__name__)

FUZZY_TITLE_THRESHOLD = 92

_SCROBBLE_COLUMNS = """
    s.id, s.lastfm_username, s.track_mbid, s.track_name, s.album_mbid, s.album_name,
    s.artist_mbid, s.artist_name
"""


async def match_archive(
    db: asyncpg.Connection,
    lastfm_username: str,
    *,
    rematch_all: bool = False,
    log: Optional[Callable[[str], None]] = None,
    fuzzy: bool = True,
    fuzzy_title_threshold: int = FUZZY_TITLE_THRESHOLD,
) -> tuple[int, int]:
    """Match a user's stored scrobbles to the library. Returns (matched, unmatched)."""
    if rematch_all:
        await db.execute(
            """
            DELETE FROM lastfm_scrobble_match
            WHERE scrobble_id IN (SELECT id FROM lastfm_scrobble WHERE lastfm_username = $1)
            """,
            lastfm_username,
        )
        scrobbles = await db.fetch(
            f"""
            SELECT {_SCROBBLE_COLUMNS} FROM lastfm_scrobble s
            WHERE s.lastfm_username = $1
            ORDER BY s.played_at DESC, s.id DESC
            """,
            lastfm_username,
        )
    else:
        scrobbles = await db.fetch(
            f"""
            SELECT {_SCROBBLE_COLUMNS} FROM lastfm_scrobble s
            LEFT JOIN lastfm_scrobble_match m ON m.scrobble_id = s.id
            WHERE s.lastfm_username = $1 AND m.scrobble_id IS NULL
            ORDER BY s.played_at DESC, s.id DESC
            """,
            lastfm_username,
        )
    if not scrobbles:
        return 0, 0
    if log:
        log(f"Matching {len(scrobbles)} stored Last.fm scrobbles")
    return await match_and_store(
        db, scrobbles, fuzzy=fuzzy, fuzzy_title_threshold=fuzzy_title_threshold, log=log
    )


async def match_all_archives(db: asyncpg.Connection) -> tuple[int, int]:
    """Daily upkeep: match every user's unmatched stored scrobbles."""
    matched = unmatched = 0
    usernames = [
        r["lastfm_username"]
        for r in await db.fetch(
            'SELECT DISTINCT lastfm_username FROM "user" WHERE lastfm_username IS NOT NULL'
        )
    ]
    for username in usernames:
        m, u = await match_archive(db, username)
        matched += m
        unmatched += u
    return matched, unmatched


async def _main(argv: Optional[Sequence[str]] = None) -> int:
    from app.db import DB_HOST, DB_NAME, DB_PASS, DB_PORT, DB_USER
    from app.history_events import refresh_history

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", required=True, help="Jamarr username")
    parser.add_argument("--all", action="store_true", help="drop every match and rematch from scratch")
    args = parser.parse_args(argv)

    db = await asyncpg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, database=DB_NAME
    )
    try:
        user = await db.fetchrow(
            'SELECT id, lastfm_username FROM "user" WHERE username = $1', args.user
        )
        if user is None or not user["lastfm_username"]:
            print(f"No Last.fm archive for {args.user!r}")
            return 2
        matched, unmatched = await match_archive(
            db, user["lastfm_username"], rematch_all=args.all, log=print
        )
        await refresh_history(db, user["id"])
        print(f"Matched {matched}, unmatched {unmatched}")
        return 0
    finally:
        await db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(asyncio.run(_main()))
