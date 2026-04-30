import httpx
import logging
import asyncio
from urllib.parse import urlparse
from app.config import get_musicbrainz_root_url, get_musicbrainz_rate_limit
from app.scanner.stats import get_api_tracker
from app.scanner.services.utils import RateLimiter

logger = logging.getLogger("scanner.services.musicbrainz")


def _url_host_matches(url: str, domain: str) -> bool:
    """Check whether *url* belongs to *domain* (e.g. 'tidal.com')."""
    try:
        host = urlparse(url).hostname
        return host is not None and (host == domain or host.endswith("." + domain))
    except Exception:
        return False


MB_API_ROOT = f"{get_musicbrainz_root_url()}/ws/2"

# Global Limiter
mb_limit_val = get_musicbrainz_rate_limit()
mb_limiter = RateLimiter(
    rate_limit=mb_limit_val, burst_limit=5 if mb_limit_val is None else 2
)

async def fetch_core(artist_mbid: str, client: httpx.AsyncClient, artist_name: str = None):
    """
    Fetch Core Artist Metadata from MusicBrainz.
    Returns:
    - name, sort_name
    - musicbrainz_url
    - dictionary of relations (links, wikidata_url, spotify_candidates)
    - genres
    """

    await mb_limiter.acquire()
    logger.debug(f"[{artist_mbid}] MB Fetch Core Start")
    mb_url = f"{MB_API_ROOT}/artist/{artist_mbid}?inc=url-rels+genres&fmt=json"
    
    updates = {}
    
    for attempt in range(3):
        try:
            get_api_tracker().increment("musicbrainz")
            resp = await client.get(mb_url)
            if resp.status_code == 200:
                mb_data = resp.json()
                
                # Basic info
                updates["name"] = mb_data.get("name")
                updates["sort_name"] = mb_data.get("sort-name")
                updates["musicbrainz_url"] = f"{get_musicbrainz_root_url()}/artist/{artist_mbid}"
                
                # Relations
                relations = mb_data.get("relations", [])
                spotify_cands = []
                
                for rel in relations:
                    target = rel.get("url", {}).get("resource")
                    type_ = rel.get("type", "")
                    
                    if not target:
                        continue

                    if type_ == "official homepage" and not updates.get("homepage"):
                        updates["homepage"] = target
                    elif type_ == "wikidata":
                        updates["wikidata_url"] = target
                    elif _url_host_matches(target, "tidal.com"):
                        updates["tidal_url"] = target
                    elif _url_host_matches(target, "qobuz.com"):
                        updates["qobuz_url"] = target
                    elif _url_host_matches(target, "discogs.com"):
                        updates["discogs_url"] = target
                    elif _url_host_matches(target, "spotify.com") and type_ in ("streaming", "free streaming"):
                        parts = target.split("/")
                        if parts:
                            cand_id = parts[-1].split("?")[0]
                            if cand_id and not any(cand_id == c[0] for c in spotify_cands):
                                spotify_cands.append((cand_id, target))

                updates["_spotify_candidates"] = spotify_cands
                
                # Genres
                if mb_data.get("genres"):
                    updates["genres"] = [
                        {"name": g["name"], "count": g.get("count", 0)}
                        for g in mb_data["genres"]
                    ]
                    updates["genres"].sort(key=lambda x: x["count"], reverse=True)
                
                return updates
                
            elif resp.status_code == 503:
                logger.debug("Rate limited by MusicBrainz, sleeping...")
                await asyncio.sleep(1 * (attempt + 1))
                continue
            elif resp.status_code == 404:
                return None
            else:
                logger.warning(f"MB Error {resp.status_code}")
                return None
                
        except Exception as e:
            logger.warning(f"[{artist_name or artist_mbid}] MB Fetch Error (Attempt {attempt + 1}): {e}")
            await asyncio.sleep(1)
            
    return None

