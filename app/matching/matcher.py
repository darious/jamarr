"""
Last.fm scrobble matcher - orchestrates the matching process.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import asyncpg
from rapidfuzz import fuzz

from app.matching import (
    accept_match,
    base_titles_compatible,
    classify_method,
    extract_featured_artist_raw_parts,
    normalize_artist,
    normalize_name,
    normalize_title,
    scrobble_artist_parts,
    score_candidate,
    _title_variants,
    _regex_normalize,
    raw_title,
)


METHOD_RANK = {
    "mbid_track": 3,
    "mbid_artist_release": 2,
    "name_artist_album": 1,
    "name_artist_title": 0,
    "name_partial": -1,
}


async def preload_artist_lookup(conn: asyncpg.Connection) -> Dict[str, str]:
    """Preload artist name -> MBID lookup.

    Two artists can share a normalised name; ordering by MBID makes the one
    that wins stable between runs (it is still an arbitrary pick).
    """
    rows = await conn.fetch("SELECT mbid, name FROM artist ORDER BY mbid")
    lookup: Dict[str, str] = {}
    for row in rows:
        from app.matching import normalize_artist
        name = normalize_artist(row["name"])
        if name and name not in lookup:
            lookup[name] = row["mbid"]
    return lookup


async def preload_skip_artists(conn: asyncpg.Connection) -> set[str]:
    """Load artist skip list from database."""
    rows = await conn.fetch("SELECT artist_name FROM lastfm_skip_artist")
    return {row["artist_name"] for row in rows}


async def preload_tracks(
    conn: asyncpg.Connection,
    scrobbles: List[asyncpg.Record],
    artist_lookup: Dict[str, str],
) -> Dict[str, Dict[Any, List[asyncpg.Record]]]:
    """
    Preload all potential track candidates for a batch of scrobbles.
    
    Returns indexes for fast lookup by various keys.
    """
    track_mbids = {s["track_mbid"] for s in scrobbles if s["track_mbid"]}
    release_mbids = {s["album_mbid"] for s in scrobbles if s["album_mbid"]}
    artist_mbids = {s["artist_mbid"] for s in scrobbles if s["artist_mbid"]}
    
    # Add artist MBIDs from artist lookup
    for s in scrobbles:
        if s["artist_mbid"]:
            continue
        for name in _artist_keys(s):
            mbid = artist_lookup.get(normalize_artist(name))
            if mbid:
                artist_mbids.add(mbid)
    
    # Collect artist names
    artist_names = {normalize_artist(s["artist_name"]) for s in scrobbles if s["artist_name"]}
    artist_names.update({s["artist_name"].strip().lower() for s in scrobbles if s["artist_name"]})
    artist_names.update({_regex_normalize(s["artist_name"]) for s in scrobbles if s["artist_name"]})
    for s in scrobbles:
        for part in scrobble_artist_parts(s):
            artist_names.add(part)
            artist_names.add(part.strip().lower())
        for part in extract_featured_artist_raw_parts(s["track_name"]):
            artist_names.add(part.strip().lower())
            artist_names.add(_regex_normalize(part))
    
    # Collect title names
    title_names = {normalize_title(s["track_name"]) for s in scrobbles if s["track_name"]}
    title_names.update({s["track_name"].strip().lower() for s in scrobbles if s["track_name"]})
    title_names.update({_regex_normalize(s["track_name"]) for s in scrobbles if s["track_name"]})
    for name in list(title_names):
        if name:
            title_names.update(_title_variants(name))
    
    # Collect album names
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

    # Query by track MBID
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

    # Query by release + artist MBID
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

    # Query by release MBID
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

    # Query by artist + title
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
                    OR lower(replace(t.title, chr(8217), chr(39))) = ANY($3::text[])
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

    # Query by title + album
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

    # Query by artist
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
            """,
            list(artist_names),
        )
        for row in rows:
            key = normalize_artist(row["artist"])
            indexes["artist"].setdefault(key, []).append(row)

    # Query by track_artist join
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

    # Query by artist MBID
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


