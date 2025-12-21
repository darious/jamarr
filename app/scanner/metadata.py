import httpx
import json
import time
import asyncio
from bs4 import BeautifulSoup
import logging
import base64
import re
from app.config import get_spotify_credentials, get_musicbrainz_root_url, get_musicbrainz_rate_limit, get_qobuz_region

logger = logging.getLogger(__name__)

MB_API_ROOT = f"{get_musicbrainz_root_url()}/ws/2"
WIKI_API_ROOT = "https://en.wikipedia.org/api/rest_v1/page/summary"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_ROOT = "https://api.spotify.com/v1"

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

async def match_track_to_library(db, artist_mbid, track_name, album_name=None):
    """
    Match external track to local library track.
    Returns track_id if found, None otherwise.
    """
    # Normalize for fuzzy matching
    normalized_track = track_name.lower().strip()
    
    query = """
        SELECT t.id FROM tracks t
        JOIN track_artists ta ON t.id = ta.track_id
        WHERE ta.mbid = ?
        AND LOWER(TRIM(t.title)) = ?
    """
    params = [artist_mbid, normalized_track]
    
    # Add album filter if provided
    if album_name:
        query += " AND LOWER(TRIM(t.album)) = ?"
        params.append(album_name.lower().strip())
    
    query += " LIMIT 1"
    
    async with db.execute(query, params) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else None

