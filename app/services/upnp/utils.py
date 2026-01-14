from typing import Dict, Any, Optional, List
import xml.etree.ElementTree as ET
from urllib.parse import urljoin
import aiohttp
import logging

logger = logging.getLogger(__name__)

def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag

def _parse_icons(xml_text: str, base_url: str) -> List[Dict[str, Any]]:
    root = ET.fromstring(xml_text)
    icons: List[Dict[str, Any]] = []
    for node in root.iter():
        if _strip_ns(node.tag) != "icon":
            continue
        icon: Dict[str, Any] = {}
        for child in node:
            key = _strip_ns(child.tag)
            val = (child.text or "").strip()
            if not val:
                continue
            if key in {"width", "height", "depth"}:
                try:
                    icon[key] = int(val)
                except ValueError:
                    icon[key] = val
            else:
                icon[key] = val
        if "url" in icon:
            icon["url"] = urljoin(base_url, icon["url"])
        if icon:
            icons.append(icon)
    return icons

def _pick_best_icon(icons: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not icons:
        return None
    filtered = []
    for icon in icons:
        mimetype = (icon.get("mimetype") or "").lower()
        if not mimetype:
            url = (icon.get("url") or "").lower()
            if url.endswith(".png"):
                mimetype = "image/png"
            elif url.endswith(".jpg") or url.endswith(".jpeg"):
                mimetype = "image/jpeg"
        if mimetype not in {"image/png", "image/jpeg", "image/jpg"}:
            continue
        if not icon.get("url"):
            continue
        icon["mimetype"] = mimetype
        filtered.append(icon)
    if not filtered:
        return None
    def sort_key(icon: Dict[str, Any]) -> tuple:
        width = icon.get("width") or 0
        height = icon.get("height") or 0
        area = width * height
        is_png = 1 if (icon.get("mimetype") or "").lower() == "image/png" else 0
        return (area, is_png)
    return sorted(filtered, key=sort_key, reverse=True)[0]

async def fetch_device_icons(
    session: aiohttp.ClientSession, location: str
) -> List[Dict[str, Any]]:
    if not location:
        return []
    try:
        async with session.get(
            location, timeout=aiohttp.ClientTimeout(total=8)
        ) as resp:
            if resp.status != 200:
                return []
            xml_text = await resp.text()
    except Exception as e:
        logger.debug(f"Failed to fetch device description {location}: {e}")
        return []
    try:
        return _parse_icons(xml_text, location)
    except Exception as e:
        logger.debug(f"Failed to parse device icons {location}: {e}")
        return []

async def select_renderer_icon(
    session: aiohttp.ClientSession, location: str
) -> Optional[Dict[str, Any]]:
    icons = await fetch_device_icons(session, location)
    return _pick_best_icon(icons)