def _artist_keys(scrobble: asyncpg.Record) -> List[str]:
    """Artist names to look a scrobble up by: the full name first, then the
    parts split_artist_names and featured credits give. The full name has to
    stay: "Mumford & Sons" splits into "mumford" and "sons", neither of which
    is an artist."""
    keys = [normalize_artist(scrobble["artist_name"]), *scrobble_artist_parts(scrobble)]
    return [k for k in dict.fromkeys(keys) if k]


def _collect_candidates(
    scrobble: asyncpg.Record,
    indexes: Dict[str, Dict[Any, List[asyncpg.Record]]],
    artist_lookup: Dict[str, str],
) -> List[asyncpg.Record]:
    """Collect all potential candidate tracks for a scrobble."""
    from rapidfuzz import fuzz
    
    candidates: List[asyncpg.Record] = []
    artist_keys = _artist_keys(scrobble)

    # Try MBID matches first
    if scrobble["track_mbid"]:
        candidates.extend(indexes["track_mbid"].get(scrobble["track_mbid"], []))
    if scrobble["artist_mbid"]:
        candidates.extend(indexes["artist_mbid"].get(scrobble["artist_mbid"], []))
    if scrobble["album_mbid"]:
        candidates.extend(indexes["release"].get(scrobble["album_mbid"], []))
    
    # Try artist-based matches
    for artist_key in artist_keys:
        artist_mbid = artist_lookup.get(artist_key)
        if artist_mbid:
            candidates.extend(indexes["artist_mbid"].get(artist_mbid, []))
    
    # Try release + artist MBID
    if scrobble["album_mbid"] and scrobble["artist_mbid"]:
        key = (scrobble["album_mbid"], scrobble["artist_mbid"])
        candidates.extend(indexes["release_artist"].get(key, []))
    
    # Try artist + title
    if artist_keys and scrobble["track_name"]:
        title_key = normalize_title(scrobble["track_name"])
        for variant in _title_variants(title_key):
            for artist_key in artist_keys:
                key = (artist_key, variant)
                candidates.extend(indexes["artist_title"].get(key, []))
                candidates.extend(indexes["artist_any_title"].get(key, []))
    
    # Try title + album
    if scrobble["track_name"] and scrobble["album_name"]:
        title_key = normalize_title(scrobble["track_name"])
        album_key = normalize_name(scrobble["album_name"])
        for variant in _title_variants(title_key):
            key = (variant, album_key)
            candidates.extend(indexes["title_album"].get(key, []))
    
    if candidates:
        return candidates
    
    # Fallback: broader artist-only candidates
    for artist_key in artist_keys:
        candidates.extend(indexes["artist"].get(artist_key, []))
        candidates.extend(indexes["artist_any"].get(artist_key, []))
    
    if not candidates:
        return candidates
    
    # Gate fallback candidates by fuzzy title
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


def _build_artist_volume(scrobbles: List[asyncpg.Record]) -> Dict[str, int]:
    """Build artist play count for volume-based thresholds."""
    counts: Dict[str, int] = {}
    for scrobble in scrobbles:
        name = normalize_artist(scrobble["artist_name"])
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    return counts