async def fetch_artist_metadata(mbid: str, artist_name: str, local_release_group_ids: set = None, bio_only: bool = False):
    """
    Fetches comprehensive artist metadata from MusicBrainz + Spotify + Wikidata.
    """
    if local_release_group_ids is None:
        local_release_group_ids = set()

    metadata = {
        "mbid": mbid,
        "name": artist_name,
        "sort_name": artist_name, # Default to name
        "bio": None,
        "image_url": None,
        "spotify_url": None,
        "homepage": None,
        "wikipedia_url": None,
        "qobuz_url": None,
        "tidal_url": None,
        "musicbrainz_url": None,
        "similar_artists": [],
        "top_tracks": [],
        "singles": [],
        "albums": [],
        "last_updated": time.time()
    }

    try:
        async with httpx.AsyncClient(headers={"User-Agent": "Jamarr/0.1 ( jamarr@example.com )"}) as client:
            # 1. MusicBrainz Core Data & Relations
            logger.debug(f"Fetching Core Data from MusicBrainz for {artist_name} ({mbid})...")
            await mb_limiter.acquire()
            mb_url = f"{MB_API_ROOT}/artist/{mbid}?inc=url-rels&fmt=json"
            
            mb_data = None
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
                    elif "spotify.com" in target and type_ in ("streaming", "free streaming"):
                         metadata["spotify_url"] = target
                         logger.debug(f"data source: MusicBrainz (Spotify) -> {target}")
                         # Extract ID
                         parts = target.split("/")
                         if parts:
                             spotify_id = parts[-1].split("?")[0]
            
            # 2. Wikipedia (Bio via Wikidata)
            if wikidata_url:
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
                            metadata["wikipedia_url"] = f"https://en.wikipedia.org/wiki/{wiki_title}"
                            
                            # Fetch bio extract from Wikipedia REST API
                            try:
                                logger.debug(f"Fetching bio from Wikipedia for {wiki_title}...")
                                from urllib.parse import quote
                                wiki_summary_url = f"{WIKI_API_ROOT}/{quote(wiki_title)}"
                                wiki_resp = await client.get(wiki_summary_url)
                                if wiki_resp.status_code == 200:
                                    wiki_data = wiki_resp.json()
                                    extract = wiki_data.get("extract")
                                    if extract:
                                        metadata["bio"] = extract
                                        logger.debug(f"Bio fetched: {len(extract)} characters")
                            except Exception as e:
                                logger.warning(f"Wikipedia bio fetch failed for {wiki_title}: {e}")
                except Exception as e:
                    logger.warning(f"Wikipedia fetch failed for {artist_name}: {e}")

            # 3. Spotify (Image, Similar, Top Tracks)
            # Only proceed if we have credentials
            logger.debug("Checking Spotify credentials...")
            token = await get_spotify_token(client)
            if token:
                sp_headers = {"Authorization": f"Bearer {token}"}
                
                # If no ID from MB, try to search (Exact match only? Or best guess?)
                # Safety: If we search, we must be careful.
                # Use strict search: "artist:Name"
                if not spotify_id:
                     try:
                        logger.debug(f"No Spotify ID found in MB. Searching Spotify for 'artist:{metadata['name']}'...")
                        from urllib.parse import quote
                        q = quote(metadata["name"])
                        search_url = f"{SPOTIFY_API_ROOT}/search?q=artist:{q}&type=artist&limit=1"
                        s_resp = await client.get(search_url, headers=sp_headers)
                        if s_resp.status_code == 200:
                             items = s_resp.json().get("artists", {}).get("items", [])
                             if items:
                                 # Safety Check: Is name close enough?
                                 if items[0]["name"].lower() == metadata["name"].lower():
                                      spotify_id = items[0]["id"]
                                      metadata["spotify_url"] = items[0]["external_urls"]["spotify"]
                                      logger.debug(f"Found match: {spotify_id}")
                     except Exception as e:
                         logger.warning(f"Spotify Search Failed: {e}")

                if spotify_id:
                     try:
                         # Get Artist (Image)
                         logger.debug(f"Fetching Spotify Artist details (Bio/Image) for {spotify_id}...")
                         art_resp = await client.get(f"{SPOTIFY_API_ROOT}/artists/{spotify_id}", headers=sp_headers)
                         if art_resp.status_code == 200:
                             images = art_resp.json().get("images", [])
                             if images:
                                 metadata["image_url"] = images[0]["url"]

                         # Get Related Artists
                         logger.debug(f"Fetching Related Artists for: {spotify_id}")
                         rel_resp = await client.get(f"{SPOTIFY_API_ROOT}/artists/{spotify_id}/related-artists", headers=sp_headers)
                         if rel_resp.status_code == 200:
                             rel_data = rel_resp.json()
                             metadata["similar_artists"] = [a["name"] for a in rel_data.get("artists", [])[:10]]
                             logger.debug(f"Found {len(metadata['similar_artists'])} similar artists via API")
                         else:
                             logger.debug(f"Spotify Related API Failed: {rel_resp.status_code}. Attempting scrape...")
                             # Fallback: Scrape public page
                             try:
                                 from bs4 import BeautifulSoup
                                 page_url = f"https://open.spotify.com/artist/{spotify_id}"
                                 page_resp = await client.get(page_url)
                                 if page_resp.status_code == 200:
                                     soup = BeautifulSoup(page_resp.text, "html.parser")
                                     # Look for "Fans also like"
                                     fans_header = soup.find(string="Fans also like")
                                     if fans_header:
                                         # Heuristic: Find all links to /artist/ that are NOT the current artist.
                                         seen = set()
                                         similar = []
                                         for a in soup.find_all("a", href=True):
                                             href = a["href"]
                                             if href.startswith("/artist/") and spotify_id not in href:
                                                 name = a.get_text(strip=True)
                                                 if name and name not in seen:
                                                     if name.lower() != "see all":
                                                         seen.add(name)
                                                         similar.append(name)
                                         
                                         if similar:
                                             metadata["similar_artists"] = similar[:10]
                                             logger.debug(f"Scraped {len(similar)} potential similar artists")
                             except Exception as scrape_e:
                                 logger.error(f"Scraping failed: {scrape_e}")




                         # Get Top Tracks
                         logger.debug("Fetching Top Tracks from Spotify...")
                         top_resp = await client.get(f"{SPOTIFY_API_ROOT}/artists/{spotify_id}/top-tracks?market=US", headers=sp_headers)
                         if top_resp.status_code == 200:
                             top_data = top_resp.json()
                             tracks = []
                             for t in top_data.get("tracks", [])[:10]:
                                 tracks.append({
                                     "name": t["name"],
                                     "album": t["album"]["name"],
                                     "date": t["album"]["release_date"],
                                     "duration_ms": t["duration_ms"],
                                     "popularity": t["popularity"],
                                     "preview_url": t["preview_url"]
                                 })
                             metadata["top_tracks"] = tracks
                     except Exception as e:
                         logger.warning(f"Spotify Data Fetch Failed: {e}")
            else:
                logger.debug("No Spotify token available (credentials missing or failed).")

            # 4. MusicBrainz Singles & Albums (Release Groups)
            # Fetch directly from MB
            # 4. MusicBrainz Singles & Albums (Release Groups)
            if bio_only:
                 logger.debug("Bio-only mode: Skipping Release Groups and Link Resolution.")
                 return metadata

            logger.debug("Fetching Singles (Release Groups) from MusicBrainz...")
            singles = await fetch_artist_release_groups(mbid, "single", client)
            # Skip link resolution for singles as per user request (optimisation)
            metadata["singles"] = singles
            
            logger.debug("Fetching Albums (Release Groups) from MusicBrainz...")
            albums = await fetch_artist_release_groups(mbid, "album", client)
            for a in albums:
                 logger.debug(f"Resoving links for album: {a['title']} ({a['mbid']})")
                 res = await fetch_best_release_match(a['mbid'], client)
                 a['links'] = res['links']
                 a['release_ids'] = res['release_ids']
            metadata["albums"] = albums
            
            logger.debug("Fetching EPs (Release Groups) from MusicBrainz...")
            eps = await fetch_artist_release_groups(mbid, "ep", client)
            for e in eps:
                 # Only resolve links if we have files for this EP locally
                 if e['mbid'] in local_release_group_ids:
                     logger.debug(f"Resolving links for EP (Local): {e['title']} ({e['mbid']})")
                     res = await fetch_best_release_match(e['mbid'], client)
                     e['links'] = res['links']
                     e['release_ids'] = res['release_ids']
                 else:
                     # logger.debug(f"Skipping links for EP (Remote): {e['title']}")
                     pass
            
            # Merge EPs into Albums
            metadata["albums"].extend(eps)

    except Exception as e:
        logger.error(f"Critical error fetching metadata for {artist_name}: {e}")

    return metadata

