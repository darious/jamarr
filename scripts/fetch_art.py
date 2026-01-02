#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import httpx
import yaml
from PIL import Image, ImageFile
from rich.console import Console
from rich.logging import RichHandler

# Re-use the album_art processing pipeline for RGB conversion, resizing, and JPEG export.
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.append(str(SCRIPT_DIR))
sys.path.append(str(ROOT_DIR))
try:
    from album_art import convert_to_rgb, resize_if_needed, save_jpeg_atomic  # type: ignore
except Exception as exc:  # pragma: no cover - import guard
    raise SystemExit(f"Failed to import album_art helpers: {exc}")

try:
    from app.config import get_musicbrainz_root_url  # type: ignore
except Exception:
    get_musicbrainz_root_url = None


def resolve_mb_base() -> str:
    try:
        if get_musicbrainz_root_url:
            root = get_musicbrainz_root_url()
        else:
            raise RuntimeError("app.config get_musicbrainz_root_url unavailable")
    except Exception:
        # Fallback: read config.yaml next to repo root
        cfg_path = ROOT_DIR / "config.yaml"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r") as f:
                    cfg = yaml.safe_load(f) or {}
                root = cfg.get("musicbrainz", {}).get("root_url", "https://musicbrainz.org")
            except Exception:
                root = "https://musicbrainz.org"
        else:
            root = "https://musicbrainz.org"
    return root.rstrip("/") + "/ws/2"


MB_BASE = resolve_mb_base()
CAA_BASE = "https://coverartarchive.org"
USER_AGENT = "JamarrArtFetcher/1.0 ( dev@jamarr.local )"
MIN_TARGET_DIM = 2800

console = Console()
logger = None
ImageFile.LOAD_TRUNCATED_IMAGES = True


def setup_logging() -> None:
    global logger
    logger = logging.getLogger("fetch_art")
    logger.setLevel(logging.INFO)
    handler = RichHandler(console=console, show_time=False, show_path=False, rich_tracebacks=True)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.handlers.clear()
    logger.addHandler(handler)


def sanitize_component(value: str) -> str:
    """
    Make a string safe for filenames: strip path separators and control chars.
    """
    bad_chars = ['/', '\\', ':', '*', '?', '"', "<", ">", "|"]
    for ch in bad_chars:
        value = value.replace(ch, "-")
    return "".join(c for c in value if c.isprintable()).strip() or "unknown"