def match_scrobble(
    scrobble: asyncpg.Record,
    indexes: Dict[str, Dict[Any, List[asyncpg.Record]]],
    artist_lookup: Dict[str, str],
    artist_volume: Dict[str, int],
    skip_artists: set[str],
    fuzzy: bool = True,
    fuzzy_title_threshold: int = 92,
) -> Optional[Tuple[int, float, str, str]]:
    """
    Match a single scrobble to a library track.
    
    Returns: (track_id, score, method, reason) or None if no match
    """
    sc_artist = normalize_artist(scrobble["artist_name"])
    if sc_artist in skip_artists:
        return None

    candidates = _collect_candidates(scrobble, indexes, artist_lookup)
    if not candidates:
        return None

    # Deduplicate candidates
    seen_ids = set()
    uniq_candidates: List[asyncpg.Record] = []
    for candidate in candidates:
        if candidate["id"] in seen_ids:
            continue
        seen_ids.add(candidate["id"])
        uniq_candidates.append(candidate)

    sc_title = normalize_title(scrobble["track_name"])
    sc_album = normalize_name(scrobble["album_name"])

    # Check for non-various album matches
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

    # Score candidates. The winner is the maximum of a total sort key, so the
    # result never depends on the order candidates arrived in (SQL row order
    # and set iteration both vary between runs).
    best: Optional[Tuple[int, float, str, str]] = None
    best_key: Optional[Tuple[float, int, int, int, int, int, int]] = None
    sc_raw_title = raw_title(scrobble["track_name"])
    for candidate in uniq_candidates:
        tr_album_artist = normalize_name(candidate["album_artist"])
        # Skip various artists if we have better matches
        if album_match_exists and tr_album_artist in ("various artists", "various", "va"):
            continue
        if non_various_title_match_exists and tr_album_artist in ("various artists", "various", "va"):
            continue
        
        score, reason, aa_rank, rt_rank = score_candidate(scrobble, candidate)
        method = classify_method(score, reason)
        
        # Check if match is acceptable
        if not accept_match(method, score, reason):
            continue
        
        title_match = "track_name" in reason or "fuzzy_title" in reason
        if not title_match:
            continue
        
        # Volume-based threshold for fuzzy matches
        artist_count = artist_volume.get(sc_artist, 0)
        title_gate = 0.9 if artist_count >= 50 else 0.85
        if "fuzzy_title" in reason and score < title_gate:
            continue

        # Higher score first (rounded, so float noise doesn't decide), then an
        # exact title over a fuzzy one, then method, album artist relation and
        # release type. Of candidates still tied, one whose raw title equals
        # the scrobble's wins (normalize_title drops "(Acoustic Version)", so
        # "Goodbye My Lover" otherwise ties with its acoustic bonus track); the
        # lowest track id settles the rest.
        key = (
            round(score, 2),
            1 if "track_name" in reason else 0,
            METHOD_RANK.get(method, -1),
            aa_rank,
            rt_rank,
            1 if raw_title(candidate["title"]) == sc_raw_title else 0,
            -candidate["id"],
        )
        if best_key is None or key > best_key:
            best_key = key
            best = (candidate["id"], score, method, reason)

    if not best:
        if fuzzy:
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
                    if not base_titles_compatible(
                        scrobble["track_name"], candidate["title"]
                    ):
                        continue
                    if (
                        not best_fuzzy
                        or similarity > best_fuzzy[1]
                        or (similarity == best_fuzzy[1] and candidate["id"] < best_fuzzy[0])
                    ):
                        best_fuzzy = (candidate["id"], similarity)
                if best_fuzzy:
                    return (
                        best_fuzzy[0],
                        0.6,
                        "fuzzy_title",
                        f"fuzzy_title_{best_fuzzy[1]}",
                    )
        return None
    
    return best


MATCH_BATCH_SIZE = 1000

UPSERT_MATCH_SQL = """
INSERT INTO lastfm_scrobble_match (scrobble_id, track_id, match_score, match_method, match_reason, cache_key)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (scrobble_id) DO UPDATE SET
    track_id = EXCLUDED.track_id,
    match_score = EXCLUDED.match_score,
    match_method = EXCLUDED.match_method,
    match_reason = EXCLUDED.match_reason,
    cache_key = EXCLUDED.cache_key,
    matched_at = NOW()
"""