async def fetch_artist_release_groups(mbid: str, type_str: str, client: httpx.AsyncClient):
    """
    Generic fetch for Release Groups (Albums or Singles).
    Strictly filters out Compilation, Live, Remix, etc. unless it's the primary type.
    """
    results = []
    try:
        offset = 0
        limit = 100
        seen_titles = set()
        
        while True:
            await mb_limiter.acquire()
            url = f"{MB_API_ROOT}/release-group?artist={mbid}&type={type_str}&fmt=json&limit={limit}&offset={offset}&inc=artist-credits"
            resp = await client.get(url)
            
            if resp.status_code != 200:
                break
                
            data = resp.json()
            groups = data.get("release-groups", [])
            
            for rg in groups:
                 # 1. Primary Artist Check
                 credits = rg.get("artist-credit", [])
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
                 
                 results.append({
                     "mbid": rg.get("id"),
                     "title": title,
                     "date": rg.get("first-release-date"),
                     "musicbrainz_url": f"{get_musicbrainz_root_url()}/release-group/{rg.get('id')}"
                 })
            
            if len(groups) < limit:
                break
            offset += limit
            
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
        
        # Extract Links
        links = []
        for rel in best.get("relations", []):
             target = rel.get("url", {}).get("resource", "")
             type_ = rel.get("type", "")
             if "tidal.com" in target:
                 links.append({"type": "tidal", "url": target})
             elif "qobuz.com" in target:
                 links.append({"type": "qobuz", "url": target})
             elif "spotify.com" in target:
                 links.append({"type": "spotify", "url": target})
        
        # Collect ALL release IDs associated with this group for backfilling
        release_ids = [r["id"] for r in releases]
        
        return {
            "links": links,
            "release_ids": release_ids
        }
        
    except Exception as e:
        logger.warning(f"Error resolving release links for {rg_id}: {e}")
        return {"links": [], "release_ids": []}

async def fetch_track_credits(mb_recording_id: str, mb_release_track_id: str = None):
    """
    Fetch artist credits for a track.
    Returns list of (mbid, name).
    """
    target_id = mb_recording_id or mb_release_track_id
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
