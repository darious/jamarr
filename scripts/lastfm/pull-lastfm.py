#!/usr/bin/env python
"""
Pull Last.fm scrobble history and store a minimal record set in the dev DB.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import asyncpg
import httpx
from rich.console import Console

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

console = Console()


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and value[0] in ("'", '"') and value[-1] == value[0]:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _normalize_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_artist(artist: Any) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if isinstance(artist, dict):
        name = artist.get("name") or artist.get("#text")
        return (
            _normalize_value(artist.get("url")),
            _normalize_value(name),
            _normalize_value(artist.get("mbid")),
        )
    if isinstance(artist, str):
        return None, _normalize_value(artist), None
    return None, None, None


def _parse_album(album: Any) -> Tuple[Optional[str], Optional[str]]:
    if isinstance(album, dict):
        return _normalize_value(album.get("mbid")), _normalize_value(album.get("#text"))
    if isinstance(album, str):
        return None, _normalize_value(album)
    return None, None


def _build_scrobble(track: Dict[str, Any], username: str) -> Optional[Dict[str, Any]]:
    date = track.get("date")
    if not isinstance(date, dict) or "uts" not in date:
        return None

    artist_url, artist_name, artist_mbid = _parse_artist(track.get("artist"))
    album_mbid, album_name = _parse_album(track.get("album"))

    return {
        "lastfm_username": username,
        "played_at_uts": int(date["uts"]),
        "track_mbid": _normalize_value(track.get("mbid")),
        "track_name": _normalize_value(track.get("name")),
        "track_url": _normalize_value(track.get("url")),
        "artist_url": artist_url,
        "artist_name": artist_name,
        "artist_mbid": artist_mbid,
        "album_mbid": album_mbid,
        "album_name": album_name,
    }


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


def fetch_page(
    client: httpx.Client,
    api_key: str,
    username: str,
    page: int,
    limit: int,
    to_timestamp: Optional[int],
    from_timestamp: Optional[int],
    max_retries: int,
    backoff_base: float,
    backoff_max: float,
) -> Dict[str, Any]:
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
    if to_timestamp:
        params["to"] = str(to_timestamp)
    if from_timestamp:
        params["from"] = str(from_timestamp)
    for attempt in range(max_retries + 1):
        try:
            resp = client.get(url, params=params)
            if resp.status_code == 429:
                delay = _retry_delay(
                    attempt,
                    backoff_base,
                    backoff_max,
                    resp.headers.get("Retry-After"),
                )
                print(f"Rate limited (HTTP 429). Sleeping {delay:.1f}s then retrying.")
                time.sleep(delay)
                continue
            resp.raise_for_status()
            data = resp.json()
            if data.get("error"):
                error_code = str(data.get("error"))
                if error_code == "29":
                    delay = _retry_delay(attempt, backoff_base, backoff_max, None)
                    print(
                        f"Rate limited (API error 29). Sleeping {delay:.1f}s then retrying."
                    )
                    time.sleep(delay)
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
            print(f"HTTP {status} from Last.fm. Sleeping {delay:.1f}s then retrying.")
            time.sleep(delay)
        except httpx.RequestError as exc:
            delay = _retry_delay(attempt, backoff_base, backoff_max, None)
            print(f"Network error: {exc}. Sleeping {delay:.1f}s then retrying.")
            time.sleep(delay)
    raise RuntimeError("Exceeded max retries while fetching Last.fm data.")


async def ensure_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lastfm_scrobble (
            id BIGSERIAL PRIMARY KEY,
            lastfm_username TEXT NOT NULL,
            played_at TIMESTAMPTZ NOT NULL,
            played_at_uts BIGINT,
            track_mbid TEXT,
            track_name TEXT NOT NULL,
            track_url TEXT,
            artist_mbid TEXT,
            artist_name TEXT NOT NULL,
            artist_url TEXT,
            album_mbid TEXT,
            album_name TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(lastfm_username, played_at, track_name, artist_name)
        );
        """
    )
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_lastfm_scrobble_user_played
        ON lastfm_scrobble(lastfm_username, played_at DESC);
        """
    )


async def get_oldest_scrobble_uts(
    conn: asyncpg.Connection, username: str
) -> Optional[int]:
    row = await conn.fetchrow(
        """
        SELECT MIN(played_at_uts) AS oldest
        FROM lastfm_scrobble
        WHERE lastfm_username = $1
        """,
        username,
    )
    if not row or row["oldest"] is None:
        return None
    return int(row["oldest"])


async def get_newest_scrobble_uts(
    conn: asyncpg.Connection, username: str
) -> Optional[int]:
    row = await conn.fetchrow(
        """
        SELECT MAX(played_at_uts) AS newest
        FROM lastfm_scrobble
        WHERE lastfm_username = $1
        """,
        username,
    )
    if not row or row["newest"] is None:
        return None
    return int(row["newest"])


async def insert_scrobbles(
    conn: asyncpg.Connection, scrobbles: Iterable[Dict[str, Any]]
) -> int:
    rows = [
        (
            row["lastfm_username"],
            row["played_at_uts"],
            row["track_mbid"],
            row["track_name"],
            row["track_url"],
            row["artist_mbid"],
            row["artist_name"],
            row["artist_url"],
            row["album_mbid"],
            row["album_name"],
        )
        for row in scrobbles
        if row.get("track_name") and row.get("artist_name")
    ]
    if not rows:
        return 0

    await conn.executemany(
        """
        INSERT INTO lastfm_scrobble (
            lastfm_username,
            played_at,
            played_at_uts,
            track_mbid,
            track_name,
            track_url,
            artist_mbid,
            artist_name,
            artist_url,
            album_mbid,
            album_name
        )
        VALUES (
            $1,
            to_timestamp($2),
            $2,
            $3,
            $4,
            $5,
            $6,
            $7,
            $8,
            $9,
            $10
        )
        ON CONFLICT DO NOTHING
        """,
        rows,
    )
    return len(rows)


async def run(args: argparse.Namespace) -> None:
    load_dotenv(ROOT / ".env")

    api_key = os.environ.get("LASTFM_API_KEY")
    if not api_key:
        raise RuntimeError("LASTFM_API_KEY is required (set in .env)")

    db_host = os.environ.get("DB_HOST", "127.0.0.1")
    db_port = int(os.environ.get("DB_PORT", "8110"))
    db_user = os.environ.get("DB_USER", "jamarr")
    db_pass = os.environ.get("DB_PASS", "jamarr")
    db_name = os.environ.get("DB_NAME", "jamarr")

    async with asyncpg.create_pool(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_pass,
        database=db_name,
        min_size=1,
        max_size=4,
    ) as pool:
        async with pool.acquire() as conn:
            await ensure_table(conn)

        limit = args.limit
        page = 1
        total_pages = None
        total_seen = 0
        total_inserted = 0
        dump_rows: List[Dict[str, Any]] = []
        oldest_uts: Optional[int] = None
        newest_uts: Optional[int] = None

        if args.older_than_db:
            async with pool.acquire() as conn:
                oldest_uts = await get_oldest_scrobble_uts(conn, args.user)
            if oldest_uts is None:
                print("No existing scrobbles found; fetching latest instead.")
        if args.newer_than_db:
            async with pool.acquire() as conn:
                newest_uts = await get_newest_scrobble_uts(conn, args.user)
            if newest_uts is None:
                print("No existing scrobbles found; fetching latest instead.")

        with httpx.Client(timeout=30.0) as client:
            while True:
                data = fetch_page(
                    client,
                    api_key,
                    args.user,
                    page,
                    limit,
                    oldest_uts - 1 if oldest_uts else None,
                    newest_uts + 1 if newest_uts else None,
                    args.max_retries,
                    args.backoff_base,
                    args.backoff_max,
                )
                recent = data.get("recenttracks", {})
                tracks = recent.get("track", [])
                if isinstance(tracks, dict):
                    tracks = [tracks]

                scrobbles: List[Dict[str, Any]] = []
                for track in tracks:
                    if not isinstance(track, dict):
                        continue
                    parsed = _build_scrobble(track, args.user)
                    if parsed:
                        if oldest_uts and parsed["played_at_uts"] >= oldest_uts:
                            continue
                        scrobbles.append(parsed)

                total_seen += len(scrobbles)
                if args.output:
                    dump_rows.extend(scrobbles)

                async with pool.acquire() as conn:
                    inserted = await insert_scrobbles(conn, scrobbles)
                total_inserted += inserted

                if total_pages is None:
                    attrs = recent.get("@attr") or {}
                    try:
                        total_pages = int(attrs.get("totalPages") or 0)
                    except (TypeError, ValueError):
                        total_pages = 0

                last_uts = None
                if scrobbles:
                    last_uts = min(row["played_at_uts"] for row in scrobbles)
                last_dt = None
                if last_uts:
                    last_dt = datetime.fromtimestamp(last_uts, tz=timezone.utc)
                last_label = last_dt.isoformat().replace("+00:00", "Z") if last_dt else "-"
                console.print(
                    f"[bold]Page {page}/{total_pages or '?'}[/bold]: "
                    f"[cyan]{len(scrobbles)}[/cyan] scrobbles, "
                    f"[green]{inserted}[/green] inserted, "
                    f"[magenta]{total_seen}[/magenta] total pulled, "
                    f"[blue]{last_label}[/blue] last scrobble"
                )

                if args.older_than_db and len(scrobbles) >= limit:
                    break
                if not total_pages or page >= total_pages:
                    break
                if args.max_pages and page >= args.max_pages:
                    break
                page += 1
                if args.sleep > 0:
                    time.sleep(args.sleep)

        print(f"Done. {total_seen} scrobbles processed, {total_inserted} inserted.")

        if args.output:
            output_path = Path(args.output)
            output_path.write_text(json.dumps(dump_rows, indent=2))
            print(f"Wrote JSON dump to {output_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pull Last.fm scrobble history and store in dev DB.",
    )
    parser.add_argument("--user", default="darious1472", help="Last.fm username")
    parser.add_argument("--limit", type=int, default=200, help="Tracks per page")
    parser.add_argument("--max-pages", type=int, default=0, help="Stop after N pages")
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.2,
        help="Delay between pages (seconds)",
    )
    parser.add_argument(
        "--output",
        help="Optional path to write scrobble list as JSON",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=6,
        help="Max retries per page on rate limits or transient errors",
    )
    parser.add_argument(
        "--backoff-base",
        type=float,
        default=1.0,
        help="Base seconds for exponential backoff",
    )
    parser.add_argument(
        "--backoff-max",
        type=float,
        default=30.0,
        help="Max seconds to wait between retries",
    )
    parser.add_argument(
        "--older-than-db",
        action="store_true",
        help="Only pull scrobbles older than the oldest in the DB",
    )
    parser.add_argument(
        "--newer-than-db",
        action="store_true",
        help="Only pull scrobbles newer than the newest in the DB",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("Interrupted.")


if __name__ == "__main__":
    main()
