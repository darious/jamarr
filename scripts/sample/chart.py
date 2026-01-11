#!/usr/bin/env python3
"""
Scrape the Official Charts albums chart and print a table.

Usage:
  python3 scripts/chart.py
  python3 scripts/chart.py --limit 50
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass
from typing import Iterable

import httpx
from bs4 import BeautifulSoup
from rapidfuzz import fuzz
from rich.console import Console
from rich.table import Table


CHART_URL = "https://www.officialcharts.com/charts/albums-chart/"
MB_BASE_URL = "http://192.168.1.105:5000"
DEFAULT_LIMIT = 20


@dataclass
class ChartEntry:
    position: str
    title: str
    artist: str
    last_week: str
    peak: str
    weeks: str
    status: str
    catalog_number: str = ""
    info_url: str = ""
    release_mbid: str = ""
    release_group_mbid: str = ""
    confidence: int = 0


def fetch_chart_html(url: str) -> str:
    headers = {
        "User-Agent": "jamarr-chart/1.0 (+https://www.officialcharts.com/)",
        "Accept": "text/html,application/xhtml+xml",
    }
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        return response.text


def _select_text(root, selectors: Iterable[str]) -> str:
    for selector in selectors:
        node = root.select_one(selector)
        if node:
            text = node.get_text(" ", strip=True)
            if text:
                return text
    return ""


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
    return _normalize_space(text)


def _strip_artist_noise(text: str) -> str:
    text = re.sub(r"\s+(feat\.?|featuring|ft\.?)\s+.+$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+with\s+.+$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+x\s+.+$", "", text, flags=re.IGNORECASE)
    return text.strip()


def _strip_title_suffixes(text: str) -> tuple[str, str]:
    original = text
    text = re.sub(r"\s*[\(\[\{].*[\)\]\}]\s*$", "", text).strip()

    suffixes = [
        "deluxe",
        "remastered",
        "anniversary edition",
        "expanded edition",
        "special edition",
        "collector's edition",
        "platinum edition",
        "super deluxe",
        "tour collection",
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
    return _normalize_space(text)


def _ellipsis_title_variant(text: str) -> str:
    if re.search(r"\b\d{4}\s*-\s*\d{4}\b", text) and " - " in text:
        left, right = text.split(" - ", 1)
        return _normalize_space(f"{left}... {right}")
    return text


def _colon_title_variant(text: str) -> str:
    if " - " in text:
        return text.replace(" - ", ": ")
    return text


def _alphanum_title_variant(text: str) -> str:
    if re.search(r"[A-Za-z]\\d[A-Za-z]", text):
        return re.sub(r"(?<=\\b[A-Za-z])1(?=[A-Za-z]\\b)", "I", text)
    return text


def _number_one_variants(text: str) -> list[str]:
    variants = []
    if re.search(r"(?i)NUMBER\s+1", text):
        variants.append(re.sub(r"(?i)NUMBER\s+1", "No. 1", text))
        variants.append(re.sub(r"(?i)NUMBER\s+1", "#1", text))
    if re.search(r"(?i)NUMBER\s+ONE", text):
        variants.append(re.sub(r"(?i)NUMBER\s+ONE", "No. 1", text))
        variants.append(re.sub(r"(?i)NUMBER\s+ONE", "#1", text))
    return variants


def generate_artist_variants(artist: str) -> list[str]:
    normalized = _normalize_punctuation(artist)
    variants = [normalized, _strip_artist_noise(normalized)]
    variants = [_normalize_joiners(v) for v in variants if v]
    return list(dict.fromkeys(v for v in variants if v))


def generate_title_variants(title: str, artist: str) -> list[str]:
    normalized = _normalize_punctuation(title)
    no_suffix, _ = _strip_title_suffixes(normalized)
    joiners = _normalize_joiners(no_suffix)
    loose = re.sub(r"[\"'`]", "", joiners)
    symbol_variant = _symbol_title_variant(no_suffix)
    ellipsis_variant = _ellipsis_title_variant(no_suffix)
    colon_variant = _colon_title_variant(no_suffix)
    alphanum_variant = _alphanum_title_variant(no_suffix)
    # number_one_variants = _number_one_variants(no_suffix)
    base_variants = [
        normalized,
        no_suffix,
        joiners,
        loose,
        symbol_variant,
        ellipsis_variant,
        colon_variant,
        alphanum_variant,
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
    return text


def _parse_stat_texts(texts: list[str]) -> dict[str, str]:
    stats: dict[str, str] = {}
    label_map = {
        "LW": "last_week",
        "LAST WEEK": "last_week",
        "PEAK": "peak",
        "PEAK POSITION": "peak",
        "WKS": "weeks",
        "WEEKS": "weeks",
        "WEEKS ON CHART": "weeks",
    }

    upper_texts = [_normalize_space(t).upper() for t in texts if t.strip()]
    for idx, token in enumerate(upper_texts):
        if token in label_map:
            value = ""
            if idx + 1 < len(upper_texts):
                value = upper_texts[idx + 1]
            stats[label_map[token]] = value

    joined = " ".join(upper_texts)
    patterns = {
        "last_week": r"\bLW\b\s*([0-9]+|NEW|RE-ENTRY|REENTRY|--|-)\b",
        "peak": r"\bPEAK\b\s*([0-9]+|--|-)\b",
        "weeks": r"\bWKS\b\s*([0-9]+|--|-)\b|\bWEEKS\b\s*([0-9]+|--|-)\b",
    }
    for key, pattern in patterns.items():
        if key in stats and stats[key]:
            continue
        match = re.search(pattern, joined)
        if match:
            stats[key] = next(g for g in match.groups() if g)
    return stats


def _extract_stats(item) -> tuple[str, str, str]:
    stats_root = item.select_one(
        ".chart-positions__stats, .chart-positions__stats-list, .chart-positions__stats-items, .chart-stats"
    )
    texts = []
    if stats_root:
        texts = [t for t in stats_root.stripped_strings if t.strip()]
    stats = _parse_stat_texts(texts)

    last_week = stats.get("last_week", "")
    peak = stats.get("peak", "")
    weeks = stats.get("weeks", "")
    return last_week, peak, weeks


def _extract_status(item) -> str:
    status_candidates = item.select(
        ".chart-positions__status, .chart-positions__status-icon, "
        ".chart-positions__movement, .chart-positions__trend, .chart-positions__status-text"
    )
    statuses = []
    for node in status_candidates:
        classes = " ".join(node.get("class", []))
        text = _normalize_space(node.get_text(" ", strip=True)).upper()
        statuses.append((classes, text))

    for classes, text in statuses:
        if "RE-ENTRY" in text or "REENTRY" in text or "reentry" in classes or "re-entry" in classes:
            return "reentry"
        if "NEW" in text or "new" in classes:
            return "new entry"
        if "down" in classes or "DOWN" in text:
            return "down"
        if "up" in classes or "UP" in text:
            return "up"

    if item.select_one(".chart-positions__reentry"):
        return "reentry"
    if item.select_one(".chart-positions__new"):
        return "new entry"
    return "steady"


def _extract_nuxt_payload(html: str) -> list | None:
    scripts = re.findall(r"<script(?:[^>]*)>(.*?)</script>", html, flags=re.DOTALL | re.IGNORECASE)
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
        except json.JSONDecodeError:
            return None


def _resolve_payload(payload: list, value):
    if isinstance(value, int) and 0 <= value < len(payload):
        return payload[value]
    return value


def _parse_chart_from_payload(payload: list) -> list[ChartEntry]:
    entries: list[ChartEntry] = []
    for obj in payload:
        if not isinstance(obj, dict):
            continue
        if not {"position", "title", "artist", "lastWeek", "peak", "weeks", "new", "reentry"}.issubset(obj):
            continue

        position = _resolve_payload(payload, obj["position"])
        title = _resolve_payload(payload, obj["title"])
        artist = _resolve_payload(payload, obj["artist"])
        last_week = _resolve_payload(payload, obj["lastWeek"])
        peak = _resolve_payload(payload, obj["peak"])
        weeks = _resolve_payload(payload, obj["weeks"])
        is_new = bool(_resolve_payload(payload, obj["new"]))
        is_reentry = bool(_resolve_payload(payload, obj["reentry"]))

        if is_new:
            status = "new entry"
            last_week_display = "NEW"
        elif is_reentry:
            status = "reentry"
            last_week_display = "RE"
        else:
            status = "steady"
            last_week_display = last_week

        if status == "steady":
            try:
                pos_num = int(position)
                lw_num = int(last_week_display) if last_week_display is not None else None
            except (TypeError, ValueError):
                pos_num = None
                lw_num = None
            if lw_num is not None:
                if pos_num < lw_num:
                    status = "up"
                elif pos_num > lw_num:
                    status = "down"

        info_url = _resolve_payload(payload, obj.get("infoUrl"))
        entries.append(
            ChartEntry(
                position=_normalize_space(str(position)),
                title=_normalize_space(str(title)),
                artist=_normalize_space(str(artist)),
                last_week=_normalize_space(str(last_week_display)) if last_week_display is not None else "",
                peak=_normalize_space(str(peak)) if peak is not None else "",
                weeks=_normalize_space(str(weeks)) if weeks is not None else "",
                status=status,
                info_url=_normalize_space(str(info_url)) if info_url else "",
            )
        )

    def _pos_key(entry: ChartEntry) -> int:
        try:
            return int(entry.position)
        except ValueError:
            return 10_000

    entries.sort(key=_pos_key)
    return entries


def parse_chart(html: str) -> list[ChartEntry]:
    payload = _extract_nuxt_payload(html)
    if payload:
        entries = _parse_chart_from_payload(payload)
        if entries:
            return entries

    soup = BeautifulSoup(html, "html.parser")
    items = soup.select(".chart-positions__item, .chart-positions__list > *")
    if not items:
        items = soup.select(".chart-positions > *")

    entries: list[ChartEntry] = []
    for item in items:
        position = _select_text(
            item,
            [
                ".chart-positions__position",
                ".chart-positions__position-number",
                ".position",
            ],
        )
        title = _select_text(
            item,
            [
                ".chart-positions__title",
                ".title",
                ".chart-positions__album",
                "h4",
            ],
        )
        artist = _select_text(
            item,
            [
                ".chart-positions__artist",
                ".artist",
                ".chart-positions__subtitle",
                "h5",
            ],
        )

        if not position or not title:
            continue

        last_week, peak, weeks = _extract_stats(item)
        status = _extract_status(item)
        entries.append(
            ChartEntry(
                position=_normalize_space(position),
                title=_normalize_space(title),
                artist=_normalize_space(artist),
                last_week=_normalize_space(last_week),
                peak=_normalize_space(peak),
                weeks=_normalize_space(weeks),
                status=status,
            )
        )

    return entries


def render_table(entries: list[ChartEntry]) -> None:
    table = Table(title="Official Charts - Albums")
    table.add_column("Pos", justify="right")
    table.add_column("Album")
    table.add_column("Artist")
    table.add_column("Cat No")
    table.add_column("LW", justify="right")
    table.add_column("Peak", justify="right")
    table.add_column("Weeks", justify="right")
    table.add_column("Status", justify="left")
    table.add_column("Release MBID")
    table.add_column("RG MBID")
    table.add_column("Conf", justify="right")

    for entry in entries:
        table.add_row(
            entry.position,
            entry.title,
            entry.artist,
            entry.catalog_number or "-",
            entry.last_week or "-",
            entry.peak or "-",
            entry.weeks or "-",
            entry.status,
            entry.release_mbid or "-",
            entry.release_group_mbid or "-",
            str(entry.confidence) if entry.confidence else "-",
        )

    Console().print(table)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape the Official Charts albums chart.")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Number of rows to print (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument("--url", default=CHART_URL, help="Chart URL to scrape")
    parser.add_argument("--mb-base-url", default=MB_BASE_URL, help="MusicBrainz API base URL")
    args = parser.parse_args()

    try:
        html = fetch_chart_html(args.url)
    except httpx.HTTPError as exc:
        print(f"Error fetching chart: {exc}", file=sys.stderr)
        return 1

    entries = parse_chart(html)
    if not entries:
        print("No chart entries found. The page structure may have changed.", file=sys.stderr)
        return 1

    limit = max(1, args.limit)
    entries_to_render = entries[:limit]
    asyncio.run(enrich_entries(entries_to_render, args.mb_base_url))
    render_table(entries_to_render)
    return 0


async def enrich_entries(entries: list[ChartEntry], mb_base_url: str) -> None:
    await populate_catalog_numbers(entries)
    await populate_mb_matches(entries, mb_base_url)


async def populate_catalog_numbers(entries: list[ChartEntry]) -> None:
    headers = {
        "User-Agent": "jamarr-chart/1.0 (+https://www.officialcharts.com/)",
        "Accept": "application/json",
    }
    semaphore = asyncio.Semaphore(10)

    async def fetch_catalog(entry: ChartEntry) -> None:
        if not entry.info_url:
            return
        async with semaphore:
            try:
                response = await client.get(entry.info_url, headers=headers)
                response.raise_for_status()
                data = response.json()
                entry.catalog_number = _normalize_space(str(data.get("catNo", "")))
            except (httpx.HTTPError, ValueError):
                entry.catalog_number = ""

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        await asyncio.gather(*(fetch_catalog(entry) for entry in entries))


def _barcode_candidates(catno: str) -> list[str]:
    if not catno:
        return []
    digits = re.sub(r"\D", "", catno)
    if len(digits) in {12, 13, 14}:
        return [digits]
    if len(digits) == 11:
        return [f"0{digits}"]
    return []


def _build_mb_queries(artist: str, title: str, catno: str) -> list[str]:
    artist_variants = generate_artist_variants(artist)
    title_variants = generate_title_variants(title, artist)
    queries = []

    barcodes = _barcode_candidates(catno)
    for barcode in barcodes:
        queries.append(f'barcode:"{barcode}" AND artist:"{artist_variants[0]}"')

    for artist_variant in artist_variants:
        for title_variant in title_variants:
            queries.append(f'release:"{title_variant}" AND artist:"{artist_variant}"')

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

    title_score = fuzz.token_set_ratio(
        _normalize_for_scoring(entry.title),
        _normalize_for_scoring(title),
    )
    artist_score = fuzz.token_set_ratio(
        _normalize_for_scoring(entry.artist),
        _normalize_for_scoring(artist),
    )

    score = int(title_score * 0.6 + artist_score * 0.3)

    for barcode in _barcode_candidates(entry.catalog_number):
        if candidate.get("barcode") == barcode:
            score += 10

    country = candidate.get("country")
    if country in {"GB", "XW"}:
        score += 5

    if (candidate.get("status") or "").lower() == "official":
        score += 5

    return min(score, 100)

def _is_album_release(candidate: dict) -> bool:
    rg = candidate.get("release-group") or {}
    primary_type = (rg.get("primary-type") or "").lower()
    if primary_type:
        return primary_type == "album"
    return True


async def populate_mb_matches(entries: list[ChartEntry], mb_base_url: str) -> None:
    semaphore = asyncio.Semaphore(6)

    async def fetch_matches(entry: ChartEntry) -> None:
        queries = _build_mb_queries(entry.artist, entry.title, entry.catalog_number)
        if not queries:
            return

        best = None
        async with semaphore:
            for query in queries:
                try:
                    response = await client.get(
                        f"{mb_base_url}/ws/2/release/",
                        params={"query": query, "fmt": "json", "limit": 25},
                        headers={"User-Agent": "jamarr-chart/1.0"},
                    )
                    response.raise_for_status()
                    data = response.json()
                except (httpx.HTTPError, ValueError):
                    continue

                for candidate in data.get("releases", []):
                    if not _is_album_release(candidate):
                        continue
                    score = _score_candidate(entry, candidate)
                    if best is None or score > best["score"]:
                        best = {
                            "score": score,
                            "id": candidate.get("id", ""),
                            "rg_id": (candidate.get("release-group") or {}).get("id", ""),
                        }

        if best:
            entry.release_mbid = best["id"]
            entry.release_group_mbid = best["rg_id"]
            entry.confidence = best["score"]

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        await asyncio.gather(*(fetch_matches(entry) for entry in entries))


if __name__ == "__main__":
    raise SystemExit(main())
