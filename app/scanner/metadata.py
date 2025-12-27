
import httpx
import json
import time
import asyncio
from bs4 import BeautifulSoup
import logging
import base64
import re
import difflib
import math
from app.config import get_spotify_credentials, get_musicbrainz_root_url, get_musicbrainz_rate_limit, get_qobuz_region, get_fanarttv_api_key, get_max_workers, get_lastfm_credentials
from app.db import get_db

logger = logging.getLogger("scanner.metadata")

MB_API_ROOT = f"{get_musicbrainz_root_url()}/ws/2"
WIKI_API_ROOT = "https://en.wikipedia.org/api/rest_v1/page/summary"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_ROOT = "https://api.spotify.com/v1"
FANART_API_ROOT = "https://webservice.fanart.tv/v3/music"
SPOTIFY_SCANNING_DISABLED = False

_spotify_token = None
_token_expiry = 0

class RateLimiter:
    def __init__(self, rate_limit: float, burst_limit: int = 1):
        self.rate_limit = rate_limit
        self.burst_limit = burst_limit
        self._tokens = burst_limit
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        if self.rate_limit is None:
            return
            
        async with self._lock:
            now = time.monotonic()
            time_passed = now - self._last_update
            self._last_update = now
            self._tokens = min(self.burst_limit, self._tokens + time_passed * self.rate_limit)

            if self._tokens < 1:
                wait_time = (1 - self._tokens) / self.rate_limit
                await asyncio.sleep(wait_time)
                self._tokens -= 1
                self._last_update = time.monotonic()
            else:
                self._tokens -= 1

# Global Limiters
mb_limit_val = get_musicbrainz_rate_limit()
mb_limiter = RateLimiter(rate_limit=mb_limit_val, burst_limit=5 if mb_limit_val is None else 2)

async def fetch_fanart_artist_images(client: httpx.AsyncClient, mbid: str):
    """
    Fetch best artist thumb and background URLs from Fanart.tv for a given MusicBrainz ID.
    Returns dict with keys: thumb, background.
    """
    api_key = get_fanarttv_api_key()
    if not api_key or not mbid:
        return {"thumb": None, "background": None}

    def _pick_best(entries):
        if not entries:
            return None
        def _score(entry):
            likes = entry.get("likes") or 0
            try:
                likes = int(likes)
            except (TypeError, ValueError):
                likes = 0
            return (likes, entry.get("url") or "")
        best = max(entries, key=_score)
        url = best.get("url")
        if url and url.startswith("http://"):
            url = "https://" + url[len("http://"):]
        return url

    try:
        resp = await client.get(f"{FANART_API_ROOT}/{mbid}", params={"api_key": api_key}, timeout=20.0)
        if resp.status_code != 200:
            logger.debug(f"Fanart.tv lookup failed for {mbid}: {resp.status_code}")
            return {"thumb": None, "background": None}

        data = resp.json()
        return {
            "thumb": _pick_best(data.get("artistthumb") or []),
            "background": _pick_best(data.get("artistbackground") or []),
        }
    except Exception as e:
        logger.debug(f"Fanart.tv fetch error for {mbid}: {e}")
        return {"thumb": None, "background": None}

async def get_spotify_token(client: httpx.AsyncClient):
    global _spotify_token, _token_expiry
    if _spotify_token and time.time() < _token_expiry:
        return _spotify_token
    
    client_id, client_secret = get_spotify_credentials()
    if not client_id or not client_secret:
        return None

    auth_str = f"{client_id}:{client_secret}"
    b64_auth = base64.b64encode(auth_str.encode()).decode()
    
    try:
        resp = await client.post(
            SPOTIFY_TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {b64_auth}"}
        )
        if resp.status_code == 200:
            data = resp.json()
            _spotify_token = data["access_token"]
            _token_expiry = time.time() + data["expires_in"] - 60
            return _spotify_token
        else:
            logger.error(f"Spotify Auth Failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Spotify Auth Error: {e}")
    return None

def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower()) if name else ""

def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _normalize_name(a), _normalize_name(b)).ratio()

async def _evaluate_spotify_candidate(client: httpx.AsyncClient, headers: dict, candidate_id: str, target_name: str):
    try:
        resp = await client.get(f"{SPOTIFY_API_ROOT}/artists/{candidate_id}", headers=headers)
        if resp.status_code == 429:
             raise RuntimeError("Spotify Rate Limit Exceeded")
        if resp.status_code != 200:
            return None
        data = resp.json()
        name = data.get("name") or ""
        pop = data.get("popularity") or 0
        followers = data.get("followers", {}).get("total") or 0

        name_score = _similarity(name, target_name)
        pop_score = min(max(pop, 0), 100) / 100
        # Normalize followers with log scale to keep within 0-1
        followers_score = min(math.log10(followers + 1) / 7, 1) if followers else 0
        final_score = name_score * 0.7 + pop_score * 0.2 + followers_score * 0.1

        return {
            "id": candidate_id,
            "url": data.get("external_urls", {}).get("spotify"),
            "name": name,
            "popularity": pop,
            "followers": followers,
            "name_score": name_score,
            "final_score": final_score,
        }
    except Exception as e:
        logger.debug(f"Failed to evaluate Spotify candidate {candidate_id}: {e}")
        return None