async def match_and_store(
    conn: asyncpg.Connection,
    scrobbles: List[asyncpg.Record],
    *,
    fuzzy: bool = True,
    fuzzy_title_threshold: int = 92,
    log: Optional[Callable[[str], None]] = None,
    batch_size: int = MATCH_BATCH_SIZE,
) -> Tuple[int, int]:
    """Match scrobbles in batches and upsert the results.

    Scrobbles are processed in the order given (the sync passes newest
    first). Each batch first reuses matches stored for the same cache key by
    earlier batches or syncs, then matches the rest. A last pass gives a
    scrobble nothing matched a track that other scrobbles of the same Last.fm
    track MBID were matched to (see _match_by_shared_track_mbid). Returns
    (matched, unmatched).
    """
    from app.matching import build_cache_key

    matched = 0
    unmatched = 0
    artist_lookup = await preload_artist_lookup(conn)
    skip_artists = await preload_skip_artists(conn)
    no_match: List[asyncpg.Record] = []

    for i in range(0, len(scrobbles), batch_size):
        batch = scrobbles[i:i + batch_size]
        if log:
            log(f"Processing batch {i // batch_size + 1} ({len(batch)} scrobbles)...")

        indexes = await preload_tracks(conn, batch, artist_lookup)
        artist_volume = _build_artist_volume(batch)

        cache_keys = [k for k in (build_cache_key(s) for s in batch) if k]
        cached_matches: Dict[str, asyncpg.Record] = {}
        if cache_keys:
            cache_rows = await conn.fetch(
                """
                SELECT cache_key, track_id, match_score, match_method, match_reason
                FROM lastfm_scrobble_match
                WHERE cache_key = ANY($1::text[])
                ORDER BY matched_at DESC, id DESC
                """,
                cache_keys,
            )
            # Most recent match per cache key; id settles rows written together.
            for row in cache_rows:
                cached_matches.setdefault(row["cache_key"], row)

        match_rows = []
        for scrobble in batch:
            cache_key = build_cache_key(scrobble)
            cached = cached_matches.get(cache_key) if cache_key else None
            if cached is not None:
                match_rows.append((
                    scrobble["id"], cached["track_id"], cached["match_score"],
                    cached["match_method"], cached["match_reason"], cache_key,
                ))
                matched += 1
                continue

            result = match_scrobble(
                scrobble,
                indexes,
                artist_lookup,
                artist_volume,
                skip_artists,
                fuzzy=fuzzy,
                fuzzy_title_threshold=fuzzy_title_threshold,
            )
            if result:
                track_id, score, method, reason = result
                match_rows.append((scrobble["id"], track_id, score, method, reason, cache_key))
                matched += 1
            else:
                unmatched += 1
                if scrobble["track_mbid"] and normalize_artist(scrobble["artist_name"]) not in skip_artists:
                    no_match.append(scrobble)

        if match_rows:
            await conn.executemany(
                UPSERT_MATCH_SQL,
                match_rows,
            )

    shared = await _match_by_shared_track_mbid(conn, no_match)
    return matched + shared, unmatched - shared


SHARED_MBID_METHOD = "track_mbid_shared"


async def _match_by_shared_track_mbid(conn: asyncpg.Connection, scrobbles: List[asyncpg.Record]) -> int:
    """Match scrobbles nothing else matched to the track that most other
    scrobbles with the same Last.fm track MBID are matched to.

    The MBID names one recording, so this catches artist spellings the
    matcher can't link ("30 Seconds to Mars" vs "Thirty Seconds to Mars",
    "Koяn"). It runs only after the matcher found nothing: Last.fm gives
    every edition of an album the same track MBID, so it must never
    override a match that the album could decide (issue #366). The rows get
    no cache key, so they are never copied on, and their own method, so they
    never serve as a source. Returns the number matched.
    """
    if not scrobbles:
        return 0
    rows = await conn.fetch(
        """
        SELECT s.track_mbid, m.track_id, count(*) AS n, max(m.match_score) AS score
        FROM lastfm_scrobble_match m
        JOIN lastfm_scrobble s ON s.id = m.scrobble_id
        WHERE s.track_mbid = ANY($1::text[]) AND m.match_method <> $2
        GROUP BY s.track_mbid, m.track_id
        ORDER BY s.track_mbid, n DESC, m.track_id
        """,
        list({sc["track_mbid"] for sc in scrobbles}),
        SHARED_MBID_METHOD,
    )
    best: Dict[str, asyncpg.Record] = {}
    for row in rows:
        best.setdefault(row["track_mbid"], row)
    match_rows = [
        (sc["id"], best[sc["track_mbid"]]["track_id"], best[sc["track_mbid"]]["score"],
         SHARED_MBID_METHOD, SHARED_MBID_METHOD, None)
        for sc in scrobbles if sc["track_mbid"] in best
    ]
    if match_rows:
        await conn.executemany(
            UPSERT_MATCH_SQL,
            match_rows,
        )
    return len(match_rows)
