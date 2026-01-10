"""
Last.fm scrobble matching logic.

Matches Last.fm scrobbles to library tracks using multiple strategies:
- MBID-based matching (highest confidence)
- Name-based matching (artist + title + album)
- Fuzzy matching (PostgreSQL trigram search)
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import asyncpg
from rapidfuzz import fuzz

# Benign suffix tokens that can be stripped from titles
BENIGN_SUFFIX_TOKENS = {
    "remaster", "remastered", "mono", "stereo", "edit", "radio", "vocal",
    "explicit", "clean", "bonus", "deluxe", "expanded", "anniversary",
    "reissue", "version", "single", "original", "acoustic", "live",
    "session", "sessions", "mix", "album", "remix",
}


@lru_cache(maxsize=200000)
def _normalize_basic(value: Optional[str]) -> str:
    """Normalize text by removing accents, converting to lowercase, and standardizing separators."""
    if not value:
        return ""
    # Remove accents
    value = "".join(
        c for c in unicodedata.normalize("NFKD", value) 
        if not unicodedata.combining(c)
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

@lru_cache(maxsize=200000)
def _strip_benign_suffix(title: str) -> str:
    """Strip benign suffixes like (Remastered) from titles."""
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


def _strip_leading_article(value: str) -> str:
    """Strip leading articles (the, a, an) from names."""
    for article in ("the ", "a ", "an "):
        if value.startswith(article):
            return value[len(article):].strip()
    return value


@lru_cache(maxsize=200000)
def normalize_title(value: Optional[str]) -> str:
    """Normalize track title for matching."""
    if not value:
        return ""
    # Strip track numbers
    stripped = re.sub(r"^\s*\d{1,3}\s*[-.\u2013]\s*", "", value)
    stripped = re.sub(r"^\s*\d{1,3}\s+", "", stripped)
    # Strip artist prefix (e.g., "Artist - Title")
    stripped = re.sub(r"^\s*[^-]{1,80}\s-\s+", "", stripped)
    # Strip benign suffixes
    stripped = _strip_benign_suffix(stripped)
    # Replace special characters
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
    # Strip featuring artists
    stripped = re.sub(
        r"\s*[\(\[]\s*(feat\.?|featuring|ft\.?)\s+[^\)\]]+[\)\]]\s*$",
        "", stripped, flags=re.IGNORECASE
    )
    stripped = re.sub(
        r"\s*[\(\[]\s*with\s+[^\)\]]+[\)\]]\s*$",
        "", stripped, flags=re.IGNORECASE
    )
    stripped = re.sub(
        r"\s+(feat\.?|featuring|ft\.?)\s+.+$",
        "", stripped, flags=re.IGNORECASE
    )
    stripped = re.sub(r"\s+with\s+.+$", "", stripped, flags=re.IGNORECASE)
    # Strip version suffixes
    stripped = re.sub(
        r"\s*-?\s*(radio edit|edit|remix|acoustic|version|mix|live|mono|stereo|"
        r"12\" version|12 inch version|single version|album version)\s*$",
        "", stripped, flags=re.IGNORECASE
    )
    stripped = stripped.replace("’", "'")
    return _normalize_basic(stripped)


@lru_cache(maxsize=100000)
def normalize_artist(value: Optional[str]) -> str:
    """Normalize artist name for matching."""
    name = _normalize_basic(value)
    # Handle special cases
    aliases = {
        "p nk": "pink",
        "p!nk": "pink",
        "r e m": "rem",
        "a ha": "aha",
        "ac dc": "acdc",
    }
    if name in aliases:
        return aliases[name]
    # Handle single-letter artist names (e.g., "R E M" -> "rem")
    tokens = name.split()
    if tokens and all(len(token) == 1 for token in tokens):
        return "".join(tokens)
    return name


@lru_cache(maxsize=200000)
def normalize_name(value: Optional[str]) -> str:
    """Normalize generic name (album, etc.) for matching."""
    return _normalize_basic(value)


@lru_cache(maxsize=100000)
def split_artist_names(value: Optional[str]) -> List[str]:
    """Split multi-artist string into individual artist names."""
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
    """Extract featured artist names from track title."""
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
    """Extract all artist name parts from a scrobble (main artist + featured)."""
    parts = []
    parts.extend(split_artist_names(scrobble["artist_name"]))
    parts.extend(extract_featured_artists(scrobble["track_name"]))
    return list(dict.fromkeys([p for p in parts if p]))


def _title_variants(normalized_title: str) -> List[str]:
    """Generate title variants (with/without leading article)."""
    variants = {normalized_title}
    stripped = _strip_leading_article(normalized_title)
    if stripped:
        variants.add(stripped)
    return list(variants)


def build_cache_key(scrobble: asyncpg.Record) -> Optional[str]:
    """Build cache key for scrobble to enable fast duplicate lookup."""
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


def _is_various(value: Optional[str]) -> bool:
    """Check if album artist is 'Various Artists'."""
    if not value:
        return False
    return normalize_name(value) in ("various artists", "various", "va")


def _album_artist_relation(
    scrobble_artist: str, track_artist: str, album_artist: str
) -> Tuple[float, str, int]:
    """Score album artist relationship."""
    if not album_artist:
        return 0.0, "", 0
    if album_artist in ("various artists", "various", "va"):
        return -0.4, "album_artist_various", -1
    if album_artist == scrobble_artist or album_artist == track_artist:
        return 0.3, "album_artist_match", 1
    return -0.1, "album_artist_mismatch", -1


def _release_type_adjust(release_type: Optional[str]) -> Tuple[float, str, int]:
    """Adjust score based on release type."""
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


def _get_artist_names(candidate: asyncpg.Record) -> List[str]:
    """Extract artist names from candidate track record."""
    try:
        names = candidate["artist_names"]
    except KeyError:
        return []
    if not names:
        return []
    return [normalize_name(name) for name in names if name]


def score_candidate(
    scrobble: asyncpg.Record, candidate: asyncpg.Record
) -> Tuple[float, str, int, int]:
    """
    Score a candidate track match for a scrobble.
    
    Returns: (score, reason, album_artist_rank, release_type_rank)
    """
    score = 0.0
    reasons: List[str] = []

    artist_parts = scrobble_artist_parts(scrobble)
    
    # MBID matching
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

    # Name matching
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
    
    # Sanity check: title must match for high scores
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
    
    # Fuzzy title check
    if not title_match and sc_title and tr_title:
        ratio = fuzz.token_set_ratio(sc_title, tr_title)
        if ratio >= 80:
            title_match = True
            reasons.append(f"fuzzy_title_{ratio}")
    
    # Penalize if title doesn't match
    if not title_match:
        if score > 0.6:
            score = 0.6
            reasons.append("title_mismatch_penalty")
            
    # Validate Track MBID
    if "track_mbid" in reasons and not title_match:
        score = 0.6
        reasons.append("mbid_title_mismatch")

    return score, "+".join(reasons), aa_rank, rt_rank


def classify_method(score: float, reason: str) -> str:
    """Classify match method based on score and reason."""
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
    """Determine if a match should be accepted based on method and score."""
    if method == "mbid_track":
        return True
    if method == "mbid_artist_release":
        return score >= 0.7
    if method == "name_artist_album":
        return score >= 0.7
    if method == "name_artist_title":
        return score >= 0.8
    return False