async def _pick_best_spotify_candidate(client: httpx.AsyncClient, headers: dict, candidates: list, target_name: str):
    """
    Given candidate Spotify IDs, pick the best match using name similarity + popularity.
    Returns (id, url) or (None, None) if no safe match.
    """
    scored = []
    for cid, _url in candidates:
        res = await _evaluate_spotify_candidate(client, headers, cid, target_name)
        if res:
            scored.append(res)

    if not scored:
        return None, None

    # Filter out very low name matches
    scored = [c for c in scored if c["name_score"] >= 0.55]
    if not scored:
        return None, None

    # Sort by final_score, then popularity, then followers
    scored.sort(key=lambda x: (x["final_score"], x["popularity"], x["followers"]), reverse=True)
    best = scored[0]

    # If Spotify API didn't return a URL, fall back to the MB-provided one for this ID
    if not best.get("url"):
        for cid, url in candidates:
            if cid == best["id"]:
                return best["id"], url

    return best["id"], best.get("url")

async def fetch_wikidata_external_links(client: httpx.AsyncClient, wikidata_url: str, existing_links: dict) -> dict:
    """
    Fetch external service IDs from Wikidata and construct URLs.
    Only returns links that are missing from existing_links.
    
    Args:
        client: HTTP client
        wikidata_url: Wikidata entity URL (e.g., https://www.wikidata.org/wiki/Q45188)
        existing_links: Dict of existing links to check against
        
    Returns:
        Dict of {service: url} for missing links only
    """
    missing_links = {}
    
    try:
        # Extract QID from URL
        qid = wikidata_url.split("/")[-1]
        wd_api = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
        
        logger.debug(f"Fetching Wikidata external links for {qid}...")
        resp = await client.get(wd_api)
        if resp.status_code != 200:
            logger.warning(f"Wikidata fetch failed: {resp.status_code}")
            return missing_links
        
        wd_data = resp.json()
        entities = wd_data.get("entities", {})
        entity = entities.get(qid, {})
        claims = entity.get("claims", {})
        
        # Property mapping: Wikidata property ID -> (service_name, URL_template)
        property_map = {
            "P1902": ("spotify_url", "https://open.spotify.com/artist/{}"),
            "P5749": ("tidal_url", "https://tidal.com/browse/artist/{}"),
            "P6573": ("qobuz_url", "https://www.qobuz.com/us-en/interpreter/{}"),
            "P3192": ("lastfm_url", "https://www.last.fm/music/{}"),
            "P1953": ("discogs_url", "https://www.discogs.com/artist/{}"),
            "P856": ("homepage", None),  # Direct URL, no template
        }
        
        for prop_id, (service_name, url_template) in property_map.items():
            # Skip if we already have this link from MusicBrainz
            if existing_links.get(service_name):
                continue
            
            # Check if Wikidata has this property
            if prop_id not in claims:
                continue
            
            try:
                # Extract value from claim
                mainsnak = claims[prop_id][0].get("mainsnak", {})
                datavalue = mainsnak.get("datavalue", {})
                value = datavalue.get("value")
                
                if not value:
                    continue
                
                # Construct URL
                if url_template:
                    # For ID-based properties, construct URL from template
                    url = url_template.format(value)
                else:
                    # For direct URL properties (like homepage), use value directly
                    url = value
                
                missing_links[service_name] = url
                
            except Exception as e:
                logger.warning(f"Failed to extract {service_name} from Wikidata: {e}")
                continue
        
        if missing_links:
            # Create a comprehensive log message showing all filled links
            link_types = ", ".join(missing_links.keys())
            logger.info(f"Wikidata filled {len(missing_links)} missing link(s): {link_types}")
        
    except Exception as e:
        logger.warning(f"Wikidata external links fetch failed: {e}")
    
    return missing_links

