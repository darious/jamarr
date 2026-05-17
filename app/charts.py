import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

from app.db import get_pool
from app.config import get_musicbrainz_root_url

logger = logging.getLogger(__name__)

CHART_URL = "https://www.officialcharts.com/charts/albums-chart/"

@dataclass
class ChartEntry:
    position: int
    title: str
    artist: str
    last_week: str
    peak: str
    weeks: str
    status: str
    release_mbid: str = ""
    release_group_mbid: str = ""
    cover_url: str = ""
    catalog_number: str = ""
    info_url: str = ""
    confidence: int = 0

class ChartScraper:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers={
            "User-Agent": "jamarr-chart/1.0",
        })

    async def close(self):
        await self.client.aclose()
        
    async def fetch_chart(self) -> List[ChartEntry]:
        logger.info("Fetching chart from %s", CHART_URL)
        try:
            resp = await self.client.get(CHART_URL)
            resp.raise_for_status()
            html = resp.text
            return self._parse_chart(html)
        except Exception as e:
            logger.error("Failed to fetch chart: %s", e)
            raise

    def _parse_chart(self, html: str) -> List[ChartEntry]:
        # Try Nuxt payload first
        payload = self._extract_nuxt_payload(html)
        if payload:
            return self._parse_chart_from_payload(payload)

        # Fallback to HTML parsing
        soup = BeautifulSoup(html, "html.parser")
        items = soup.select(".chart-positions__item, .chart-positions__list > *")
        if not items:
            items = soup.select(".chart-positions > *")

        entries = []
        for item in items:
            pos_text = self._select_text(item, [".chart-positions__position", ".position"])
            title = self._select_text(item, [".chart-positions__title", ".title", ".chart-positions__album", "h4"])
            artist = self._select_text(item, [".chart-positions__artist", ".artist", "h5"])
            
            if not pos_text or not title:
                continue
            
            # Script just normalizes, no int conversion check here for parsing flow
            # but we want robust numeric parsing for sorting later
            
            last_week, peak, weeks = self._extract_stats(item)
            status = self._extract_status(item)

            try:
                position_int = int(self._normalize_space(pos_text))
            except ValueError:
                continue

            entries.append(ChartEntry(
                position=position_int,
                title=self._normalize_space(title),
                artist=self._normalize_space(artist),
                last_week=self._normalize_space(last_week),
                peak=self._normalize_space(peak),
                weeks=self._normalize_space(weeks),
                status=status
            ))
        
        return entries

    def _extract_nuxt_payload(self, html: str) -> Optional[List]:
        scripts = re.findall(r"<script(?:[^>]*)>(.*?)</script[^>]*>", html, flags=re.DOTALL | re.IGNORECASE)
        candidates = [s.strip() for s in scripts if s.strip().startswith("[")]
        
        if not candidates:
            return None
            
        payload = max(candidates, key=len)
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            match = re.search(r"(\\[.*\\])", payload, flags=re.DOTALL)
            if not match:
                return None
            try:
                return json.loads(match.group(1))
            except Exception:
                return None

    def _resolve_payload(self, payload: list, value):
        # EXACT logic from scripts/chart.py
        # Handles boolean False (as int 0) by indexing into payload[0]
        # FIX: Explicitly check type to avoid boolean (subclass of int) triggering index lookup
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(payload):
            return payload[value]
        return value

    def _parse_chart_from_payload(self, payload: list) -> List[ChartEntry]:
        entries: List[ChartEntry] = []
        for obj in payload:
            if not isinstance(obj, dict):
                continue
            if not {"position", "title", "artist"}.issubset(obj.keys()):
                continue

            position = self._resolve_payload(payload, obj.get("position"))
            title = self._resolve_payload(payload, obj.get("title"))
            artist = self._resolve_payload(payload, obj.get("artist"))
            last_week = self._resolve_payload(payload, obj.get("lastWeek"))
            peak = self._resolve_payload(payload, obj.get("peak"))
            weeks = self._resolve_payload(payload, obj.get("weeks"))
            
            is_new = bool(self._resolve_payload(payload, obj.get("new")))
            is_reentry = bool(self._resolve_payload(payload, obj.get("reentry")))

            status = "steady"
            last_week_display = str(last_week) if last_week is not None else None

            if is_new:
                status = "new entry"
                last_week_display = "NEW"
            elif is_reentry:
                status = "reentry"
                last_week_display = "RE"
            else:
                try:
                    pos_num = int(position)
                    lw_num = int(last_week) if last_week is not None else None
                    if lw_num is not None:
                        if pos_num < lw_num:
                            status = "up"
                        elif pos_num > lw_num:
                            status = "down"
                except Exception:
                    pass

            info_url = self._resolve_payload(payload, obj.get("infoUrl"))
            
            entries.append(ChartEntry(
                position=self._normalize_space(str(position)),
                title=self._normalize_space(str(title)),
                artist=self._normalize_space(str(artist)),
                last_week=self._normalize_space(str(last_week_display)) if last_week_display is not None else "",
                peak=self._normalize_space(str(peak)) if peak is not None else "",
                weeks=self._normalize_space(str(weeks)) if weeks is not None else "",
                status=status,
                info_url=self._normalize_space(str(info_url)) if info_url else ""
            ))
            
        def _pos_key(entry: ChartEntry) -> int:
            try:
                return int(entry.position)
            except ValueError:
                return 10000

        entries.sort(key=_pos_key)
        return entries

    def _select_text(self, root, selectors: Iterable[str]) -> str:
        for selector in selectors:
            node = root.select_one(selector)
            if node:
                text = node.get_text(" ", strip=True)
                if text:
                    return text
        return ""

    def _normalize_space(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _extract_stats(self, item) -> Tuple[str, str, str]:
        stats_root = item.select_one(".chart-positions__stats, .chart-positions__stats-list")
        if not stats_root:
            return "", "", ""
        
        texts = [t for t in stats_root.stripped_strings]
        # Very naive parsing for HTML fallback
        lw = ""
        peak = ""
        weeks = ""
        
        joined = " ".join(texts).upper()
        if "LW" in joined:
             # regex extraction
             m = re.search(r"LW\s*([0-9]+|NEW|RE)", joined)
             if m:
                 lw = m.group(1)
        if "PEAK" in joined:
             m = re.search(r"PEAK\s*([0-9]+)", joined)
             if m:
                 peak = m.group(1)
        if "WEEKS" in joined or "WKS" in joined:
             m = re.search(r"(?:WEEKS|WKS)\s*([0-9]+)", joined)
             if m:
                 weeks = m.group(1)
             
        return lw, peak, weeks

    def _extract_status(self, item) -> str:
        # Simplified HTML status extraction
        text = item.get_text().upper()
        if "NEW ENTRY" in text:
            return "new entry"
        if "RE-ENTRY" in text:
            return "reentry"
        # Often represented by classes or icons in HTML, difficult to parse without specific selectors
        return "steady"


MB_API_URL = get_musicbrainz_root_url()

async def enrich_entries(entries: List[ChartEntry]):
    # Limit enrichment to top 100 to save time/API limits
    # User-Agent matching scripts/chart.py exactly is crucial for the Official Charts API
    headers = {"User-Agent": "jamarr-chart/1.0 (+https://www.officialcharts.com/)"}

    needs_enrichment = list(entries)

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:

        # Phase 1: Populate Catalog Numbers
        # Many chart entries have an info_url that returns JSON details when requested with Accept: application/json
        sem_cat = asyncio.Semaphore(10) # Restored to 10 as per script
        async def fetch_cat(entry: ChartEntry):
            if not entry.info_url:
                return
            async with sem_cat:
                try:
                    # Provide User-Agent explicitly here to be safe and Accept json
                    req_headers = {"Accept": "application/json"}
                    req_headers.update(headers)
                    resp = await client.get(entry.info_url, headers=req_headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        entry.catalog_number = _normalize_space(str(data.get("catNo", "")))
                except Exception as e:
                    logger.debug(f"Failed to fetch catalog number for {entry.title}: {e}")

        await asyncio.gather(*(fetch_cat(e) for e in needs_enrichment))

        # Phase 2: MB Lookup — track best Album and best non-Album separately;
        # prefer Album, fall back to other types (e.g. EP) only if no Album matches.
        sem_mb = asyncio.Semaphore(10) # Local MB can handle more
        async def fetch_mb(entry: ChartEntry):
            queries = _build_mb_queries(entry.artist, entry.title, entry.catalog_number)
            if not queries:
                 logger.warning(f"Chart enrich: no queries generated for '{entry.title}' - '{entry.artist}'")
                 return

            async with sem_mb:
                best_album = None
                best_other = None
                for query in queries:
                    try:
                        params = {"query": query, "fmt": "json", "limit": 25}
                        resp = await client.get(f"{MB_API_URL}/ws/2/release/", params=params)
                        if resp.status_code == 200:
                            data = resp.json()
                            for candidate in data.get("releases", []):
                                rg = candidate.get("release-group") or {}
                                primary_type = (rg.get("primary-type") or "").lower()
                                if primary_type == "single":
                                    continue
                                score = _score_candidate(entry, candidate)
                                hit = {
                                    "score": score,
                                    "id": candidate.get("id", ""),
                                    "rg_id": rg.get("id", ""),
                                }
                                if primary_type == "album" or not primary_type:
                                    if best_album is None or score > best_album["score"]:
                                        best_album = hit
                                else:
                                    if best_other is None or score > best_other["score"]:
                                        best_other = hit
                    except Exception as e:
                        logger.warning(f"Chart enrich: MB error for '{entry.title}' ({query}): {e}")
                        continue

                # Album chart: always prefer album when one matches; fall back to
                # EP/other only if no album candidate cleared the threshold.
                album_score = best_album["score"] if best_album else 0
                other_score = best_other["score"] if best_other else 0
                if best_album and album_score > 60:
                    best = best_album
                elif best_other and other_score > 75:
                    best = best_other
                else:
                    best = None
                if best:
                     entry.release_mbid = best["id"]
                     entry.release_group_mbid = best["rg_id"]
                     entry.confidence = best["score"]

        await asyncio.gather(*(fetch_mb(e) for e in needs_enrichment))

        # Phase 3: Release-group search fallback for entries still unmatched
        still_unmatched = [e for e in needs_enrichment if not e.release_group_mbid]
        if still_unmatched:
            logger.info(f"Chart enrich: {len(still_unmatched)} entries unmatched after release search, trying release-group search")

            async def fetch_rg(entry: ChartEntry):
                rg_queries = _build_rg_queries(entry.artist, entry.title)
                async with sem_mb:
                    best_album = None
                    best_other = None
                    for query in rg_queries:
                        try:
                            params = {"query": query, "fmt": "json", "limit": 25}
                            resp = await client.get(f"{MB_API_URL}/ws/2/release-group/", params=params)
                            if resp.status_code == 200:
                                data = resp.json()
                                for rg in data.get("release-groups", []):
                                    ptype = (rg.get("primary-type") or "").lower()
                                    if ptype == "single":
                                        continue
                                    score = _score_rg_candidate(entry, rg)
                                    hit = {"score": score, "rg_id": rg.get("id", "")}
                                    if ptype == "album" or not ptype:
                                        if best_album is None or score > best_album["score"]:
                                            best_album = hit
                                    else:
                                        if best_other is None or score > best_other["score"]:
                                            best_other = hit
                        except Exception as e:
                            logger.warning(f"Chart enrich: RG search error for '{entry.title}' ({query}): {e}")
                            continue

                    album_score = best_album["score"] if best_album else 0
                    other_score = best_other["score"] if best_other else 0
                    if best_album and album_score > 60:
                        best = best_album
                    elif best_other and other_score > 75:
                        best = best_other
                    else:
                        best = None

                    if best:
                        entry.release_group_mbid = best["rg_id"]
                        entry.confidence = best["score"]
                        logger.info(f"Chart enrich: RG fallback matched '{entry.title}' - '{entry.artist}' (score={best['score']})")
                    else:
                        logger.warning(
                            f"Chart enrich: no match for '{entry.title}' - '{entry.artist}' "
                            f"(best album={best_album['score'] if best_album else 'none'}, "
                            f"best other={best_other['score'] if best_other else 'none'})"
                        )

            await asyncio.gather(*(fetch_rg(e) for e in still_unmatched))

def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def _normalize_punctuation(text: str) -> str:
    text = text.strip()
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("…", "...")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[.]+$", "", text)
    return text.strip()

def _normalize_joiners(text: str) -> str:
    text = re.sub(r"\s&\s", " and ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s\+\s", " and ", text, flags=re.IGNORECASE)
    return text.strip() # Removed _normalize_space dep as it's just strip+re

def _strip_artist_noise(text: str) -> str:
    text = re.sub(r"\s+(feat\.?|featuring|ft\.?)\s+.+$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+with\s+.+$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+x\s+.+$", "", text, flags=re.IGNORECASE)
    return text.strip()

def _strip_title_suffixes(text: str) -> Tuple[str, str]:
    original = text
    text = re.sub(r"\s*[\(\[\{].*[\)\]\}]\s*$", "", text).strip()

    suffixes = [
        "deluxe", "remastered", "anniversary edition", "expanded edition",
        "special edition", "collector's edition", "platinum edition",
        "super deluxe", "tour collection",
    ]
    parts = re.split(r"\s-\s", text)
    if len(parts) > 1:
        last = parts[-1].casefold()
        if any(s in last for s in suffixes):
            text = " - ".join(parts[:-1]).strip()

    suffix = original[len(text) :].strip() if text != original else ""
    return text, suffix

def _symbol_title_variant(text: str) -> str:
    if not re.search(r"[+\-=/×÷]", text):
        return text
    text = text.replace("÷", "/").replace("×", "x")
    text = re.sub(r"\s*([+\-=/x])\s*", r"\1", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()

def _ellipsis_title_variant(text: str) -> str:
    if re.search(r"\b\d{4}\s*-\s*\d{4}\b", text) and " - " in text:
        left, right = text.split(" - ", 1)
        return f"{left}... {right}".strip()
    return text

def _colon_title_variant(text: str) -> str:
    if " - " in text:
        return text.replace(" - ", ": ")
    return text

def _alphanum_title_variant(text: str) -> str:
    if re.search(r"[A-Za-z]\\d[A-Za-z]", text):
        return re.sub(r"(?<=\\b[A-Za-z])1(?=[A-Za-z]\\b)", "I", text)
    return text

def _number_one_variants(text: str) -> List[str]:
    variants = []
    if re.search(r"(?i)NUMBER\s+1", text):
        variants.append(re.sub(r"(?i)NUMBER\s+1", "No. 1", text))
        variants.append(re.sub(r"(?i)NUMBER\s+1", "#1", text))
    if re.search(r"(?i)NUMBER\s+ONE", text):
        variants.append(re.sub(r"(?i)NUMBER\s+ONE", "No. 1", text))
        variants.append(re.sub(r"(?i)NUMBER\s+ONE", "#1", text))
    return variants

def generate_artist_variants(artist: str) -> List[str]:
    normalized = _normalize_punctuation(artist)
    variants = [normalized, _strip_artist_noise(normalized)]
    variants = [_normalize_joiners(v) for v in variants if v]
    return list(dict.fromkeys(v for v in variants if v))

def generate_title_variants(title: str, artist: str) -> List[str]:
    normalized = _normalize_punctuation(title)
    no_suffix, _ = _strip_title_suffixes(normalized)
    joiners = _normalize_joiners(no_suffix)
    loose = re.sub(r"[\"'`]", "", joiners)
    symbol_variant = _symbol_title_variant(no_suffix)
    ellipsis_variant = _ellipsis_title_variant(no_suffix)
    colon_variant = _colon_title_variant(no_suffix)
    alphanum_variant = _alphanum_title_variant(no_suffix)
    
    base_variants = [
        normalized, no_suffix, joiners, loose,
        symbol_variant, ellipsis_variant, colon_variant, alphanum_variant,
    ]

    variants = list(base_variants)
    for variant in list(base_variants):
        variants.extend(_number_one_variants(variant))

    artist_token = _normalize_punctuation(artist)
    if artist_token:
        upper_title = no_suffix.casefold()
        upper_artist = artist_token.casefold()
        if "best of" in upper_title and upper_artist not in upper_title:
            variants.append(f"{no_suffix} {artist_token}")
    return list(dict.fromkeys(v for v in variants if v))

def _normalize_for_scoring(text: str) -> str:
    text = _normalize_punctuation(text).casefold()
    text = _normalize_joiners(text).casefold()
    return text.strip()

def _barcode_candidates(catno: str) -> List[str]:
    if not catno:
        return []
    digits = re.sub(r"\D", "", catno)
    if len(digits) in {12, 13, 14}:
        return [digits]
    if len(digits) == 11:
        return [f"0{digits}"]
    return []

def _escape_lucene(text: str) -> str:
    """Escape special Lucene characters in a quoted-string context."""
    return text.replace('"', '\\"')


def _build_mb_queries(artist: str, title: str, catno: str) -> List[str]:
    artist_variants = generate_artist_variants(artist)
    title_variants = generate_title_variants(title, artist)
    queries = []

    barcodes = _barcode_candidates(catno)
    for barcode in barcodes:
        # High priority: exact barcode + fuzzy artist
        queries.append(f'barcode:"{barcode}" AND artist:"{_escape_lucene(artist_variants[0])}"')

    # Phase 1: quoted-phrase queries (most precise)
    for artist_variant in artist_variants:
        for title_variant in title_variants:
            queries.append(
                f'release:"{_escape_lucene(title_variant)}" AND artist:"{_escape_lucene(artist_variant)}"'
            )

    # Phase 2: unquoted token queries as fallback (broader, handles ALL-CAPS and punct differences)
    # Only add the primary title/artist pair to avoid combinatorial explosion
    primary_title = re.sub(r"[^\w\s]", " ", title_variants[0]).strip()
    primary_artist = re.sub(r"[^\w\s]", " ", artist_variants[0]).strip()
    if primary_title and primary_artist:
        queries.append(f"release:{primary_title.lower()} AND artist:{primary_artist.lower()}")

    return list(dict.fromkeys(queries))

def _score_candidate(entry: ChartEntry, candidate: dict) -> int:
    title = candidate.get("title") or ""
    artist_credit = candidate.get("artist-credit") or []
    artist_names = []
    for item in artist_credit:
        if isinstance(item, dict):
            artist = item.get("artist") or {}
            name = artist.get("name") or item.get("name")
            if name:
                artist_names.append(name)
    artist = " ".join(artist_names)
    
    score_title = fuzz.token_set_ratio(
        _normalize_for_scoring(entry.title),
        _normalize_for_scoring(title),
    )
    score_artist = fuzz.token_set_ratio(
        _normalize_for_scoring(entry.artist),
        _normalize_for_scoring(artist),
    )
    
    # Weighted score
    score = int((score_title * 0.6) + (score_artist * 0.3)) # Adjusted to match script roughly
    
    # Boosts matching script logic
    for barcode in _barcode_candidates(entry.catalog_number):
         if candidate.get("barcode") == barcode:
             score += 10
             
    country = candidate.get("country")
    if country in {"GB", "XW", "XE", "EU"}:
        score += 5
        
    if (candidate.get("status") or "").lower() == "official":
        score += 5

    return min(score, 100)

def _build_rg_queries(artist: str, title: str) -> List[str]:
    """Build Lucene queries for the release-group search endpoint."""
    artist_variants = generate_artist_variants(artist)
    title_variants = generate_title_variants(title, artist)
    queries = []

    for artist_variant in artist_variants:
        for title_variant in title_variants:
            queries.append(
                f'releasegroup:"{_escape_lucene(title_variant)}" AND artist:"{_escape_lucene(artist_variant)}"'
            )

    # Unquoted token fallback
    primary_title = re.sub(r"[^\w\s]", " ", title_variants[0]).strip()
    primary_artist = re.sub(r"[^\w\s]", " ", artist_variants[0]).strip()
    if primary_title and primary_artist:
        queries.append(f"releasegroup:{primary_title.lower()} AND artist:{primary_artist.lower()}")

    return list(dict.fromkeys(queries))


def _score_rg_candidate(entry: ChartEntry, rg: dict) -> int:
    """Score a release-group candidate against a chart entry."""
    title = rg.get("title") or ""
    artist_credit = rg.get("artist-credit") or []
    artist_names = []
    for item in artist_credit:
        if isinstance(item, dict):
            artist = item.get("artist") or {}
            name = artist.get("name") or item.get("name")
            if name:
                artist_names.append(name)
    artist = " ".join(artist_names)

    score_title = fuzz.token_set_ratio(
        _normalize_for_scoring(entry.title),
        _normalize_for_scoring(title),
    )
    score_artist = fuzz.token_set_ratio(
        _normalize_for_scoring(entry.artist),
        _normalize_for_scoring(artist),
    )

    score = int((score_title * 0.6) + (score_artist * 0.3))

    ptype = (rg.get("primary-type") or "").lower()
    if ptype == "album":
        score += 5

    return min(score, 100)


async def update_chart_db(entries: List[ChartEntry]):
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM chart_album")

            for e in entries:
                try:
                    pos_val = int(e.position)
                except ValueError:
                    continue

                await conn.execute("""
                    INSERT INTO chart_album
                    (position, title, artist, last_week, peak, weeks, status, release_mbid, release_group_mbid)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """, pos_val, e.title, e.artist, e.last_week, e.peak, e.weeks, e.status,
                     e.release_mbid or "", e.release_group_mbid or "")

    logger.info(f"Updated chart with {len(entries)} entries")

async def refresh_chart_task():
    scraper = ChartScraper()
    try:
        entries = await scraper.fetch_chart()
        logger.info(f"Chart refresh: scraped {len(entries)} entries")

        await enrich_entries(entries)

        unmatched = [e for e in entries if not e.release_group_mbid]
        if unmatched:
            logger.warning(
                f"Chart refresh: {len(unmatched)} entries have no MBID after all enrichment: "
                + ", ".join(f"'{e.title}'" for e in unmatched)
            )

        await update_chart_db(entries)
    finally:
        await scraper.close()