async def fetch_json(url: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    headers = {"User-Agent": USER_AGENT}
    resp = await client.get(url, headers=headers, follow_redirects=True, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


async def fetch_release_metadata(mbid: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    url = f"{MB_BASE}/release/{mbid}?inc=artist-credits+release-groups&fmt=json"
    return await fetch_json(url, client)


async def fetch_release_group_metadata(mbid: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    url = f"{MB_BASE}/release-group/{mbid}?inc=releases&fmt=json"
    return await fetch_json(url, client)


def format_artist_credit(credits: Optional[Iterable[Dict[str, Any]]]) -> str:
    parts = []
    for credit in credits or []:
        artist = credit.get("artist", {}) if isinstance(credit, dict) else {}
        name = artist.get("sort-name") or credit.get("name") or artist.get("name")
        join = credit.get("joinphrase", "")
        if name:
            parts.append(f"{name}{join}")
    return "".join(parts) or "Unknown Artist"


def thumb_size_value(key: str) -> int:
    key_lower = key.lower()
    if key_lower.isdigit():
        return int(key_lower)
    if key_lower == "large":
        return 500
    if key_lower == "small":
        return 250
    return 0


def pick_best_image_entry(images: list[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not images:
        return None
    front_images = [img for img in images if img.get("front") or "Front" in (img.get("types") or [])]
    candidates = front_images or images

    best: Optional[Dict[str, Any]] = None
    best_score = -1
    for img in candidates:
        thumbs = img.get("thumbnails") or {}
        max_thumb = max((thumb_size_value(k) for k in thumbs.keys()), default=0)
        # Treat the full-size image URL as the largest possible size.
        score = max_thumb
        if img.get("image"):
            score = max(score, 10**9)
        if score > best_score:
            best = img
            best_score = score
    return best


def largest_url_from_entry(entry: Dict[str, Any]) -> Optional[str]:
    if entry.get("image"):
        return entry["image"]
    thumbs = entry.get("thumbnails") or {}
    if not thumbs:
        return None
    key = max(thumbs.keys(), key=thumb_size_value)
    return thumbs.get(key)


async def fetch_best_caa_image(mbid: str, scope: str, client: httpx.AsyncClient) -> Optional[str]:
    url = f"{CAA_BASE}/{scope}/{mbid}"
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = await client.get(url, headers=headers, follow_redirects=True, timeout=30.0)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        best_entry = pick_best_image_entry(data.get("images", []))
        return largest_url_from_entry(best_entry) if best_entry else None
    except httpx.HTTPStatusError as exc:
        # Other 4xx/5xx will be reported; keep searching releases if any.
        logger.info("Cover Art Archive %s lookup failed (%s)", scope, exc.response.status_code)
        return None
    except Exception as exc:
        logger.info("Cover Art Archive %s lookup error: %s", scope, exc)
        return None


def size_score(width: int, height: int) -> int:
    return width * height


def parse_date_to_tuple(date_str: str) -> tuple[int, int, int]:
    """
    Parse YYYY[-MM[-DD]] into tuple for sorting. Missing parts become 0.
    """
    if not date_str:
        return (0, 0, 0)
    parts = date_str.split("-")
    try:
        y = int(parts[0]) if len(parts) > 0 else 0
        m = int(parts[1]) if len(parts) > 1 else 0
        d = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return (0, 0, 0)
    return (y, m, d)


async def evaluate_scope_art(
    scope: str, ident: str, label: str, client: httpx.AsyncClient
) -> Optional[tuple[bytes, str, tuple[int, int], str]]:
    url = await fetch_best_caa_image(ident, scope, client)
    if not url:
        logger.info("No art found for %s %s", scope, ident)
        return None

    logger.info("Attempting art from %s (%s): %s", scope, label, url)
    try:
        data, final_url = await download_image(url, client)
    except Exception as exc:
        logger.info("Download failed for %s %s: %s", scope, ident, exc)
        return None

    try:
        with Image.open(BytesIO(data)) as im:
            width, height = im.size
    except Exception as exc:
        logger.info("Could not read image for %s %s: %s", scope, ident, exc)
        return None

    logger.info("Fetched %s art size: %dx%d", scope, width, height)
    return data, final_url, (width, height), label


async def find_best_image_for_release(
    release_id: str,
    release_group_id: Optional[str],
    releases: list[Dict[str, Any]],
    client: httpx.AsyncClient,
) -> Optional[tuple[bytes, str, tuple[int, int], str]]:
    """
    Order:
    1) Release art (if big enough, stop)
    2) Release-group art (if big enough, stop)
    3) Other releases newest -> oldest (first big enough wins)
    If nothing hits the target, return the largest image encountered.
    """
    best: Optional[tuple[bytes, str, tuple[int, int], str]] = None
    best_score = -1

    async def consider(scope: str, ident: str, label: str) -> Optional[tuple[bytes, str, tuple[int, int], str]]:
        nonlocal best, best_score
        candidate = await evaluate_scope_art(scope, ident, label, client)
        if not candidate:
            return None

        data, final_url, (width, height), source_label = candidate
        score = size_score(width, height)
        if score > best_score:
            best = candidate
            best_score = score

        if min(width, height) >= MIN_TARGET_DIM:
            logger.info("Using %s art (meets target >= %d)", scope, MIN_TARGET_DIM)
            return candidate
        return None

    # 1) Release art
    hit = await consider("release", release_id, "release")
    if hit:
        return hit

    # 2) Release-group art
    if release_group_id:
        hit = await consider("release-group", release_group_id, "release group")
        if hit:
            return hit

    # 3) Other releases (newest -> oldest)
    other_releases = [
        r for r in releases if r.get("id") and r.get("id") != release_id
    ]
    other_releases.sort(
        key=lambda r: parse_date_to_tuple(str(r.get("date", ""))), reverse=True
    )
    for rel in other_releases:
        rel_id = rel.get("id")
        label = rel.get("title") or "release"
        hit = await consider("release", rel_id, label)
        if hit:
            return hit

    return best


async def download_image(url: str, client: httpx.AsyncClient) -> tuple[bytes, str]:
    headers = {"User-Agent": USER_AGENT}
    resp = await client.get(url, headers=headers, follow_redirects=True, timeout=60.0)
    resp.raise_for_status()
    return resp.content, str(resp.url)


async def process_release(mbid: str) -> int:
    setup_logging()
    logger.info("MusicBrainz base: %s", MB_BASE.replace("/ws/2", ""))
    logger.info("Fetching metadata for release %s", mbid)

    try:
        async with httpx.AsyncClient() as client:
            release_meta = await fetch_release_metadata(mbid, client)
            title = release_meta.get("title") or "Unknown Album"
            artist = format_artist_credit(release_meta.get("artist-credit"))
            logger.info("Release: %s — %s", artist, title)

            release_group_id = (
                release_meta.get("release-group") or {}
            ).get("id")
            releases: list[Dict[str, Any]] = []
            if release_group_id:
                logger.info("Fetching release-group metadata %s for alternatives", release_group_id)
                try:
                    release_group_meta = await fetch_release_group_metadata(release_group_id, client)
                    releases = release_group_meta.get("releases", []) or []
                except httpx.HTTPStatusError as exc:
                    logger.warning("Release-group lookup failed (%s): %s", exc.response.status_code, exc)
                except Exception as exc:
                    logger.warning("Failed to fetch release-group metadata: %s", exc)

            best = await find_best_image_for_release(mbid, release_group_id, releases, client)
            if not best:
                logger.error("No cover art found in Cover Art Archive for this release or related releases.")
                return 1

            data, final_url, (width, height), source_label = best
    except httpx.HTTPStatusError as exc:
        logger.error("MusicBrainz request failed (%s): %s", exc.response.status_code, exc)
        return 1
    except httpx.RequestError as exc:
        logger.error("Network error contacting MusicBrainz: %s", exc)
        return 1
    except Exception as exc:
        logger.error("Unexpected error: %s", exc)
        return 1

    with Image.open(BytesIO(data)) as im:
        im = convert_to_rgb(im)
        processed, resized = resize_if_needed(im)
        out_width, out_height = processed.size

        filename = f"{sanitize_component(artist)} - {sanitize_component(title)} {mbid}.jpg"
        out_path = Path.cwd() / filename

        def save_with_recovery(img: Image.Image, dest: Path) -> bool:
            try:
                img.load()
                save_jpeg_atomic(img, dest)
                return True
            except OSError as exc:
                logger.warning("Initial save failed (%s); rebuilding image buffer", exc)
                try:
                    rebuilt = Image.frombytes(img.mode, img.size, img.tobytes())
                    rebuilt.load()
                    save_jpeg_atomic(rebuilt, dest)
                    return True
                except Exception as exc2:
                    logger.warning("Rebuild + optimized save failed (%s); trying plain JPEG save", exc2)
                    try:
                        rebuilt.save(dest, format="JPEG", quality=95)
                        logger.info("Saved using plain JPEG fallback (no optimize/progressive)")
                        return True
                    except Exception as exc3:
                        logger.error("Plain JPEG save failed: %s", exc3)
                        return False

        if not save_with_recovery(processed, out_path):
            return 1

    if resized:
        logger.info("Resized to %dx%d and saved to %s", out_width, out_height, out_path)
    else:
        logger.info("Saved (no resize needed) to %s", out_path)
    logger.info("Source: %s (picked from %s art, original %dx%d)", final_url, source_label, width, height)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Fetch and process cover art for a MusicBrainz release.")
    parser.add_argument("mbid", help="MusicBrainz release ID")
    args = parser.parse_args(argv)
    return asyncio.run(process_release(args.mbid))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
