#!/usr/bin/env python
"""
Match recent Last.fm scrobbles to library tracks using local data only.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import asyncpg
import math
from functools import lru_cache
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

console = Console()

BENIGN_SUFFIX_TOKENS = {
    "remaster",
    "remastered",
    "mono",
    "stereo",
    "edit",
    "radio",
    "vocal",
    "explicit",
    "clean",
    "bonus",
    "deluxe",
    "expanded",
    "anniversary",
    "reissue",
    "version",
    "single",
    "original",
    "acoustic",
    "live",
    "session",
    "sessions",
    "mix",
    "album",
    "remix",
}


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


@lru_cache(maxsize=200000)
def _normalize_basic(value: Optional[str]) -> str:
    if not value:
        return ""
    value = "".join(
        c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)
    )
    value = value.lower()
    value = value.replace("&", "and")
    value = value.replace("+", "and")
    value = value.replace("’", "'")
    value = value.replace(".", "")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


@lru_cache(maxsize=200000)
def _regex_normalize(value: Optional[str]) -> str:
    if not value:
        return ""
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _strip_leading_article(value: str) -> str:
    for article in ("the ", "a ", "an "):
        if value.startswith(article):
            return value[len(article) :].strip()
    return value


def _title_variants(normalized_title: str) -> List[str]:
    variants = {normalized_title}
    stripped = _strip_leading_article(normalized_title)
    if stripped:
        variants.add(stripped)
    return list(variants)


@lru_cache(maxsize=100000)
def split_artist_names(value: Optional[str]) -> List[str]:
    if not value:
        return []
    value = value.replace("&", "and").replace("feat.", "and").replace("featuring", "and")
    value = value.replace("ft.", "and").replace("/", "and")
    value = value.replace(" x ", " and ").replace(" vs ", " and ").replace(" with ", " and ")
    value = value.replace(" presents ", " and ").replace(" pres. ", " and ")
    value = value.replace("+", "and")
    parts = re.split(r"\s*(?:,| and )\s*", value, flags=re.IGNORECASE)
    return [normalize_artist(part) for part in parts if part.strip()]


@lru_cache(maxsize=100000)
def extract_featured_artists(title: Optional[str]) -> List[str]:
    if not title:
        return []
    segments: List[str] = []
    patterns = [
        r"\((?:feat\.?|featuring|ft\.?)\s*([^)]+)\)",
        r"\[(?:feat\.?|featuring|ft\.?)\s*([^\]]+)\]",
        r"\((?:with)\s*([^)]+)\)",
        r"\[(?:with)\s*([^\]]+)\]",
        r"(?:feat\.?|featuring|ft\.?)\s*([^–-]+)$",
        r"(?:with)\s*([^–-]+)$",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, title, flags=re.IGNORECASE):
            segments.append(match)
    artists: List[str] = []
    for segment in segments:
        artists.extend(split_artist_names(segment))
    return list(dict.fromkeys(artists))


@lru_cache(maxsize=100000)
def extract_featured_artist_raw_parts(title: Optional[str]) -> List[str]:
    if not title:
        return []
    segments: List[str] = []
    patterns = [
        r"\((?:feat\.?|featuring|ft\.?)\s*([^)]+)\)",
        r"\[(?:feat\.?|featuring|ft\.?)\s*([^\]]+)\]",
        r"\((?:with)\s*([^)]+)\)",
        r"\[(?:with)\s*([^\]]+)\]",
        r"(?:feat\.?|featuring|ft\.?)\s*([^–-]+)$",
        r"(?:with)\s*([^–-]+)$",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, title, flags=re.IGNORECASE):
            segments.append(match)
    raw_parts: List[str] = []
    for segment in segments:
        segment = (
            segment.replace("&", "and")
            .replace("feat.", "and")
            .replace("featuring", "and")
            .replace("ft.", "and")
            .replace("with", "and")
            .replace("/", "and")
            .replace("+", "and")
        )
        for part in re.split(r"\s*(?:,| and )\s*", segment, flags=re.IGNORECASE):
            if part.strip():
                raw_parts.append(part.strip())
    return list(dict.fromkeys(raw_parts))


def scrobble_artist_parts(scrobble: asyncpg.Record) -> List[str]:
    parts = []
    parts.extend(split_artist_names(scrobble["artist_name"]))
    parts.extend(extract_featured_artists(scrobble["track_name"]))
    return list(dict.fromkeys([p for p in parts if p]))


@lru_cache(maxsize=200000)
def _strip_benign_suffix(title: str) -> str:
    if not title:
        return ""
    original = title
    pattern = re.compile(r"\s*[\(\[]([^\)\]]+)[\)\]]\s*$")
    while True:
        match = pattern.search(title)
        if not match:
            break
        suffix = match.group(1)
        tokens = re.findall(r"[a-z0-9]+", suffix.lower())
        if not tokens:
            break
        if all(token.isdigit() or token in BENIGN_SUFFIX_TOKENS for token in tokens):
            title = title[: match.start()].rstrip()
            continue
        break
    return title or original


@lru_cache(maxsize=200000)
def normalize_title(value: Optional[str]) -> str:
    if not value:
        return ""
    stripped = re.sub(r"^\s*\d{1,3}\s*[-.\u2013]\s*", "", value)
    stripped = re.sub(r"^\s*\d{1,3}\s+", "", stripped)
    stripped = re.sub(
        r"^\s*[^-]{1,80}\s-\s+",
        "",
        stripped,
    )
    stripped = _strip_benign_suffix(stripped)
    stripped = stripped.replace("⦵", "music of the spheres")
    stripped = stripped.replace("❍", "music of the spheres ii")
    stripped = stripped.replace("✧", "alien choir")
    stripped = stripped.replace("∞", "infinity sign")
    stripped = stripped.replace("♡", "human heart")
    stripped = stripped.replace("♥", "human heart")
    stripped = stripped.replace("❤", "human heart")
    stripped = stripped.replace("∞", "infinity")
    stripped = stripped.replace("♡", "heart")
    stripped = stripped.replace("♥", "heart")
    stripped = stripped.replace("❤", "heart")
    stripped = stripped.replace("⦵", "sphere")
    stripped = re.sub(
        r"\s*[\(\[]\s*(feat\.?|featuring|ft\.?)\s+[^\)\]]+[\)\]]\s*$",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    stripped = re.sub(
        r"\s*[\(\[]\s*with\s+[^\)\]]+[\)\]]\s*$",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    stripped = re.sub(
        r"\s+(feat\.?|featuring|ft\.?)\s+.+$",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    stripped = re.sub(
        r"\s+with\s+.+$",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    stripped = re.sub(
        r"\s*-?\s*(radio edit|edit|remix|acoustic|version|mix|live|mono|stereo|"
        r"12\" version|12 inch version|single version|album version)\s*$",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    stripped = stripped.replace("’", "'")
    return _normalize_basic(stripped)


@lru_cache(maxsize=200000)
def normalize_artist(value: Optional[str]) -> str:
    name = normalize_name(value)
    aliases = {
        "p nk": "pink",
        "p!nk": "pink",
        "r e m": "rem",
        "a ha": "aha",
        "ac dc": "acdc",
    }
    if name in aliases:
        return aliases[name]
    tokens = name.split()
    if tokens and all(len(token) == 1 for token in tokens):
        return "".join(tokens)
    return name


@lru_cache(maxsize=200000)
def normalize_name(value: Optional[str]) -> str:
    return _normalize_basic(value)


def _album_artist_relation(
    scrobble_artist: str, track_artist: str, album_artist: str
) -> Tuple[float, str, int]:
    if not album_artist:
        return 0.0, "", 0
    if album_artist in ("various artists", "various", "va"):
        return -0.4, "album_artist_various", -1
    if album_artist == scrobble_artist or album_artist == track_artist:
        return 0.3, "album_artist_match", 1
    return -0.1, "album_artist_mismatch", -1


def _release_type_adjust(release_type: Optional[str]) -> Tuple[float, str, int]:
    if not release_type:
        return 0.0, "", 0
    rt = release_type.lower()
    preferred = {"album", "single", "ep"}
    deprioritized = {"compilation", "live", "remix", "soundtrack", "dj-mix", "mix"}
    if rt in preferred:
        return 0.15, "release_type_preferred", 1
    if rt in deprioritized:
        return -0.25, "release_type_deprioritized", -1
    return 0.0, "", 0


MODEL_FEATURES = [
    "track_mbid_match",
    "artist_mbid_match",
    "album_mbid_match",
    "artist_name_match",
    "track_name_match",
    "album_name_match",
    "album_artist_match",
    "album_artist_various",
    "release_type_preferred",
    "release_type_deprioritized",
    "fuzzy_title_score",
]

DEFAULT_SKIP_ARTISTS = {
    "bbc radio",
    "bbc radio 1",
    "bbc radio 1xtra",
    "bbc radio 2",
    "bbc radio 3",
    "bbc radio 4",
    "bbc radio 4 extra",
    "bbc radio 5 live",
    "bbc radio 6 music",
    "bbc radio scotland",
    "bbc radio ulster",
    "bbc radio wales",
    "bbc world service",
    "cariad lloyd",
    "leo laporte and the twits",
    "muddy knees media",
    "hotel spa",
    "tom merritt molly wood and veronica belmont",
    "steve gibson with leo laporte",
    "pixel corps",
    "stephen colbert",
    "plosive productions",
    "rain sounds xle library",
    "nature sounds xle library",
    "spa",
}


async def ensure_match_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lastfm_scrobble_match (
            id BIGSERIAL PRIMARY KEY,
            scrobble_id BIGINT NOT NULL,
            track_id BIGINT NOT NULL,
            match_score DOUBLE PRECISION NOT NULL,
            match_method TEXT NOT NULL,
            match_reason TEXT,
            match_version TEXT,
            matched_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(scrobble_id),
            FOREIGN KEY(scrobble_id) REFERENCES lastfm_scrobble(id) ON DELETE CASCADE,
            FOREIGN KEY(track_id) REFERENCES track(id) ON DELETE CASCADE
        );
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lastfm_match_cache (
            id BIGSERIAL PRIMARY KEY,
            cache_key TEXT UNIQUE NOT NULL,
            track_id BIGINT NOT NULL,
            match_score DOUBLE PRECISION NOT NULL,
            match_method TEXT NOT NULL,
            match_reason TEXT,
            match_version TEXT,
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            FOREIGN KEY(track_id) REFERENCES track(id) ON DELETE CASCADE
        );
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lastfm_scrobble_miss (
            id BIGSERIAL PRIMARY KEY,
            scrobble_id BIGINT UNIQUE NOT NULL,
            lastfm_username TEXT NOT NULL,
            match_version TEXT,
            reason TEXT,
            candidate_score DOUBLE PRECISION,
            candidate_artist TEXT,
            candidate_album TEXT,
            candidate_track TEXT,
            attempted_at TIMESTAMPTZ DEFAULT NOW(),
            FOREIGN KEY(scrobble_id) REFERENCES lastfm_scrobble(id) ON DELETE CASCADE
        );
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lastfm_match_candidate (
            id BIGSERIAL PRIMARY KEY,
            scrobble_id BIGINT NOT NULL,
            track_id BIGINT NOT NULL,
            score DOUBLE PRECISION NOT NULL,
            method TEXT NOT NULL,
            reason TEXT,
            rank INTEGER,
            cache_key TEXT,
            candidate_artist TEXT,
            candidate_album TEXT,
            candidate_track TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(scrobble_id, track_id),
            FOREIGN KEY(scrobble_id) REFERENCES lastfm_scrobble(id) ON DELETE CASCADE,
            FOREIGN KEY(track_id) REFERENCES track(id) ON DELETE CASCADE
        );
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lastfm_match_feedback (
            id BIGSERIAL PRIMARY KEY,
            scrobble_id BIGINT NOT NULL,
            track_id BIGINT NOT NULL,
            decision TEXT NOT NULL CHECK (decision IN ('accept', 'reject')),
            notes TEXT,
            cache_key TEXT,
            reviewed_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(scrobble_id, track_id, decision),
            FOREIGN KEY(scrobble_id) REFERENCES lastfm_scrobble(id) ON DELETE CASCADE,
            FOREIGN KEY(track_id) REFERENCES track(id) ON DELETE CASCADE
        );
        """
    )
    await conn.execute(
        "ALTER TABLE lastfm_match_candidate ADD COLUMN IF NOT EXISTS cache_key TEXT"
    )
    await conn.execute(
        "ALTER TABLE lastfm_match_feedback ADD COLUMN IF NOT EXISTS cache_key TEXT"
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lastfm_match_model (
            name TEXT PRIMARY KEY,
            weights JSONB NOT NULL,
            bias DOUBLE PRECISION NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lastfm_scrobble_skip (
            id BIGSERIAL PRIMARY KEY,
            scrobble_id BIGINT UNIQUE NOT NULL,
            lastfm_username TEXT NOT NULL,
            reason TEXT,
            skipped_at TIMESTAMPTZ DEFAULT NOW(),
            FOREIGN KEY(scrobble_id) REFERENCES lastfm_scrobble(id) ON DELETE CASCADE
        );
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lastfm_skip_artist (
            artist_name TEXT PRIMARY KEY
        );
        """
    )
    for artist in DEFAULT_SKIP_ARTISTS:
        await conn.execute(
            "INSERT INTO lastfm_skip_artist (artist_name) VALUES ($1) ON CONFLICT DO NOTHING",
            artist,
        )


async def fetch_scrobbles(
    conn: asyncpg.Connection, username: str, limit: int, include_matched: bool = False
) -> List[asyncpg.Record]:
    if include_matched:
        return await conn.fetch(
            """
            SELECT id, lastfm_username, track_mbid, track_name, album_mbid, album_name,
                   artist_mbid, artist_name
            FROM lastfm_scrobble
            WHERE lastfm_username = $1
            ORDER BY played_at DESC
            LIMIT $2
            """,
            username,
            limit,
        )
    else:
        return await conn.fetch(
            """
            SELECT s.id, s.lastfm_username, s.track_mbid, s.track_name, s.album_mbid, s.album_name,
                   s.artist_mbid, s.artist_name
            FROM lastfm_scrobble s
            LEFT JOIN lastfm_scrobble_match m ON m.scrobble_id = s.id
            LEFT JOIN lastfm_scrobble_skip sk ON sk.scrobble_id = s.id
            WHERE s.lastfm_username = $1
              AND m.scrobble_id IS NULL
              AND sk.scrobble_id IS NULL
            ORDER BY s.played_at DESC
            LIMIT $2
            """,
            username,
            limit,
        )


def build_cache_key(scrobble: asyncpg.Record) -> Optional[str]:
    if scrobble["track_mbid"]:
        return f"track_mbid:{scrobble['track_mbid']}"
    artist = normalize_name(scrobble["artist_name"])
    title = normalize_title(scrobble["track_name"])
    album = normalize_name(scrobble["album_name"])
    if artist and title:
        if album:
            return f"name:{artist}|{title}|{album}"
        return f"name:{artist}|{title}"
    return None


def _key_or_empty(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _get_artist_names(candidate: asyncpg.Record) -> List[str]:
    try:
        names = candidate["artist_names"]
    except KeyError:
        return []
    if not names:
        return []
    return [normalize_name(name) for name in names if name]


async def preload_artist_lookup(conn: asyncpg.Connection) -> Dict[str, str]:
    rows = await conn.fetch("SELECT mbid, name FROM artist")
    lookup: Dict[str, str] = {}
    for row in rows:
        name = normalize_artist(row["name"])
        if name and name not in lookup:
            lookup[name] = row["mbid"]
    return lookup


async def preload_skip_artists(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch("SELECT artist_name FROM lastfm_skip_artist")
    return {row["artist_name"] for row in rows}


async def preload_tracks(
    conn: asyncpg.Connection,
    scrobbles: List[asyncpg.Record],
    artist_lookup: Dict[str, str],
) -> Dict[str, Dict[Any, List[asyncpg.Record]]]:
    track_mbids = {s["track_mbid"] for s in scrobbles if s["track_mbid"]}
    release_mbids = {s["album_mbid"] for s in scrobbles if s["album_mbid"]}
    artist_mbids = {s["artist_mbid"] for s in scrobbles if s["artist_mbid"]}
    for s in scrobbles:
        if s["artist_mbid"]:
            continue
        for name in scrobble_artist_parts(s):
            mbid = artist_lookup.get(normalize_artist(name))
            if mbid:
                artist_mbids.add(mbid)
    artist_names = {normalize_artist(s["artist_name"]) for s in scrobbles if s["artist_name"]}
    artist_names.update({s["artist_name"].strip().lower() for s in scrobbles if s["artist_name"]})
    artist_names.update({_regex_normalize(s["artist_name"]) for s in scrobbles if s["artist_name"]})
    for s in scrobbles:
        for part in extract_featured_artists(s["track_name"]):
            artist_names.add(part)
            artist_names.add(part.strip().lower())
        for part in extract_featured_artist_raw_parts(s["track_name"]):
            artist_names.add(part.strip().lower())
            artist_names.add(_regex_normalize(part))
    for s in scrobbles:
        if s["artist_name"]:
            for part in scrobble_artist_parts(s):
                artist_names.add(normalize_artist(part))
                artist_names.add(part.strip().lower())
    
    title_names = {normalize_title(s["track_name"]) for s in scrobbles if s["track_name"]}
    title_names.update({s["track_name"].strip().lower() for s in scrobbles if s["track_name"]})
    title_names.update({_regex_normalize(s["track_name"]) for s in scrobbles if s["track_name"]})
    for name in list(title_names):
        if name:
            title_names.update(_title_variants(name))
    
    album_names = {normalize_name(s["album_name"]) for s in scrobbles if s["album_name"]}
    album_names.update({s["album_name"].strip().lower() for s in scrobbles if s["album_name"]})
    album_names.update({_regex_normalize(s["album_name"]) for s in scrobbles if s["album_name"]})

    indexes: Dict[str, Dict[Any, List[asyncpg.Record]]] = {
        "track_mbid": {},
        "release": {},
        "release_artist": {},
        "artist_title": {},
        "title_album": {},
        "artist": {},
        "artist_any_title": {},
        "artist_any": {},
        "artist_mbid": {},
    }

    if track_mbids:
        rows = await conn.fetch(
            """
            SELECT t.id, t.title, t.artist, t.album, t.artist_mbid, t.track_mbid, t.release_mbid,
                   t.duration_seconds, t.album_artist, t.album_artist_mbid, t.release_type,
                   COALESCE(an.names, ARRAY[]::text[]) AS artist_names
            FROM track t
            LEFT JOIN LATERAL (
                SELECT array_agg(DISTINCT a.name) AS names
                FROM track_artist ta
                JOIN artist a ON a.mbid = ta.artist_mbid
                WHERE ta.track_id = t.id
            ) an ON TRUE
            WHERE track_mbid = ANY($1::text[])
            """,
            list(track_mbids),
        )
        for row in rows:
            indexes["track_mbid"].setdefault(row["track_mbid"], []).append(row)

    if release_mbids and artist_mbids:
        rows = await conn.fetch(
            """
            SELECT t.id, t.title, t.artist, t.album, t.artist_mbid, t.track_mbid, t.release_mbid,
                   t.duration_seconds, t.album_artist, t.album_artist_mbid, t.release_type,
                   COALESCE(an.names, ARRAY[]::text[]) AS artist_names
            FROM track t
            LEFT JOIN LATERAL (
                SELECT array_agg(DISTINCT a.name) AS names
                FROM track_artist ta
                JOIN artist a ON a.mbid = ta.artist_mbid
                WHERE ta.track_id = t.id
            ) an ON TRUE
            WHERE release_mbid = ANY($1::text[]) AND artist_mbid = ANY($2::text[])
            """,
            list(release_mbids),
            list(artist_mbids),
        )
        for row in rows:
            key = (row["release_mbid"], row["artist_mbid"])
            indexes["release_artist"].setdefault(key, []).append(row)

    if release_mbids:
        rows = await conn.fetch(
            """
            SELECT t.id, t.title, t.artist, t.album, t.artist_mbid, t.track_mbid, t.release_mbid,
                   t.duration_seconds, t.album_artist, t.album_artist_mbid, t.release_type,
                   COALESCE(an.names, ARRAY[]::text[]) AS artist_names
            FROM track t
            LEFT JOIN LATERAL (
                SELECT array_agg(DISTINCT a.name) AS names
                FROM track_artist ta
                JOIN artist a ON a.mbid = ta.artist_mbid
                WHERE ta.track_id = t.id
            ) an ON TRUE
            WHERE release_mbid = ANY($1::text[])
            """,
            list(release_mbids),
        )
        for row in rows:
            indexes["release"].setdefault(row["release_mbid"], []).append(row)

    if artist_names and title_names:
        rows = await conn.fetch(
            """
            SELECT t.id, t.title, t.artist, t.album, t.artist_mbid, t.track_mbid, t.release_mbid,
                   t.duration_seconds, t.album_artist, t.album_artist_mbid, t.release_type,
                   COALESCE(an.names, ARRAY[]::text[]) AS artist_names
            FROM track t
            LEFT JOIN LATERAL (
                SELECT array_agg(DISTINCT a.name) AS names
                FROM track_artist ta
                JOIN artist a ON a.mbid = ta.artist_mbid
                WHERE ta.track_id = t.id
            ) an ON TRUE
            WHERE (
                (
                    lower(t.artist) = ANY($1::text[])
                    OR lower(regexp_replace(t.artist, '[^a-z0-9]+', ' ', 'g')) = ANY($1::text[])
                    OR t.artist_mbid = ANY($2::text[])
                )
                AND (
                    lower(t.title) = ANY($3::text[])
                    OR lower(replace(t.title, '.', '')) = ANY($3::text[])
                    OR lower(replace(t.title, '’', '''')) = ANY($3::text[])
                    OR lower(regexp_replace(t.title, '[^a-z0-9]+', ' ', 'g')) = ANY($3::text[])
                )
            ) OR t.track_mbid = ANY($4::text[])
            """,
            list(artist_names),
            list(artist_mbids),
            list(title_names),
            list(track_mbids),
        )
        for row in rows:
            title = normalize_title(row["title"])
            for variant in _title_variants(title):
                key = (normalize_artist(row["artist"]), variant)
                indexes["artist_title"].setdefault(key, []).append(row)

    if title_names and album_names:
        rows = await conn.fetch(
            """
            SELECT t.id, t.title, t.artist, t.album, t.artist_mbid, t.track_mbid, t.release_mbid,
                   t.duration_seconds, t.album_artist, t.album_artist_mbid, t.release_type,
                   COALESCE(an.names, ARRAY[]::text[]) AS artist_names
            FROM track t
            LEFT JOIN LATERAL (
                SELECT array_agg(DISTINCT a.name) AS names
                FROM track_artist ta
                JOIN artist a ON a.mbid = ta.artist_mbid
                WHERE ta.track_id = t.id
            ) an ON TRUE
            WHERE (
                lower(title) = ANY($1::text[])
                OR lower(regexp_replace(title, '[^a-z0-9]+', ' ', 'g')) = ANY($1::text[])
            )
            AND (
                lower(album) = ANY($2::text[])
                OR lower(regexp_replace(album, '[^a-z0-9]+', ' ', 'g')) = ANY($2::text[])
            )
            """,
            list(title_names),
            list(album_names),
        )
        for row in rows:
            title = normalize_title(row["title"])
            for variant in _title_variants(title):
                key = (variant, normalize_name(row["album"]))
                indexes["title_album"].setdefault(key, []).append(row)

    if artist_names:
        rows = await conn.fetch(
            """
            SELECT t.id, t.title, t.artist, t.album, t.artist_mbid, t.track_mbid, t.release_mbid,
                   t.duration_seconds, t.album_artist, t.album_artist_mbid, t.release_type,
                   COALESCE(an.names, ARRAY[]::text[]) AS artist_names
            FROM track t
            LEFT JOIN LATERAL (
                SELECT array_agg(DISTINCT a.name) AS names
                FROM track_artist ta
                JOIN artist a ON a.mbid = ta.artist_mbid
                WHERE ta.track_id = t.id
            ) an ON TRUE
            WHERE lower(artist) = ANY($1::text[])
               OR lower(regexp_replace(artist, '[^a-z0-9]+', ' ', 'g')) = ANY($1::text[])
            """,
            list(artist_names),
        )
        for row in rows:
            key = normalize_artist(row["artist"])
            indexes["artist"].setdefault(key, []).append(row)

    if artist_names:
        rows = await conn.fetch(
            """
            SELECT t.id, t.title, t.artist, t.album, t.artist_mbid, t.track_mbid, t.release_mbid,
                   t.duration_seconds, t.album_artist, t.album_artist_mbid, t.release_type,
                   COALESCE(an.names, ARRAY[]::text[]) AS artist_names
            FROM track t
            JOIN track_artist ta ON ta.track_id = t.id
            JOIN artist a ON a.mbid = ta.artist_mbid
            LEFT JOIN LATERAL (
                SELECT array_agg(DISTINCT a2.name) AS names
                FROM track_artist ta2
                JOIN artist a2 ON a2.mbid = ta2.artist_mbid
                WHERE ta2.track_id = t.id
            ) an ON TRUE
            WHERE lower(a.name) = ANY($1::text[])
               OR lower(regexp_replace(a.name, '[^a-z0-9]+', ' ', 'g')) = ANY($1::text[])
            """,
            list(artist_names),
        )
        for row in rows:
            for name in row["artist_names"] or []:
                key = normalize_artist(name)
                indexes["artist_any"].setdefault(key, []).append(row)
                if row["title"]:
                    title = normalize_title(row["title"])
                    for variant in _title_variants(title):
                        key_title = (key, variant)
                        indexes["artist_any_title"].setdefault(key_title, []).append(row)

    if artist_mbids:
        rows = await conn.fetch(
            """
            SELECT t.id, t.title, t.artist, t.album, ta.artist_mbid, t.track_mbid, t.release_mbid,
                   t.duration_seconds, t.album_artist, t.album_artist_mbid, t.release_type,
                   COALESCE(an.names, ARRAY[]::text[]) AS artist_names
            FROM track t
            JOIN track_artist ta ON ta.track_id = t.id
            LEFT JOIN LATERAL (
                SELECT array_agg(DISTINCT a2.name) AS names
                FROM track_artist ta2
                JOIN artist a2 ON a2.mbid = ta2.artist_mbid
                WHERE ta2.track_id = t.id
            ) an ON TRUE
            WHERE ta.artist_mbid = ANY($1::text[])
            """,
            list(artist_mbids),
        )
        for row in rows:
            indexes["artist_mbid"].setdefault(row["artist_mbid"], []).append(row)

    return indexes


def _build_artist_volume(scrobbles: List[asyncpg.Record]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for scrobble in scrobbles:
        name = normalize_artist(scrobble["artist_name"])
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    return counts


def _collect_candidates(
    scrobble: asyncpg.Record,
    indexes: Dict[str, Dict[Any, List[asyncpg.Record]]],
    artist_lookup: Dict[str, str],
) -> List[asyncpg.Record]:
    candidates: List[asyncpg.Record] = []
    if scrobble["track_mbid"]:
        candidates.extend(indexes["track_mbid"].get(scrobble["track_mbid"], []))
    if scrobble["artist_mbid"]:
        candidates.extend(indexes["artist_mbid"].get(scrobble["artist_mbid"], []))
    if scrobble["album_mbid"]:
        candidates.extend(indexes["release"].get(scrobble["album_mbid"], []))
    artist_parts = scrobble_artist_parts(scrobble)
    if scrobble["artist_name"] or artist_parts:
        for artist_key in artist_parts or [normalize_artist(scrobble["artist_name"])]:
            artist_mbid = artist_lookup.get(artist_key)
            if artist_mbid:
                candidates.extend(indexes["artist_mbid"].get(artist_mbid, []))
    if scrobble["album_mbid"] and scrobble["artist_mbid"]:
        key = (scrobble["album_mbid"], scrobble["artist_mbid"])
        candidates.extend(indexes["release_artist"].get(key, []))
    if (scrobble["artist_name"] or artist_parts) and scrobble["track_name"]:
        title_key = normalize_title(scrobble["track_name"])
        for variant in _title_variants(title_key):
            for artist_key in artist_parts or [normalize_artist(scrobble["artist_name"])]:
                key = (artist_key, variant)
                candidates.extend(indexes["artist_title"].get(key, []))
                candidates.extend(indexes["artist_any_title"].get(key, []))
    if scrobble["track_name"] and scrobble["album_name"]:
        title_key = normalize_title(scrobble["track_name"])
        album_key = normalize_name(scrobble["album_name"])
        for variant in _title_variants(title_key):
            key = (variant, album_key)
            candidates.extend(indexes["title_album"].get(key, []))
    if candidates:
        return candidates
    # Fallback: broader artist-only candidates when strict title-based matches fail.
    if scrobble["artist_name"] or artist_parts:
        for artist_key in artist_parts or [normalize_artist(scrobble["artist_name"])]:
            candidates.extend(indexes["artist"].get(artist_key, []))
            candidates.extend(indexes["artist_any"].get(artist_key, []))
    if not candidates:
        return candidates
    # Gate fallback candidates by fuzzy title to avoid unrelated tracks.
    sc_title = normalize_title(scrobble["track_name"])
    if not sc_title:
        return candidates
    filtered = []
    for candidate in candidates:
        tr_title = normalize_title(candidate["title"])
        if not tr_title:
            continue
        if fuzz.ratio(sc_title, tr_title) >= 85:
            filtered.append(candidate)
    return filtered or candidates


def _is_various(value: Optional[str]) -> bool:
    if not value:
        return False
    return normalize_name(value) in ("various artists", "various", "va")


def extract_features(
    scrobble: asyncpg.Record, candidate: asyncpg.Record
) -> Dict[str, float]:
    sc_artist = normalize_artist(scrobble["artist_name"])
    sc_title = normalize_title(scrobble["track_name"])
    sc_album = normalize_name(scrobble["album_name"])
    artist_parts = scrobble_artist_parts(scrobble)

    tr_artist = normalize_artist(candidate["artist"])
    artist_names = [normalize_artist(name) for name in _get_artist_names(candidate)]
    tr_title = normalize_title(candidate["title"])
    tr_album = normalize_name(candidate["album"])
    tr_album_artist = normalize_artist(candidate["album_artist"])
    release_type = normalize_name(candidate["release_type"])

    features = {
        "track_mbid_match": 1.0
        if scrobble["track_mbid"]
        and candidate["track_mbid"]
        and scrobble["track_mbid"] == candidate["track_mbid"]
        else 0.0,
        "artist_mbid_match": 1.0
        if scrobble["artist_mbid"]
        and candidate["artist_mbid"]
        and scrobble["artist_mbid"] == candidate["artist_mbid"]
        else 0.0,
        "album_mbid_match": 1.0
        if scrobble["album_mbid"]
        and candidate["release_mbid"]
        and scrobble["album_mbid"] == candidate["release_mbid"]
        else 0.0,
        "artist_name_match": 1.0
        if sc_artist
        and (
            (tr_artist and sc_artist == tr_artist)
            or (artist_names and sc_artist in artist_names)
            or (artist_parts and any(part in artist_names or part == tr_artist for part in artist_parts))
        )
        else 0.0,
        "track_name_match": 1.0 if sc_title and tr_title and sc_title == tr_title else 0.0,
        "album_name_match": 1.0 if sc_album and tr_album and sc_album == tr_album else 0.0,
        "album_artist_match": 1.0
        if sc_artist
        and (
            sc_artist == tr_album_artist
            or (sc_artist == tr_artist and tr_album_artist == "")
        )
        else 0.0,
        "album_artist_various": 1.0 if _is_various(tr_album_artist) else 0.0,
        "release_type_preferred": 1.0
        if release_type in ("album", "single", "ep")
        else 0.0,
        "release_type_deprioritized": 1.0
        if release_type in ("compilation", "live", "remix", "soundtrack", "dj mix", "mix")
        else 0.0,
        "fuzzy_title_score": 0.0,
    }

    if sc_title and tr_title:
        features["fuzzy_title_score"] = fuzz.ratio(sc_title, tr_title) / 100.0
    return features


def apply_model_score(
    features: Dict[str, float],
    weights: Dict[str, float],
    bias: float,
) -> float:
    total = bias
    for name in MODEL_FEATURES:
        total += weights.get(name, 0.0) * features.get(name, 0.0)
    return 1.0 / (1.0 + math.exp(-total))


async def load_model(conn: asyncpg.Connection, name: str) -> Optional[Tuple[Dict[str, float], float]]:
    row = await conn.fetchrow(
        "SELECT weights, bias FROM lastfm_match_model WHERE name = $1",
        name,
    )
    if not row:
        return None
    weights = {k: float(v) for k, v in dict(row["weights"]).items()}
    return weights, float(row["bias"])


async def save_model(
    conn: asyncpg.Connection,
    name: str,
    weights: Dict[str, float],
    bias: float,
) -> None:
    await conn.execute(
        """
        INSERT INTO lastfm_match_model (name, weights, bias)
        VALUES ($1, $2, $3)
        ON CONFLICT (name) DO UPDATE SET
            weights = EXCLUDED.weights,
            bias = EXCLUDED.bias,
            updated_at = NOW()
        """,
        name,
        weights,
        bias,
    )


async def train_model(
    conn: asyncpg.Connection,
    name: str,
    epochs: int,
    lr: float,
) -> Tuple[Dict[str, float], float]:
    rows = await conn.fetch(
        """
        SELECT f.decision, s.track_mbid AS s_track_mbid, s.artist_mbid AS s_artist_mbid,
               s.album_mbid AS s_album_mbid, s.artist_name AS s_artist_name,
               s.track_name AS s_track_name, s.album_name AS s_album_name,
               t.track_mbid AS t_track_mbid, t.artist_mbid AS t_artist_mbid,
               t.release_mbid AS t_release_mbid, t.artist AS t_artist,
               t.title AS t_title, t.album AS t_album, t.album_artist AS t_album_artist,
               t.release_type AS t_release_type
        FROM lastfm_match_feedback f
        JOIN lastfm_scrobble s ON s.id = f.scrobble_id
        JOIN track t ON t.id = f.track_id
        """,
    )
    if not rows:
        raise RuntimeError("No feedback rows to train on.")

    weights = {name: 0.0 for name in MODEL_FEATURES}
    bias = 0.0

    for _ in range(epochs):
        for row in rows:
            label = 1.0 if row["decision"] == "accept" else 0.0
            scrobble = {
                "track_mbid": row["s_track_mbid"],
                "artist_mbid": row["s_artist_mbid"],
                "album_mbid": row["s_album_mbid"],
                "artist_name": row["s_artist_name"],
                "track_name": row["s_track_name"],
                "album_name": row["s_album_name"],
            }
            candidate = {
                "track_mbid": row["t_track_mbid"],
                "artist_mbid": row["t_artist_mbid"],
                "release_mbid": row["t_release_mbid"],
                "artist": row["t_artist"],
                "title": row["t_title"],
                "album": row["t_album"],
                "album_artist": row["t_album_artist"],
                "release_type": row["t_release_type"],
            }
            features = extract_features(scrobble, candidate)
            pred = apply_model_score(features, weights, bias)
            error = pred - label
            for name in MODEL_FEATURES:
                weights[name] -= lr * error * features.get(name, 0.0)
            bias -= lr * error

    await save_model(conn, name, weights, bias)
    return weights, bias


def score_candidate(
    scrobble: asyncpg.Record, candidate: asyncpg.Record
) -> Tuple[float, str, int, int]:
    score = 0.0
    reasons: List[str] = []

    artist_parts = scrobble_artist_parts(scrobble)
    if scrobble["track_mbid"] and candidate["track_mbid"]:
        if scrobble["track_mbid"] == candidate["track_mbid"]:
            score += 1.0
            reasons.append("track_mbid")

    if scrobble["artist_mbid"] and candidate["artist_mbid"]:
        if scrobble["artist_mbid"] == candidate["artist_mbid"]:
            score += 0.5
            reasons.append("artist_mbid")

    if scrobble["album_mbid"] and candidate["release_mbid"]:
        if scrobble["album_mbid"] == candidate["release_mbid"]:
            score += 0.4
            reasons.append("album_release_mbid")

    sc_artist = normalize_artist(scrobble["artist_name"])
    sc_title = normalize_title(scrobble["track_name"])
    sc_album = normalize_name(scrobble["album_name"])

    tr_artist = normalize_artist(candidate["artist"])
    artist_names = [normalize_artist(name) for name in _get_artist_names(candidate)]
    tr_title = normalize_title(candidate["title"])
    tr_album = normalize_name(candidate["album"])
    tr_album_artist = normalize_artist(candidate["album_artist"])

    if sc_artist and (
        (tr_artist and sc_artist == tr_artist)
        or (artist_names and sc_artist in artist_names)
        or (artist_parts and any(part in artist_names or part == tr_artist for part in artist_parts))
    ):
        score += 0.5
        reasons.append("artist_name")
    sc_title_stripped = _strip_leading_article(sc_title) if sc_title else ""
    tr_title_stripped = _strip_leading_article(tr_title) if tr_title else ""
    if sc_title and tr_title and (
        sc_title == tr_title
        or sc_title_stripped == tr_title
        or sc_title == tr_title_stripped
        or (sc_title_stripped and sc_title_stripped == tr_title_stripped)
    ):
        score += 0.5
        reasons.append("track_name")
    if sc_album and tr_album and sc_album == tr_album:
        score += 0.5
        reasons.append("album_name")
    if sc_album and tr_album and sc_album != tr_album:
        if scrobble["album_mbid"] and candidate["release_mbid"]:
            if scrobble["album_mbid"] == candidate["release_mbid"]:
                score -= 0.25
                reasons.append("album_mbid_name_mismatch")

    aa_delta, aa_reason, aa_rank = _album_artist_relation(
        sc_artist, tr_artist, tr_album_artist
    )
    if aa_reason:
        score += aa_delta
        reasons.append(aa_reason)

    rt_delta, rt_reason, rt_rank = _release_type_adjust(candidate["release_type"])
    if rt_reason:
        score += rt_delta
        reasons.append(rt_reason)

    score = max(0.0, min(score, 1.0))
    
    # --- SANITY CHECK ---
    # Determine if we have a title match (exact or fuzzy)
    sc_title_stripped = _strip_leading_article(sc_title) if sc_title else ""
    tr_title_stripped = _strip_leading_article(tr_title) if tr_title else ""
    title_match = (
        sc_title
        and tr_title
        and (
            sc_title == tr_title
            or sc_title_stripped == tr_title
            or sc_title == tr_title_stripped
            or (sc_title_stripped and sc_title_stripped == tr_title_stripped)
        )
    )
    
    # If standard title match failed, check fuzzy (token sort/set)
    if not title_match and sc_title and tr_title:
        # Quick fuzzy check to see if we should accept "Artist + Album" matches
        # or TRUST a track_mbid match
        ratio = fuzz.token_set_ratio(sc_title, tr_title)
        if ratio >= 80:
            title_match = True
            reasons.append(f"fuzzy_title_{ratio}")
    
    # RULE 1: If Title does NOT match, score cannot be > 0.6 (unless it's a specific instrumental/classical exception, handled elsewhere)
    # This prevents "Artist + Album" matches (0.5 + 0.5 = 1.0) for different tracks on the same album.
    if not title_match:
        # Penalize heavy
        if score > 0.6:
            score = 0.6
            reasons.append("title_mismatch_penalty")
            
    # RULE 2: Validate Track MBID
    # If we matched via MBID, but titles are wildly different, trust the Title (user intention) over the (possibly dragged) MBID.
    if "track_mbid" in reasons and not title_match:
         # Downgrade 
         score = 0.6
         reasons.append("mbid_title_mismatch")

    return score, "+".join(reasons), aa_rank, rt_rank


def classify_method(score: float, reason: str) -> str:
    has_title = "track_name" in reason or "fuzzy_title" in reason
    if "track_mbid" in reason:
        return "mbid_track"
    if "artist_mbid" in reason and "album_release_mbid" in reason:
        return "mbid_artist_release"
    if "artist_name" in reason and has_title and "album_name" in reason:
        return "name_artist_album"
    if "artist_name" in reason and has_title:
        return "name_artist_title"
    return "name_partial"


def accept_match(method: str, score: float, reason: str) -> bool:
    if method == "mbid_track":
        return True
    if method == "mbid_artist_release":
        return score >= 0.7
    if method == "name_artist_album":
        return score >= 0.7
    if method == "name_artist_title":
        return score >= 0.8
    return False


def match_scrobble(
    scrobble: asyncpg.Record,
    indexes: Dict[str, Dict[Any, List[asyncpg.Record]]],
    artist_lookup: Dict[str, str],
    artist_volume: Dict[str, int],
    skip_artists: set[str],
    fuzzy: bool,
    fuzzy_title_threshold: int,
    model: Optional[Tuple[Dict[str, float], float]],
    auto_accept_threshold: float,
) -> Tuple[
    Optional[Tuple[int, float, str, str]],
    str,
    Optional[Tuple[float, str, str, str]],
    List[Dict[str, Any]],
]:
    sc_artist = normalize_artist(scrobble["artist_name"])
    if sc_artist in skip_artists:
        return None, "skipped_artist", None, []

    candidates = _collect_candidates(scrobble, indexes, artist_lookup)
    if not candidates:
        return None, "no_candidates", None, []

    seen_ids = set()
    uniq_candidates: List[asyncpg.Record] = []
    for candidate in candidates:
        if candidate["id"] in seen_ids:
            continue
        seen_ids.add(candidate["id"])
        uniq_candidates.append(candidate)

    sc_artist = normalize_artist(scrobble["artist_name"])
    sc_title = normalize_title(scrobble["track_name"])
    sc_album = normalize_name(scrobble["album_name"])

    album_match_exists = False
    non_various_title_match_exists = False
    for candidate in uniq_candidates:
        tr_album = normalize_name(candidate["album"])
        tr_album_artist = normalize_artist(candidate["album_artist"])
        tr_artist = normalize_artist(candidate["artist"])
        tr_title = normalize_title(candidate["title"])
        if sc_title and sc_album and sc_title == tr_title and sc_album == tr_album:
            if tr_album_artist not in ("various artists", "various", "va"):
                if sc_artist and (sc_artist == tr_artist or sc_artist == tr_album_artist):
                    album_match_exists = True
                    break
        if sc_title and sc_artist and sc_title == tr_title:
            if tr_album_artist not in ("various artists", "various", "va"):
                if sc_artist == tr_artist or sc_artist == tr_album_artist:
                    non_various_title_match_exists = True

    best: Optional[Tuple[int, float, str, str, int, int]] = None
    best_model_score = None
    best_effective = None
    best_below: Optional[Tuple[float, str, str, str]] = None
    scored: List[Dict[str, Any]] = []
    for candidate in uniq_candidates:
        tr_album_artist = normalize_name(candidate["album_artist"])
        if album_match_exists and tr_album_artist in ("various artists", "various", "va"):
            continue
        if non_various_title_match_exists and tr_album_artist in (
            "various artists",
            "various",
            "va",
        ):
            continue
        score, reason, aa_rank, rt_rank = score_candidate(scrobble, candidate)
        method = classify_method(score, reason)
        model_score = None
        if model:
            features = extract_features(scrobble, candidate)
            model_score = apply_model_score(features, model[0], model[1])
        effective_score = model_score if model_score is not None else score
        scored.append(
            {
                "track_id": candidate["id"],
                "score": effective_score,
                "method": method,
                "reason": reason,
                "artist": candidate["artist"] or "",
                "album": candidate["album"] or "",
                "title": candidate["title"] or "",
            }
        )
        if best_below is None or effective_score > best_below[0]:
            best_below = (
                effective_score,
                candidate["artist"] or "",
                candidate["album"] or "",
                candidate["title"] or "",
            )
        if model_score is not None:
            if model_score < auto_accept_threshold and method != "mbid_track":
                continue
        else:
            if not accept_match(method, score, reason):
                continue
            title_match = "track_name" in reason or "fuzzy_title" in reason
            if not title_match:
                continue
            artist_count = artist_volume.get(sc_artist, 0)
            title_gate = 0.9 if artist_count >= 50 else 0.85
            if "fuzzy_title" in reason and score < title_gate:
                continue
        if best_effective is None or effective_score > best_effective:
            best = (candidate["id"], score, method, reason, aa_rank, rt_rank)
            best_model_score = model_score
            best_effective = effective_score
            continue
        if best and best_effective is not None and abs(effective_score - best_effective) <= 0.01:
            method_rank = {
                "mbid_track": 3,
                "mbid_artist_release": 2,
                "name_artist_album": 1,
                "name_artist_title": 0,
                "name_partial": -1,
            }
            current_rank = method_rank.get(method, -1)
            best_rank = method_rank.get(best[2], -1)
            if current_rank > best_rank:
                best = (candidate["id"], score, method, reason, aa_rank, rt_rank)
                best_model_score = model_score
                best_effective = effective_score
                continue
            if current_rank == best_rank:
                if aa_rank > best[4]:
                    best = (candidate["id"], score, method, reason, aa_rank, rt_rank)
                    best_model_score = model_score
                    best_effective = effective_score
                    continue
                if aa_rank == best[4] and rt_rank > best[5]:
                    best = (candidate["id"], score, method, reason, aa_rank, rt_rank)
                    best_model_score = model_score
                    best_effective = effective_score

    if not best and fuzzy:
        sc_title = normalize_title(scrobble["track_name"])
        if sc_title:
            best_fuzzy: Optional[Tuple[int, int]] = None
            for candidate in uniq_candidates:
                tr_title = normalize_title(candidate["title"])
                if not tr_title:
                    continue
                similarity = int(fuzz.ratio(sc_title, tr_title))
                if similarity < fuzzy_title_threshold:
                    continue
                if not best_fuzzy or similarity > best_fuzzy[1]:
                    best_fuzzy = (candidate["id"], similarity)
            if best_fuzzy:
                return (
                    best_fuzzy[0],
                    0.6,
                    "fuzzy_title",
                    f"fuzzy_title_{best_fuzzy[1]}",
                ), None, None, scored

    if not best:
        return None, "below_threshold", best_below, scored
    final_score = best_model_score if best_model_score is not None else best[1]
    return (best[0], final_score, best[2], best[3]), None, None, scored


async def run(args: argparse.Namespace) -> None:
    load_dotenv(ROOT / ".env")

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
            await ensure_match_table(conn)
            if args.train_model:
                await train_model(
                    conn,
                    args.model_name,
                    args.model_epochs,
                    args.model_lr,
                )
                console.print("[green]Model trained and saved.[/green]")
                return
            model = None
            if args.use_model:
                model = await load_model(conn, args.model_name)
            
            console.print(f"[cyan]Fetching scrobbles for user {args.user}...[/cyan]")
            # Fetch ALL potential work items (filtered by resume logic)
            all_scrobbles = await fetch_scrobbles(conn, args.user, args.limit, include_matched=args.force)
            console.print(f"[cyan]Found {len(all_scrobbles)} scrobbles to process.[/cyan]")
            
            if not all_scrobbles:
                console.print("[green]Nothing to do![/green]")
                return

            artist_lookup = await preload_artist_lookup(conn)
            skip_artists = await preload_skip_artists(conn)
            
            # Global stats
            global_metrics = {
                "matched": 0,
                "skipped": 0,
                "unmatched": 0,
                "cache_hits": 0
            }

            progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TextColumn("matched [green]{task.fields[matched]}[/green]"),
                TextColumn("skipped [yellow]{task.fields[skipped]}[/yellow]"),
                TextColumn("unmatched [red]{task.fields[unmatched]}[/red]"),
                TextColumn("cache [blue]{task.fields[cache_hits]}[/blue]"),
                TimeElapsedColumn(),
                console=console,
            )

            BATCH_SIZE = 5000
            total_scrobbles = len(all_scrobbles)
            
            with progress:
                main_task_id = progress.add_task(
                    "Matching scrobbles",
                    total=total_scrobbles,
                    matched=0,
                    skipped=0,
                    unmatched=0,
                    cache_hits=0,
                )

                for i in range(0, total_scrobbles, BATCH_SIZE):
                    batch_scrobbles = all_scrobbles[i : i + BATCH_SIZE]
                    console.print(f"\n[bold]Processing Batch {i // BATCH_SIZE + 1} ({len(batch_scrobbles)} items)[/bold]")
                    
                    # Preload tracks for this batch ONLY
                    indexes = await preload_tracks(conn, batch_scrobbles, artist_lookup)
                    artist_volume = _build_artist_volume(batch_scrobbles)

                    # Prepare batch-local data structures
                    batch_scrobble_ids = [s["id"] for s in batch_scrobbles]
                    
                    # Ensure existing matches are checked (redundant if fetch_scrobbles works, but safe)
                    existing_rows = await conn.fetch(
                        """
                        SELECT scrobble_id FROM lastfm_scrobble_match
                        WHERE scrobble_id = ANY($1::bigint[])
                        """,
                        batch_scrobble_ids,
                    )
                    existing_matches = {row["scrobble_id"] for row in existing_rows}

                    cache_keys = [build_cache_key(s) for s in batch_scrobbles]
                    cache_keys = [k for k in cache_keys if k]
                    cached_matches: Dict[str, asyncpg.Record] = {}
                    if cache_keys:
                        cache_rows = await conn.fetch(
                            """
                            SELECT cache_key, track_id, match_score, match_method, match_reason
                            FROM lastfm_match_cache
                            WHERE cache_key = ANY($1::text[])
                            """,
                            cache_keys,
                        )
                        cached_matches = {row["cache_key"]: row for row in cache_rows}

                    match_rows: List[Tuple[int, int, float, str, str, str]] = []
                    cache_rows: List[Tuple[str, int, float, str, str, str]] = []
                    miss_rows: List[Tuple[int, str, str, str, Optional[float], Optional[str], Optional[str], Optional[str]]] = []
                    skip_rows: List[Tuple[int, str, str]] = []
                    candidate_rows: List[Tuple[int, int, float, str, str, int, str, str, str, str]] = []

                    # Define process logic closing over current batch context
                    def process_scrobble_batch(scrobble: asyncpg.Record):
                        cache_key = build_cache_key(scrobble)
                        if cache_key and cache_key in cached_matches and not args.force:
                            cached = cached_matches[cache_key]
                            return ("cache", (scrobble["id"], cached["track_id"], cached["match_score"], cached["match_method"], cached["match_reason"], args.match_version), None, scrobble["id"], scrobble["lastfm_username"], None, None, [], cache_key)
                        
                        if scrobble["id"] in existing_matches and not args.force:
                            return ("skip", None, None, scrobble["id"], scrobble["lastfm_username"], None, None, [], cache_key)
                        
                        best, miss_reason, miss_candidate, scored = match_scrobble(
                            scrobble,
                            indexes,
                            artist_lookup,
                            artist_volume,
                            skip_artists,
                            args.fuzzy,
                            args.fuzzy_title_threshold,
                            model,
                            args.auto_accept_threshold,
                        )
                        
                        if not best:
                            return ("unmatched", None, None, scrobble["id"], scrobble["lastfm_username"], miss_reason, miss_candidate, scored, cache_key)
                        
                        track_id, score, method, reason = best
                        if args.dry_run:
                            return ("matched", None, None, scrobble["id"], scrobble["lastfm_username"], None, None, scored, cache_key)
                        
                        match_row = (scrobble["id"], track_id, score, method, reason, args.match_version)
                        cache_row = (cache_key, track_id, score, method, reason, args.match_version) if cache_key else None
                        return ("matched", match_row, cache_row, scrobble["id"], scrobble["lastfm_username"], None, None, scored, cache_key)

                    # Run Batch
                    if args.workers > 1:
                        with ThreadPoolExecutor(max_workers=args.workers) as executor:
                            futures = [executor.submit(process_scrobble_batch, s) for s in batch_scrobbles]
                            for future in as_completed(futures):
                                res = future.result()
                                _handle_result(
                                    res,
                                    args,
                                    global_metrics,
                                    match_rows,
                                    cache_rows,
                                    miss_rows,
                                    skip_rows,
                                    candidate_rows,
                                )
                                progress.advance(main_task_id)
                                progress.update(main_task_id, **global_metrics)
                    else:
                        for scrobble in batch_scrobbles:
                            res = process_scrobble_batch(scrobble)
                            _handle_result(
                                res,
                                args,
                                global_metrics,
                                match_rows,
                                cache_rows,
                                miss_rows,
                                skip_rows,
                                candidate_rows,
                            )
                            progress.advance(main_task_id)
                            progress.update(main_task_id, **global_metrics)

                    # Fuzzy Pass for Batch
                    if miss_rows and not args.dry_run and args.fuzzy:
                        await _run_fuzzy_pass(conn, args, miss_rows, batch_scrobbles, match_rows, global_metrics, progress, main_task_id, console)

                    # Commit Batch
                    if not args.dry_run:
                        if match_rows:
                            await conn.executemany("""
                                INSERT INTO lastfm_scrobble_match (scrobble_id, track_id, match_score, match_method, match_reason, match_version)
                                VALUES ($1, $2, $3, $4, $5, $6)
                                ON CONFLICT (scrobble_id) DO UPDATE SET
                                    track_id = EXCLUDED.track_id, match_score = EXCLUDED.match_score, match_method = EXCLUDED.match_method,
                                    match_reason = EXCLUDED.match_reason, match_version = EXCLUDED.match_version, matched_at = NOW()
                            """, match_rows)
                            scrobble_ids = [row[0] for row in match_rows]
                            await conn.execute(
                                "DELETE FROM lastfm_scrobble_miss WHERE scrobble_id = ANY($1::bigint[])",
                                scrobble_ids,
                            )
                            await conn.execute(
                                "DELETE FROM lastfm_scrobble_skip WHERE scrobble_id = ANY($1::bigint[])",
                                scrobble_ids,
                            )
                        if cache_rows:
                            await conn.executemany("""
                                INSERT INTO lastfm_match_cache (cache_key, track_id, match_score, match_method, match_reason, match_version)
                                VALUES ($1, $2, $3, $4, $5, $6)
                                ON CONFLICT (cache_key) DO UPDATE SET
                                    track_id = EXCLUDED.track_id, match_score = EXCLUDED.match_score, match_method = EXCLUDED.match_method,
                                    match_reason = EXCLUDED.match_reason, match_version = EXCLUDED.match_version, updated_at = NOW()
                            """, cache_rows)
                        if candidate_rows:
                             await conn.executemany("""
                                INSERT INTO lastfm_match_candidate (scrobble_id, track_id, score, method, reason, rank, cache_key, candidate_artist, candidate_album, candidate_track)
                                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                                ON CONFLICT (scrobble_id, track_id) DO UPDATE SET
                                    score = EXCLUDED.score, method = EXCLUDED.method, reason = EXCLUDED.reason, rank = EXCLUDED.rank,
                                    cache_key = EXCLUDED.cache_key, candidate_artist = EXCLUDED.candidate_artist, candidate_album = EXCLUDED.candidate_album,
                                    candidate_track = EXCLUDED.candidate_track, created_at = NOW()
                            """, candidate_rows)
                        if miss_rows:
                             # filter out ones recovered by fuzzy
                             miss_rows_final = [r for r in miss_rows if r is not None]
                             if miss_rows_final:
                                 await conn.executemany("""
                                    INSERT INTO lastfm_scrobble_miss (scrobble_id, lastfm_username, match_version, reason, candidate_score, candidate_artist, candidate_album, candidate_track)
                                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                                    ON CONFLICT (scrobble_id) DO UPDATE SET
                                        lastfm_username = EXCLUDED.lastfm_username, match_version = EXCLUDED.match_version, reason = EXCLUDED.reason,
                                        candidate_score = EXCLUDED.candidate_score, candidate_artist = EXCLUDED.candidate_artist,
                                        candidate_album = EXCLUDED.candidate_album, candidate_track = EXCLUDED.candidate_track, attempted_at = NOW()
                                """, miss_rows_final)
                        if skip_rows:
                            await conn.executemany(
                                """
                                INSERT INTO lastfm_scrobble_skip (scrobble_id, lastfm_username, reason)
                                VALUES ($1, $2, $3)
                                ON CONFLICT (scrobble_id) DO UPDATE SET
                                    lastfm_username = EXCLUDED.lastfm_username,
                                    reason = EXCLUDED.reason,
                                    skipped_at = NOW()
                                """,
                                skip_rows,
                            )
                    
                    # Cleanup
                    del indexes
                    del batch_scrobbles
                    del match_rows, cache_rows, miss_rows, skip_rows, candidate_rows
                    
            console.print(
                f"[bold]Done[/bold]. Matched [green]{global_metrics['matched']}[/green], "
                f"skipped [yellow]{global_metrics['skipped']}[/yellow], "
                f"unmatched [red]{global_metrics['unmatched']}[/red], "
                f"cache hits [blue]{global_metrics['cache_hits']}[/blue]."
            )

def _handle_result(res, args, metrics, match_rows, cache_rows, miss_rows, skip_rows, candidate_rows):
    status, match_row, cache_row, s_id, uname, miss_reason, miss_candidate, scored, cache_key = res
    if status == "cache":
        metrics["cache_hits"] += 1
        metrics["matched"] += 1
        if match_row: match_rows.append(match_row)
    elif status == "skip":
        metrics["skipped"] += 1
    elif status == "matched":
        metrics["matched"] += 1
        if match_row: match_rows.append(match_row)
        if cache_row: cache_rows.append(cache_row)
        if scored and not args.dry_run:
            _store_candidates(args, s_id, scored, cache_key, candidate_rows)
    elif status == "unmatched":
        if miss_reason == "skipped_artist":
            metrics["skipped"] += 1
            if not args.dry_run:
                skip_rows.append((s_id, uname, miss_reason))
            return
        metrics["unmatched"] += 1
        if not args.dry_run:
            c_score, c_artist, c_album, c_track = (None, None, None, None)
            if miss_reason == "below_threshold" and miss_candidate:
                c_score, c_artist, c_album, c_track = miss_candidate
            miss_rows.append((s_id, uname, args.match_version, miss_reason or "no_candidate_match", c_score, c_artist, c_album, c_track))
            if scored:
                _store_candidates(args, s_id, scored, cache_key, candidate_rows)

def _store_candidates(args, scrobble_id, scored, cache_key, candidate_rows):
    scored_sorted = sorted(scored, key=lambda row: row["score"], reverse=True)
    best_score = scored_sorted[0]["score"] if scored_sorted else None
    second_score = scored_sorted[1]["score"] if len(scored_sorted) > 1 else None
    should_store = (
        args.store_candidates
        or (best_score is not None and best_score < args.review_threshold)
        or (best_score is not None and best_score < args.auto_accept_threshold and second_score is not None and (best_score - second_score) <= args.review_delta)
    )
    if should_store:
        candidate_cache_key = cache_key or f"scrobble:{scrobble_id}"
        for idx, row in enumerate(scored_sorted[: args.candidate_limit], start=1):
            candidate_rows.append((scrobble_id, row["track_id"], row["score"], row["method"], row["reason"], idx, candidate_cache_key, row["artist"], row["album"], row["title"]))

async def _run_fuzzy_pass(conn, args, miss_rows, scrobbles, match_rows, metrics, progress, main_task_id, console):
    miss_map = {row[0]: i for i, row in enumerate(miss_rows)}
    miss_scrobbles = [s for s in scrobbles if s["id"] in miss_map]
    
    fuzzy_matches_found = 0
    fuzzy_progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("recovered [green]{task.fields[recovered]}[/green]"),
        TimeElapsedColumn(),
        console=console,
    )
    
    with fuzzy_progress:
        task_id = fuzzy_progress.add_task(f"Fuzzy Searching {len(miss_rows)} misses", total=len(miss_scrobbles), recovered=0)
        for scrobble in miss_scrobbles:
            search_artist = scrobble["artist_name"]
            title_query = scrobble["track_name"]
            
            if not search_artist or not title_query or len(search_artist) < 3 or len(title_query) < 3:
                fuzzy_progress.advance(task_id)
                continue

            try:
                rows = await conn.fetch(
                    """
                SELECT t.id, t.title, t.artist, t.album, t.artist_mbid, t.track_mbid, t.release_mbid,
                       t.duration_seconds, t.album_artist, t.album_artist_mbid, t.release_type
                FROM track t
                LEFT JOIN track_artist ta ON ta.track_id = t.id
                LEFT JOIN artist a ON a.mbid = ta.artist_mbid
                WHERE t.title % $2
                  AND (
                      t.artist % $1
                      OR t.album_artist % $1
                      OR a.name % $1
                  )
                ORDER BY (t.title <-> $2) + (t.artist <-> $1) ASC
                LIMIT 10
                """,
                    search_artist,
                    title_query,
                )
            except asyncpg.PostgresError as exc:
                console.print(f"[yellow]Skipping fuzzy DB pass: {exc}[/yellow]")
                return
            
            candidates = rows
            scored_fuzzy = []
            for cand in candidates:
                score, reason, _, _ = score_candidate(scrobble, cand)
                method = classify_method(score, reason)
                scored_fuzzy.append({"track_id": cand["id"], "score": score, "reason": reason, "method": method + "_fuzzy_db", "artist": cand["artist"], "title": cand["title"], "album": cand["album"]})
            
            scored_fuzzy.sort(key=lambda x: x["score"], reverse=True)
            if scored_fuzzy and scored_fuzzy[0]["score"] >= args.auto_accept_threshold:
                best = scored_fuzzy[0]
                fuzzy_matches_found += 1
                miss_idx = miss_map[scrobble["id"]]
                miss_rows[miss_idx] = None
                metrics["unmatched"] -= 1
                metrics["matched"] += 1
                match_rows.append((scrobble["id"], best["track_id"], best["score"], best["method"], best["reason"], args.match_version))
                fuzzy_progress.update(task_id, recovered=fuzzy_matches_found)
                fuzzy_progress.advance(task_id)
                continue

            # Third Pass
            if not title_query or len(title_query) < 5: 
                fuzzy_progress.advance(task_id)
                continue 

            try:
                rows = await conn.fetch("""
                SELECT t.id, t.title, t.artist, t.album, t.artist_mbid, t.track_mbid, t.release_mbid,
                       t.duration_seconds, t.album_artist, t.album_artist_mbid, t.release_type
                FROM track t
                WHERE t.title % $1
                ORDER BY t.title <-> $1 ASC LIMIT 10
                """, title_query)
            except asyncpg.PostgresError as exc:
                console.print(f"[yellow]Skipping fuzzy DB cross-pass: {exc}[/yellow]")
                break
            
            scored_cross = []
            for cand in rows:
                tr_artist_norm = normalize_artist(cand["artist"])
                sc_artist_norm = normalize_artist(scrobble["artist_name"])
                artist_match = (sc_artist_norm in tr_artist_norm or tr_artist_norm in sc_artist_norm) or (fuzz.partial_ratio(sc_artist_norm, tr_artist_norm) > 80)
                
                if artist_match:
                     score, reason, _, _ = score_candidate(scrobble, cand)
                     if "artist_name" not in reason: score += 0.4; reason += "+cross_artist_recovery"
                     if "track_name" not in reason and "fuzzy_token_set" not in reason and fuzz.ratio(title_query, normalize_title(cand["title"])) > 80: score += 0.5; reason += "+fuzzy_title_global"
                     score = min(score, 1.0)
                     method = classify_method(score, reason)
                     scored_cross.append({"track_id": cand["id"], "score": score, "reason": reason, "method": method + "_cross_artist", "artist": cand["artist"], "title": cand["title"], "album": cand["album"]})
            
            if scored_cross:
                scored_cross.sort(key=lambda x: x["score"], reverse=True)
                best = scored_cross[0]
                if best["score"] >= args.auto_accept_threshold:
                    fuzzy_matches_found += 1
                    miss_idx = miss_map[scrobble["id"]]
                    miss_rows[miss_idx] = None
                    metrics["unmatched"] -= 1
                    metrics["matched"] += 1
                    match_rows.append((scrobble["id"], best["track_id"], best["score"], best["method"], best["reason"], args.match_version))
                    fuzzy_progress.update(task_id, recovered=fuzzy_matches_found)
            
            fuzzy_progress.advance(task_id)
    
    # Update main progress matched count from findings
    progress.update(main_task_id, **metrics)
    console.print(f"[green]Fuzzy DB Search recovered {fuzzy_matches_found} matches![/green]")
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Match Last.fm scrobbles to library tracks using local data.",
    )
    parser.add_argument("--user", default="darious1472", help="Last.fm username")
    parser.add_argument("--limit", type=int, default=200, help="Scrobbles to match")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute matches without writing to the DB",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing matches",
    )
    parser.add_argument(
        "--match-version",
        default="v1",
        help="Version label for this matching run",
    )
    parser.add_argument(
        "--fuzzy",
        action="store_true",
        help="Enable RapidFuzz title matching fallback",
    )
    parser.add_argument(
        "--fuzzy-title-threshold",
        type=int,
        default=92,
        help="Minimum RapidFuzz ratio for title matches",
    )
    parser.add_argument(
        "--store-candidates",
        action="store_true",
        help="Store candidate matches for review",
    )
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=5,
        help="Max candidates stored per scrobble",
    )
    parser.add_argument(
        "--review-threshold",
        type=float,
        default=0.85,
        help="Store candidates when top score is below this",
    )
    parser.add_argument(
        "--review-delta",
        type=float,
        default=0.05,
        help="Store candidates when top two scores are within this delta",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel worker threads for scoring",
    )
    parser.add_argument(
        "--auto-accept-threshold",
        type=float,
        default=0.95,
        help="Auto-accept when model score is above this threshold",
    )
    parser.add_argument(
        "--use-model",
        action="store_true",
        help="Use trained model when available",
    )
    parser.add_argument(
        "--train-model",
        action="store_true",
        help="Train and save the model using feedback, then exit",
    )
    parser.add_argument(
        "--model-name",
        default="default",
        help="Model name for storage and retrieval",
    )
    parser.add_argument(
        "--model-epochs",
        type=int,
        default=10,
        help="Training epochs for the model",
    )
    parser.add_argument(
        "--model-lr",
        type=float,
        default=0.1,
        help="Learning rate for the model",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        console.print("Interrupted.")


if __name__ == "__main__":
    main()