async def fetch_release_groups(artist_mbid: str, type_str: str, client: httpx.AsyncClient, artist_name: str = None):
    """
    Fetch Release Groups (Albums or Singles).
    type_str: 'single' or 'album' (or 'ep')
    """
    results = []
    try:
        offset = 0
        limit = 100
        seen_titles = set()
        
        # Strategy: "release" browse for Singles (Strict), "release-group" for others
        use_release_browse = type_str == "single"
        
        base_endpoint = "release" if use_release_browse else "release-group"
        extra_query = "&status=official" if use_release_browse else ""
        inc_params = "release-groups+artist-credits" if use_release_browse else "artist-credits"
        
        while True:
            await mb_limiter.acquire()
            url = f"{MB_API_ROOT}/{base_endpoint}?artist={artist_mbid}&type={type_str}&fmt=json&limit={limit}&offset={offset}&inc={inc_params}{extra_query}"
            get_api_tracker().increment("musicbrainz")
            
            resp = await client.get(url)
            if resp.status_code != 200:
                break
            
            data = resp.json()
            items = data.get("releases" if use_release_browse else "release-groups", [])
            
            logger.debug(f"MB API returned {len(items)} items at offset {offset} for type={type_str}")
            
            if not items:
                break
                
            for item in items:
                rg = item.get("release-group", {}) if use_release_browse else item
                
                if use_release_browse:
                     if item.get("country") not in ("US", "GB", "XW"):
                         continue
                
                if not rg.get("id"):
                    continue

                # Secondary Type Filter (Strict)
                if rg.get("secondary-types"):
                    continue
                    
                title = rg.get("title")
                if not title:
                    continue
                    
                norm_title = title.lower().strip()
                if "spotify" in norm_title:
                    continue
                    
                if norm_title in seen_titles:
                    continue
                seen_titles.add(norm_title)
                
                final_date = rg.get("first-release-date")
                
                results.append({
                    "mbid": rg["id"],
                    "title": title,
                    "date": final_date,
                    "musicbrainz_url": f"{get_musicbrainz_root_url()}/release-group/{rg['id']}"
                })
            
            if len(items) < limit:
                break
            offset += limit
            
            if use_release_browse and offset > 2000:
                break
                
        results.sort(key=lambda x: x["date"] or "", reverse=True)
        return results
        
    except Exception as e:
        logger.error(f"[{artist_name or artist_mbid}] Error fetching {type_str} for {artist_mbid}: {e}")
        return []

async def fetch_best_release_match(rg_id: str, client: httpx.AsyncClient):
    """
    Fetches releases for a Release Group.
    """
    try:
        await mb_limiter.acquire()
        url = f"{MB_API_ROOT}/release?release-group={rg_id}&inc=url-rels+media&fmt=json&limit=100"
        
        # We don't increment stats here? Original didn't seem to have it, but maybe it should?
        # Original code: await mb_limiter.acquire(); resp = await client.get(url)
        # I'll add increment to be safe and consistent.
        get_api_tracker().increment("musicbrainz")
        
        resp = await client.get(url)
        if resp.status_code != 200:
            return None

        data = resp.json()
        releases = data.get("releases", [])
        if not releases:
            return None

        def score_release(rel):
            score = 0
            media = rel.get("media", [])
            formats = []
            for m in media:
                fmt = m.get("format")
                if fmt:
                    formats.append(fmt.lower())
            if "digital media" in formats:
                score += 1000
            elif "cd" in formats:
                score += 500
            
            country = rel.get("country", "")
            if country == "XW":
                score += 100
            elif country in ["US", "GB"]:
                score += 50
            return score

        releases.sort(key=lambda x: (score_release(x), x.get("date", "")), reverse=True)
        best = releases[0]
        best_release_id = best.get("id")

        links = []
        seen_urls = set()

        def add_links_from_release(release):
            for rel in release.get("relations", []):
                target = rel.get("url", {}).get("resource", "")
                if not target or target in seen_urls:
                    continue
                
                l_type = None
                if _url_host_matches(target, "tidal.com"):
                    l_type = "tidal"
                elif _url_host_matches(target, "qobuz.com"):
                    l_type = "qobuz"
                elif _url_host_matches(target, "musicbrainz.org"):
                    l_type = "musicbrainz"
                
                if l_type:
                    links.append({"type": l_type, "url": target})
                    seen_urls.add(target)

        add_links_from_release(best)
        for rel in releases:
            if rel.get("id") == best_release_id:
                continue
            add_links_from_release(rel)
            
        release_ids = [r["id"] for r in releases]
        
        return {
            "links": links,
            "release_ids": release_ids,
            "primary_release_id": best_release_id,
        }

    except Exception as e:
        logger.warning(f"Error resolving release links for {rg_id}: {e}")
        return {"links": [], "release_ids": [], "primary_release_id": None}