async def fetch_lastfm_top_tracks(mbid, artist_name):
    """
    Fetch top tracks from Last.fm using MBID strict.
    """
    if not mbid: return []
    
    api_key, _ = get_lastfm_credentials()
    if not api_key:
        logger.warning("Last.fm API key not configured.")
        return []

    url = "http://ws.audioscrobbler.com/2.0/"
    params = {
        "method": "artist.gettoptracks",
        "mbid": mbid,
        "api_key": api_key,
        "format": "json",
        "limit": 15  # Fetch slightly more to allow filtering if needed
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                tracks_data = data.get("toptracks", {}).get("track", [])
                if not tracks_data: return []
                
                # Normalize result to list if single dict
                if isinstance(tracks_data, dict): tracks_data = [tracks_data]
                
                results = []
                rank = 1
                for t in tracks_data:
                    if rank > 10: break
                    
                    # Extract MBID if available (Track MBID)
                    track_mbid = t.get("mbid")
                    
                    results.append({
                        "name": t.get("name"),
                        "mbid": track_mbid, # Use this for matching
                        "rank": rank,
                        "playcount": t.get("playcount"),
                        "popularity": t.get("playcount"), # Map playcount to popularity for storage
                        "album": None # Last.fm top tracks often don't have album info directly
                    })
                    rank += 1
                return results
            else:
                logger.warning(f"Last.fm Top Tracks error {resp.status_code} for {mbid}")
                return []
    except Exception as e:
        logger.error(f"Last.fm Top Tracks failed for {mbid}: {e}")
        return []

async def fetch_lastfm_artist_url(mbid: str):
    """
    Fetch artist URL from Last.fm using MBID.
    """
    if not mbid: return None
    
    api_key, _ = get_lastfm_credentials()
    if not api_key: return None

    url = "http://ws.audioscrobbler.com/2.0/"
    params = {
        "method": "artist.getinfo",
        "mbid": mbid,
        "api_key": api_key,
        "format": "json"
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("artist", {}).get("url")
            else:
                logger.debug(f"Last.fm Artist Info error {resp.status_code} for {mbid}")
                return None
    except Exception as e:
        logger.debug(f"Last.fm Artist Info failed for {mbid}: {e}")
        return None


async def fetch_lastfm_similar_artists(mbid, artist_name):
    """
    Fetch similar artists from Last.fm using MBID strict.
    """
    if not mbid: return []

    api_key, _ = get_lastfm_credentials()
    if not api_key: return []

    url = "http://ws.audioscrobbler.com/2.0/"
    params = {
        "method": "artist.getsimilar",
        "mbid": mbid,
        "api_key": api_key,
        "format": "json",
        "limit": 15
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                similar_data = data.get("similarartists", {}).get("artist", [])
                if not similar_data: return []
                
                if isinstance(similar_data, dict): similar_data = [similar_data]

                results = []
                count = 0
                for a in similar_data:
                    if count >= 10: break
                    
                    # Last.fm can handle excluding the artist itself, but just in case
                    if a.get("mbid") == mbid: continue
                    if a.get("name") == artist_name: continue

                    results.append({
                        "name": a.get("name"),
                        "mbid": a.get("mbid"),
                        "match": a.get("match") 
                    })
                    count += 1
                return results
            else:
                logger.warning(f"Last.fm Similar Artists error {resp.status_code} for {mbid}")
                return []
    except Exception as e:
        logger.error(f"Last.fm Similar Artists failed for {mbid}: {e}")
        return []

async def match_track_to_library(db, artist_mbid, track_name, album_name=None, external_mb_track_id=None):
    """
    Match external track to local library track using fuzzy matching with dynamic weighting.
    Returns track_id if found, None otherwise.
    """
    # Get all tracks for this artist (including features)
    # We also fetch MB IDs now
    query = """
        SELECT t.id, t.title, t.album, t.duration_seconds, t.track_mbid, t.release_track_mbid
        FROM track t
        JOIN track_artist ta ON t.id = ta.track_id
        WHERE ta.artist_mbid = ? 
    """
    
    candidates = []
    async with db.execute(query, (artist_mbid,)) as cursor:
        candidates = await cursor.fetchall()
        
    if not candidates:
        return None

    # 1. Exact MBID Match (Highest Priority)
    if external_mb_track_id:
        for row in candidates:
            cid, ctitle, calbum, cseconds, cmb_track_id, cmb_release_track_id = row
            if cmb_track_id == external_mb_track_id or cmb_release_track_id == external_mb_track_id:
                return cid

    # Normalize helpers
    def normalize(s):
        if not s: return ""
        s = s.lower().strip()
        # Remove typical suffixes/prefixes for cleaner matching
        s = re.sub(r'[\(\[][^\)\]]*(feat|with|remast|deluxe|edit|mix)[^\)\]]*[\)\]]', '', s)
        s = re.sub(r'[^\w\s]', '', s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    def fuzzy_score(s1, s2):
        return difflib.SequenceMatcher(None, normalize(s1), normalize(s2)).ratio()

    # Calculate scores
    best_score = 0
    best_match = None
    
    for row in candidates:
        cid, ctitle, calbum, cseconds, cmb_track_id, cmb_release_track_id = row
        
        # Dynamic Weighting
        total_weight = 0.6
        current_score = 0
        
        # 1. Title Score (Base 0.6)
        t_score = fuzzy_score(track_name, ctitle)
        if t_score < 0.6: continue 
        current_score += t_score * 0.6
        
        # 2. Album Score (Weight 0.2 if applicable)
        if album_name and calbum:
            total_weight += 0.2
            a_score = fuzzy_score(album_name, calbum)
            current_score += a_score * 0.2
        
        # 3. Duration Score (Weight 0.2 if applicable)
        # We rely on caller passing correct info, but currently they pass None mostly.
        # However, checking if duration exists in DB row is good.
        # But we need external duration to compare against.
        # Since the function signature doesn't support duration yet, we skip this part 
        # basically making it Title(60%) + Album(20%) logic, which we verified works for Singles (Title 60/60 = 100%).
        
        # Normalize
        final_score = current_score / total_weight
        
        if final_score > best_score:
            best_score = final_score
            best_match = cid

    if best_score > 0.75:
        return best_match

    return None

async def fetch_artist_metadata(
    mbid: str,
    artist_name: str,
    local_release_group_ids: set = None,
    bio_only: bool = False,
    fetch_metadata: bool = True,
    fetch_bio: bool = True,
    fetch_artwork: bool = True,
    fetch_spotify_artwork: bool = False,
    fetch_links: bool = True,
    fetch_top_tracks: bool = True,
    fetch_singles: bool = True,
    known_wikipedia_url: str = None,
    known_spotify_url: str = None,
    fetch_similar_artists: bool = False,
):
    """
    Fetches comprehensive artist metadata from MusicBrainz + Spotify + Wikidata.
    """
    if local_release_group_ids is None:
        local_release_group_ids = set()

    logger.info(f"Fetching metadata for {artist_name} ({mbid})...")

    # If nothing is requested, return immediately
    if not any([fetch_metadata, fetch_bio, fetch_artwork, fetch_links, fetch_top_tracks, fetch_singles, bio_only, fetch_similar_artists]):
        return {
            "mbid": mbid,
            "name": artist_name,
            "sort_name": artist_name,
            "updated_at": time.time(),
            "bio": None,
            "image_url": None,
            "image_source": None,
            "spotify_url": None,
            "homepage": None,
            "wikipedia_url": None,
            "qobuz_url": None,
            "tidal_url": None,
            "lastfm_url": None,
            "musicbrainz_url": None,
            "similar_artists": [],
            "top_tracks": [],
            "singles": [],
            "albums": [],
        }

    metadata = {
        "mbid": mbid,
        "name": artist_name,
        "sort_name": artist_name, # Default to name
        "bio": None,
        "image_url": None,
        "image_source": None,
        "background_url": None,
        "background_source": None,
        "spotify_url": known_spotify_url,
        "homepage": None,
        "wikipedia_url": known_wikipedia_url,
        "qobuz_url": None,
        "tidal_url": None,
        "lastfm_url": None,
        "discogs_url": None,
        "musicbrainz_url": None,
        "similar_artists": [],
        "top_tracks": [],
        "singles": [],
        "albums": [],
        "genres": [],
        "updated_at": time.time()
    }

    # Fast path: artwork-only (skip MusicBrainz release/link fetch)
    only_art = fetch_artwork and not (fetch_metadata or fetch_bio or fetch_links or fetch_top_tracks or fetch_singles or bio_only)
    if only_art:
        try:
            async with httpx.AsyncClient(headers={"User-Agent": "Jamarr/0.1 ( jamarr@example.com )"}) as client:
                fanart = await fetch_fanart_artist_images(client, mbid)
                if fanart.get("thumb"):
                    metadata["image_url"] = fanart["thumb"]
                    metadata["image_source"] = "fanart.tv"
                if fanart.get("background"):
                    metadata["background_url"] = fanart["background"]
                    metadata["background_source"] = "fanart.tv"
        except Exception:
            pass
        return metadata

    try:
        async with httpx.AsyncClient(headers={"User-Agent": "Jamarr/0.1 ( jamarr@example.com )"}) as client:
            # 1. MusicBrainz Core Data & Relations
            # For singles-only runs we don't need core artist data/relations.
            # OPTIMIZATION: If we only want Bio and we already have the URL, skip MB.
            skip_mb_for_bio = bio_only and known_wikipedia_url
            
            needs_mb = (fetch_metadata or fetch_links or (fetch_bio and not skip_mb_for_bio))
            mb_data = None
            if needs_mb:
                logger.debug(f"Fetching Core Data from MusicBrainz for {artist_name} ({mbid})...")
                await mb_limiter.acquire()
                mb_url = f"{MB_API_ROOT}/artist/{mbid}?inc=url-rels+genres&fmt=json"
                
                for attempt in range(3):
                    try:
                        resp = await client.get(mb_url)
                        if resp.status_code == 200:
                            mb_data = resp.json()
                            break
                        elif resp.status_code == 503:
                            logger.debug("Rate limited by MusicBrainz, sleeping...")
                            await asyncio.sleep(1 * (attempt + 1))
                            continue
                        elif resp.status_code == 404:
                             logger.warning(f"Artist not found in MusicBrainz: {mbid}")
                             break
                    except Exception as e:
                         logger.warning(f"MB Fetch Error (Attempt {attempt+1}): {e}")
                         await asyncio.sleep(1)

            wikidata_url = None
            spotify_id = None
            spotify_candidates = []
            
            if mb_data:
                # Update Core Info
                if mb_data.get("name"): metadata["name"] = mb_data["name"]
                if mb_data.get("sort-name"): metadata["sort_name"] = mb_data["sort-name"]
                metadata["musicbrainz_url"] = f"{get_musicbrainz_root_url()}/artist/{mbid}"

                logger.debug(f"Processsing relations for {metadata['name']}...")
                
                # Relations
                relations = mb_data.get("relations", [])
                for rel in relations:
                    target = rel.get("url", {}).get("resource")
                    type_ = rel.get("type", "")
                    
                    if type_ == "official homepage" and not metadata["homepage"]:
                        metadata["homepage"] = target
                        logger.debug(f"data source: MusicBrainz (Homepage) -> {target}")
                    elif type_ == "wikidata":
                        wikidata_url = target
                        logger.debug(f"data source: MusicBrainz (Wikidata) -> {target}")
                    elif "tidal.com" in target:
                         metadata["tidal_url"] = target
                         logger.debug(f"data source: MusicBrainz (Tidal) -> {target}")
                    elif "qobuz.com" in target:
                         # We accept any Qobuz artist link provided by MB
                         metadata["qobuz_url"] = target
                         logger.debug(f"data source: MusicBrainz (Qobuz) -> {target}")
                    elif "discogs.com" in target:
                         metadata["discogs_url"] = target
                         logger.debug(f"data source: MusicBrainz (Discogs) -> {target}")
                    elif "spotify.com" in target and type_ in ("streaming", "free streaming"):
                         # Collect all candidate Spotify URLs/IDs from MB
                         parts = target.split("/")
                         if parts:
                             cand_id = parts[-1].split("?")[0]
                             if cand_id and not any(cand_id == c[0] for c in spotify_candidates):
                                 spotify_candidates.append((cand_id, target))
                                 logger.debug(f"data source: MusicBrainz (Spotify candidate) -> {target}")
                
                # Genres
                if mb_data.get("genres"):
                    metadata["genres"] = [
                        {"name": g["name"], "count": g.get("count", 0)} 
                        for g in mb_data["genres"]
                    ]
                    # Sort by count descending
                    metadata["genres"].sort(key=lambda x: x["count"], reverse=True)
                    logger.debug(f"Found {len(metadata['genres'])} genres for {artist_name}")

            if fetch_artwork:
                fanart = await fetch_fanart_artist_images(client, mbid)
                if fanart.get("thumb"):
                    metadata["image_url"] = fanart["thumb"]
                    metadata["image_source"] = "fanart.tv"
                if fanart.get("background"):
                    metadata["background_url"] = fanart["background"]
                    metadata["background_source"] = "fanart.tv"
            
            # 2. Wikipedia (Bio via Wikidata OR Known URL)
            # Logic: If we have a wikipedia_url (known or from relations? wait relations give wikidata not wikipedia),
            # we need to handle that. MB relations gives Wikidata usually, not direct Wikipedia.
            # But if known_wikipedia_url is passed, use it.
            
            target_wiki_url = metadata["wikipedia_url"] # Starts with known_url
            
            # If we have a Wikidata URL from MB, use it to resolve Wikipedia if we don't have one
            if wikidata_url and fetch_bio and not target_wiki_url:
                try:
                    logger.debug(f"Fetching Wikipedia link via Wikidata ({wikidata_url})...")
                    qid = wikidata_url.split("/")[-1]
                    wd_api = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
                    wd_resp = await client.get(wd_api)
                    if wd_resp.status_code == 200:
                        wd_data = wd_resp.json()
                        entities = wd_data.get("entities", {})
                        entity = entities.get(qid, {})
                        sitelinks = entity.get("sitelinks", {})
                        enwiki = sitelinks.get("enwiki", {})
                        wiki_title = enwiki.get("title")
                        
                        if wiki_title:
                            target_wiki_url = f"https://en.wikipedia.org/wiki/{wiki_title}"
                            metadata["wikipedia_url"] = target_wiki_url
                except Exception as e:
                     logger.warning(f"Wikidata resolution failed: {e}")

            if target_wiki_url and fetch_bio:
                 # Fetch bio extract from Wikipedia REST API
                 # Extract title from URL
                 # URL format: https://en.wikipedia.org/wiki/Title_Here
                 try:
                     wiki_title = target_wiki_url.split("/wiki/")[-1]
                     if wiki_title:
                        logger.debug(f"Fetching bio from Wikipedia for {wiki_title}...")
                        from urllib.parse import quote, unquote
                        # Decode first in case it's encoded, then re-quote for API?
                        # Actually the API handles it, but let's be safe.
                        safe_title = unquote(wiki_title)
                        
                        wiki_summary_url = f"{WIKI_API_ROOT}/{quote(safe_title)}"
                        wiki_resp = await client.get(wiki_summary_url)
                        if wiki_resp.status_code == 200:
                            wiki_data = wiki_resp.json()
                            extract = wiki_data.get("extract")
                            if extract:
                                metadata["bio"] = extract
                                logger.debug(f"Bio fetched: {len(extract)} characters")
                 except Exception as e:
                     logger.warning(f"Wikipedia bio fetch failed for {target_wiki_url}: {e}")

            # 2b. Wikidata Fallback for Missing External Links
            # If we have a Wikidata URL and fetch_links is enabled, try to fill missing links
            if wikidata_url and fetch_links:
                try:
                    # Check which links are missing
                    existing_links = {
                        "spotify_url": metadata.get("spotify_url"),
                        "tidal_url": metadata.get("tidal_url"),
                        "qobuz_url": metadata.get("qobuz_url"),
                        "lastfm_url": metadata.get("lastfm_url"),
                        "discogs_url": metadata.get("discogs_url"),
                        "homepage": metadata.get("homepage"),
                    }
                    
                    # Fetch missing links from Wikidata
                    wikidata_links = await fetch_wikidata_external_links(client, wikidata_url, existing_links)
                    
                    # Merge Wikidata links into metadata (only for missing links)
                    for service, url in wikidata_links.items():
                        if not metadata.get(service):
                            metadata[service] = url
                            logger.debug(f"data source: Wikidata ({service}) -> {url}")
                            
                except Exception as e:
                    logger.warning(f"Wikidata fallback failed: {e}")

            # 3. Last.fm (Top Tracks & Similar Artists)
            if fetch_top_tracks:
                logger.debug(f"Fetching Top Tracks from Last.fm for {artist_name}...")
                metadata["top_tracks"] = await fetch_lastfm_top_tracks(mbid, artist_name)
                logger.debug(f"Found {len(metadata['top_tracks'])} top tracks")

            if fetch_similar_artists:
                 logger.debug(f"Fetching Similar Artists from Last.fm for {artist_name}...")
                 metadata["similar_artists"] = await fetch_lastfm_similar_artists(mbid, artist_name)
                 logger.debug(f"Found {len(metadata['similar_artists'])} similar artists")

            if fetch_links:
                 logger.debug(f"Fetching Last.fm URL for {artist_name}...")
                 metadata["lastfm_url"] = await fetch_lastfm_artist_url(mbid)

            # 4. Spotify (Artwork & Links)
            # We need to resolve Spotify ID if we want artwork OR if we want to store the Spotify link
            if (fetch_spotify_artwork or fetch_links) and not SPOTIFY_SCANNING_DISABLED:
                logger.debug("Checking Spotify credentials for artwork...")
                token = await get_spotify_token(client)
                if token:
                    sp_headers = {"Authorization": f"Bearer {token}"}

                    # If we have multiple candidates from MB, pick the best one using Spotify metadata
                    if spotify_candidates:
                        try:
                            picked_id, picked_url = await _pick_best_spotify_candidate(
                                client, sp_headers, spotify_candidates, metadata["name"]
                            )
                            if picked_id and picked_url:
                                spotify_id = picked_id
                                metadata["spotify_url"] = picked_url
                                logger.debug(f"Selected Spotify candidate from MB list: {spotify_id}")
                        except Exception as e:
                            logger.warning(f"Spotify candidate selection failed: {e}")

                    # If no ID chosen yet, try a strict search
                    if not spotify_id:
                         try:
                            logger.debug(f"No Spotify ID found in MB. Searching Spotify for 'artist:{metadata['name']}'...")
                            from urllib.parse import quote
                            q = quote(metadata["name"])
                            search_url = f"{SPOTIFY_API_ROOT}/search?q=artist:{q}&type=artist&limit=3"
                            s_resp = await client.get(search_url, headers=sp_headers)
                            if s_resp.status_code == 429: raise RuntimeError("Spotify Rate Limit Exceeded")
                            if s_resp.status_code == 200:
                                 items = s_resp.json().get("artists", {}).get("items", [])
                                 if items:
                                     # Choose the best search result by name similarity
                                     scored = []
                                     for it in items:
                                         scored.append(( _similarity(it["name"], metadata["name"]), it))
                                     scored.sort(key=lambda x: (x[0], x[1].get("popularity", 0)), reverse=True)
                                     best = scored[0]
                                     if best[0] >= 0.6:
                                          spotify_id = best[1]["id"]
                                          metadata["spotify_url"] = best[1]["external_urls"]["spotify"]
                                          logger.debug(f"Found match via search: {spotify_id}")
                         except Exception as e:
                             logger.warning(f"Spotify Search Failed: {e}")

                    if spotify_id:
                        try:
                            # Get Artist (Image)
                            if fetch_artwork:
                                logger.debug(f"Fetching Spotify Artist details (Bio/Image) for {spotify_id}...")
                                art_resp = await client.get(f"{SPOTIFY_API_ROOT}/artists/{spotify_id}", headers=sp_headers)
                                if art_resp.status_code == 429: raise RuntimeError("Spotify Rate Limit Exceeded")
                                if art_resp.status_code == 200:
                                    images = art_resp.json().get("images", [])
                                    if images and not metadata["image_url"]:
                                        metadata["image_url"] = images[0]["url"]
                                        metadata["image_source"] = "spotify"
                        except RuntimeError as re:
                             # Re-raise critical errors like Rate Limit
                             raise re
                        except Exception as e:
                            logger.warning(f"Spotify Artwork Fetch Failed: {e}")
                else:
                    logger.debug("No Spotify token available (credentials missing or failed).")
                    # Fallback: if only one MB candidate, preserve that URL even without token
                    if spotify_candidates and len(spotify_candidates) == 1 and not metadata["spotify_url"]:
                        metadata["spotify_url"] = spotify_candidates[0][1]
            elif (fetch_top_tracks or fetch_spotify_artwork) and SPOTIFY_SCANNING_DISABLED:
                logger.debug("Spotify scanning disabled; skipping Spotify API calls.")

            # 4. MusicBrainz Singles & Albums (Release Groups)
            if bio_only and not (fetch_links or fetch_singles):
                 logger.debug("Bio-only mode: Skipping Release Groups and Link Resolution.")
                 return metadata

            if fetch_singles:
                logger.debug("Fetching Singles (Release Groups) from MusicBrainz...")
                singles = await fetch_artist_release_groups(mbid, "single", client)
                metadata["singles"] = singles

            if fetch_metadata or fetch_links:
                logger.debug("Fetching Albums (Release Groups) from MusicBrainz...")
                albums = await fetch_artist_release_groups(mbid, "album", client)
                # Optimization: We used to resolve links for every missing album here.
                # User requested to skip this expensive lookup.
                # We will rely on Release Group MBIDs for linking.
                metadata["albums"] = albums

                logger.debug("Fetching EPs (Release Groups) from MusicBrainz...")
                eps = await fetch_artist_release_groups(mbid, "ep", client)
                # Skip link resolution for EPs when we already have them locally; only missing-albums flow needs links.
                metadata["albums"].extend(eps)

    except Exception as e:
        logger.error(f"Critical error fetching metadata for {artist_name}: {e}")

    return metadata

async def fetch_artist_release_groups(mbid: str, type_str: str, client: httpx.AsyncClient):
    """
    Generic fetch for Release Groups (Albums or Singles).
    
    For Singles: Strictly filters for OFFICIAL releases in US/GB/XW.
    For Others: Uses standard RG browse (filters secondary types).
    """
    results = []
    try:
        offset = 0
        limit = 100
        seen_titles = set()
        
        # Strategy Switch: "release" browse for Singles (Strict), "release-group" browse for others (Faster)
        use_release_browse = (type_str == "single")
        
        base_endpoint = "release" if use_release_browse else "release-group"
        extra_query = "&status=official" if use_release_browse else ""
        inc_params = "release-groups+artist-credits" if use_release_browse else "artist-credits"
        
        # For releases, we will filter by country client-side or we could add ?country= but that only allows one?
        # MB API doesn't support multiple countries in one param easily. We'll filter client-side.
        
        while True:
            await mb_limiter.acquire()
            url = f"{MB_API_ROOT}/{base_endpoint}?artist={mbid}&type={type_str}&fmt=json&limit={limit}&offset={offset}&inc={inc_params}{extra_query}"
            resp = await client.get(url)
            
            if resp.status_code != 200:
                break
                
            data = resp.json()
            # Key differs based on endpoint
            items = data.get("releases", []) if use_release_browse else data.get("release-groups", [])
            
            if not items:
                break
            
            for item in items:
                 # Extract RG from item
                 if use_release_browse:
                     rg = item.get("release-group", {})
                     # Check Country
                     country = item.get("country", "")
                     if country not in ("US", "GB", "XW"):
                         continue
                     release_date = item.get("date") # Use release date for sorting preference? RG date is first-release-date
                 else:
                     rg = item
                     release_date = None # Will use RG first-release-date
                 
                 rg_id = rg.get("id")
                 if not rg_id: continue

                 # 1. Primary Artist Check (on the Item or RG)
                 credits = item.get("artist-credit", [])
                 if not any(c.get("artist", {}).get("id") == mbid for c in credits):
                     continue
                
                 # 2. Secondary Type Filter (Strict)
                 # We want Studio Albums/Singles. Exclude Live, Remix, Demo, etc.
                 secondary = rg.get("secondary-types", [])
                 if secondary:
                     continue
                 
                 title = rg.get("title")
                 norm_title = title.lower().strip()
                 
                 if norm_title in seen_titles:
                     continue
                 seen_titles.add(norm_title)
                 
                 # Prefer earliest date from RG, but for ordering we might use what we have
                 final_date = rg.get("first-release-date")
                 
                 results.append({
                     "mbid": rg_id,
                     "title": title,
                     "date": final_date,
                     "musicbrainz_url": f"{get_musicbrainz_root_url()}/release-group/{rg_id}"
                 })
            
            if len(items) < limit:
                break
            offset += limit
            
            # Safety break for massive catalogues if browsing releases
            if use_release_browse and offset > 2000:
                logger.warning(f"Hit strict limit browsing releases for {mbid}")
                break
            
        # Sort by date
        results.sort(key=lambda x: x["date"] or "", reverse=True)
        
    except Exception as e:
        logger.error(f"Error fetching {type_str} for {mbid}: {e}")
        
    return results

async def fetch_best_release_match(rg_id: str, client: httpx.AsyncClient):
    """
    Fetches releases for a Release Group and prioritizes:
    1. Digital Media
    2. Worldwide (XW)
    3. Date (descending)
    
    Returns (dict) release_data with 'url_rels'
    """
    try:
        await mb_limiter.acquire()
        # Fetch releases with media and URL rels
        url = f"{MB_API_ROOT}/release?release-group={rg_id}&inc=url-rels+media&fmt=json&limit=100"
        resp = await client.get(url)
        if resp.status_code != 200: return None
        
        data = resp.json()
        releases = data.get("releases", [])
        if not releases: return None
        
        # Scoring Helper
        def score_release(rel):
            score = 0
            
            # 1. Media Format (Digital > CD > Vinyl)
            media = rel.get("media", [])
            formats = []
            for m in media:
                fmt = m.get("format")
                if fmt:
                    formats.append(fmt.lower())
            if "digital media" in formats: score += 1000
            elif "cd" in formats: score += 500
            
            # 2. Country (XW > US/GB > Others)
            country = rel.get("country", "")
            if country == "XW": score += 100
            elif country in ["US", "GB"]: score += 50
            
            # 3. Date (Newer is better for links?) 
            # Actually, usually main release is earliest. But re-issues have links.
            # User said: "prioritise digital media, then worlwide, then by date"
            # We use date as tie breaker. 
            return score

        # Sort: Score Desc, Date Desc
        releases.sort(key=lambda x: (score_release(x), x.get("date", "")), reverse=True)
        
        best = releases[0]
        best_release_id = best.get("id")
        
        # Extract Links from ALL releases in the group to improve hit rate
        # We process 'best' first to prioritize its links if duplicates (though set handles that)
        # But actually, we just want ANY valid link.
        
        links = []
        seen_urls = set()
        
        # Helper to add unique links
        def add_links_from_release(release):
            for rel in release.get("relations", []):
                target = rel.get("url", {}).get("resource", "")
                if not target or target in seen_urls: continue
                
                l_type = None
                if "tidal.com" in target: l_type = "tidal"
                elif "qobuz.com" in target: l_type = "qobuz"
                elif "musicbrainz.org" in target: l_type = "musicbrainz"
                
                if l_type:
                    links.append({"type": l_type, "url": target})
                    seen_urls.add(target)

        # 1. Add links from the BEST match first (highest priority if we were ranking, but we just list them)
        add_links_from_release(best)
        
        # 2. Add links from all other releases
        for rel in releases:
            if rel.get("id") == best_release_id: continue
            add_links_from_release(rel)
        
        # Collect ALL release IDs associated with this group for backfilling
        release_ids = [r["id"] for r in releases]
        
        return {
            "links": links,
            "release_ids": release_ids,
            "primary_release_id": best_release_id,
        }
        
    except Exception as e:
        logger.warning(f"Error resolving release links for {rg_id}: {e}")
        return {"links": [], "release_ids": [], "primary_release_id": None}

async def fetch_track_credits(mb_recording_id: str, release_track_mbid: str = None):
    """
    Fetch artist credits for a track.
    Returns list of (mbid, name).
    """
    target_id = mb_recording_id or release_track_mbid
    if not target_id: return []

    credits = []
    try:
        async with httpx.AsyncClient(headers={"User-Agent": "Jamarr/0.1 ( jamarr@example.com )"}) as client:
            await mb_limiter.acquire()
            url = f"{MB_API_ROOT}/recording/{target_id}?inc=artist-credits&fmt=json"
            
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                for ac in data.get("artist-credit", []):
                    a = ac.get("artist", {})
                    if a.get("id"):
                        credits.append((a["id"], a.get("name")))
    except Exception as e:
        logger.warning(f"Track credits fetch failed: {e}")
        
    return credits
