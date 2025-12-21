import httpx
import json
import time
import asyncio
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)

import base64

from app.config import get_spotify_credentials, get_musicbrainz_root_url, get_musicbrainz_rate_limit

MB_API_ROOT = f"{get_musicbrainz_root_url()}/ws/2"
WIKI_API_ROOT = "https://en.wikipedia.org/api/rest_v1/page/summary"


SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_ROOT = "https://api.spotify.com/v1"

_spotify_token = None
_token_expiry = 0

async def get_spotify_token(client: httpx.AsyncClient):
    global _spotify_token, _token_expiry
    if _spotify_token and time.time() < _token_expiry:
        return _spotify_token
    
    client_id, client_secret = get_spotify_credentials()
    if not client_id or not client_secret:
        logger.error("Spotify credentials not configured")
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

async def fetch_artist_metadata(mbid: str, artist_name: str):
    """
    Fetches artist metadata from MusicBrainz, Wikipedia, and Spotify.
    """
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
        "musicbrainz_url": None,
        "similar_artists": [],
        "top_tracks": [],
        "singles": [],
        "albums": [],
        "last_updated": time.time()
    }

    try:
        async with httpx.AsyncClient(headers={"User-Agent": "Jamarr/0.1 ( jamarr@example.com )"}) as client:
            # 1. MusicBrainz
            mb_url = f"{MB_API_ROOT}/artist/{mbid}?inc=url-rels&fmt=json"
            logger.debug(f"Fetching MB data from: {mb_url}")
            
            mb_data = None
            resp = None
            
            for attempt in range(3):
                try:
                    resp = await client.get(mb_url)
                    if resp.status_code == 200:
                        mb_data = resp.json()
                        break
                    elif resp.status_code == 503:
                        await asyncio.sleep(1 * (attempt + 1))
                        continue
                    else:
                        logger.warning(f"MusicBrainz returned status {resp.status_code} for {mbid}")
                        break
                except Exception as e:
                    logger.warning(f"Attempt {attempt + 1}/3 failed to fetch MB data for {artist_name}: {repr(e)}")
                    if attempt < 2:
                        await asyncio.sleep(1 * (attempt + 1))
                    # If we fail all attempts, we continue to check if we got partial data or proceed to other sources
            
            # Continue even if mb_data is None (we might fallback to other sources or partial data)
            # But the logic below depends on resp.status_code check usually
            
            if mb_data:
                # Mock a successful resp object logic or just use mb_data
                # The code below uses 'resp.status_code == 200' and 'resp.json()'
                # We can just change the condition to check mb_data
                pass
            
            wikidata_url = None
            spotify_id = None
            
            if mb_data:
                # mb_data already json()
                if mb_data.get("name"):
                    metadata["name"] = mb_data.get("name")
                metadata["sort_name"] = mb_data.get("sort-name")
                relations = mb_data.get("relations", [])
                logger.debug(f"Found {len(relations)} relations for {artist_name}")
                
                # Set MusicBrainz URL
                # Set MusicBrainz URL
                metadata["musicbrainz_url"] = f"{get_musicbrainz_root_url()}/artist/{mbid}"

                for rel in relations:
                    target = rel.get("url", {}).get("resource", "")
                    type_ = rel.get("type", "")
                    
                    if type_ == "official homepage" and not metadata["homepage"]:
                        metadata["homepage"] = target
                    elif type_ == "wikidata":
                        wikidata_url = target
                    elif type_ == "purchase for download" and "qobuz.com" in target:
                        # Logic: Find the best Qobuz link. Prioritize one with a numeric ID.
                        current_qobuz = metadata.get("qobuz_url")
                        new_qobuz = target
                        
                        # Try to extract ID from new link
                        new_id = None
                        try:
                             # 1. Regex to find the ID (last numeric component)
                             import re
                             match = re.search(r'/([0-9]+)(?:[\?#]|$)', target)
                             if match:
                                 new_id = match.group(1)
                             else:
                                 # 2. Fallback: split and look for digits
                                 parts = target.strip("/").split("/")
                                 for part in reversed(parts):
                                     clean_part = part.split("?")[0]
                                     if clean_part.isdigit():
                                         new_id = clean_part
                                         break
                                 
                                 # 3. Fallback: If no ID found in URL (e.g. /interpreter/bastille/...), fetch page to scrape ID
                                 if not new_id and "qobuz.com" in target:
                                     logger.debug(f"No ID in Qobuz URL, attempting to scrape: {target}")
                                     try:
                                         q_resp = await client.get(target, follow_redirects=True)
                                         if q_resp.status_code == 200:
                                             # Look for "artist/12345" in the final URL or content
                                             final_url = str(q_resp.url)
                                             match_final = re.search(r'/([0-9]+)(?:[\?#]|$)', final_url)
                                             if match_final:
                                                 new_id = match_final.group(1)
                                                 logger.debug(f"Found ID {new_id} from redirect to {final_url}")
                                             else:
                                                 # Look in HTML content for something like "artist/12345"
                                                 # Or typically canonical link: <link rel="canonical" href=".../artist/12345" />
                                                 # Or JSON-LD
                                                 match_content = re.search(r'qobuz\.com/.*/artist/([0-9]+)', q_resp.text)
                                                 if match_content:
                                                     new_id = match_content.group(1)
                                                     logger.debug(f"Found ID {new_id} in page content")
                                     except Exception as e:
                                         logger.warning(f"Failed to scrape Qobuz page: {e}")

                        except: pass
                        
                        # Logic to replace: 
                        # 1. If we have no link yet, take this one.
                        # 2. If this one has an ID, always take it (convert to play link).
                        
                        if not current_qobuz or new_id:
                            if new_id:
                                metadata["qobuz_url"] = f"https://play.qobuz.com/artist/{new_id}"
                                logger.debug(f"Converted Qobuz URL: {metadata['qobuz_url']}")
                            else:
                                if not current_qobuz: # Don't overwrite existing (potentially better) link with a generic one
                                    metadata["qobuz_url"] = target
                        
                        logger.debug(f"Found Qobuz URL: {target}")
                    elif type_ == "streaming" and "spotify.com" in target:
                        metadata["spotify_url"] = target
                        logger.debug(f"Found Spotify URL: {target}")
                        # Extract Spotify ID from URL (https://open.spotify.com/artist/ID)
                        parts = target.split("/")
                        if len(parts) > 0:
                            spotify_id = parts[-1].split("?")[0]
                            logger.debug(f"Extracted Spotify ID: {spotify_id}")

            # 2. Wikipedia (Bio)
            if wikidata_url:
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
                        wiki_api = f"{WIKI_API_ROOT}/{wiki_title}"
                        wiki_resp = await client.get(wiki_api)
                        if wiki_resp.status_code == 200:
                            wiki_data = wiki_resp.json()
                            metadata["bio"] = wiki_data.get("extract")

            # 3. Spotify (Image & Similar Artists)
            token = await get_spotify_token(client)
            if token:
                sp_headers = {"Authorization": f"Bearer {token}"}
                
                # If we don't have an ID yet, search by name
                if not spotify_id:
                    # Use the name fetching from MB if available
                    search_query = metadata.get("name") or artist_name
                    search_url = None
                    if search_query and search_query != "Unknown Artist":
                        logger.debug(f"Searching Spotify for: {search_query}")
                        from urllib.parse import quote
                        search_url = f"{SPOTIFY_API_ROOT}/search?q={quote(search_query)}&type=artist&limit=1"
                    if search_url:
                        s_resp = await client.get(search_url, headers=sp_headers)
                        if s_resp.status_code == 200:
                            s_data = s_resp.json()
                            items = s_data.get("artists", {}).get("items", [])
                            if items:
                                spotify_id = items[0]["id"]
                                metadata["spotify_url"] = items[0]["external_urls"]["spotify"]
                                logger.debug(f"Found Spotify ID via search: {spotify_id}")
                        else:
                            logger.error(f"Spotify Search Failed: {s_resp.status_code}")

                if spotify_id:
                    # Get Artist (Image)
                    logger.debug(f"Fetching Spotify Artist: {spotify_id}")
                    art_resp = await client.get(f"{SPOTIFY_API_ROOT}/artists/{spotify_id}", headers=sp_headers)
                    if art_resp.status_code == 200:
                        art_data = art_resp.json()
                        images = art_data.get("images", [])
                        if images:
                            metadata["image_url"] = images[0]["url"] # Largest image
                            logger.debug(f"Found Image URL: {metadata['image_url']}")
                    else:
                        logger.error(f"Spotify Artist Fetch Failed: {art_resp.status_code}")

                    # Get Related Artists
                    logger.debug(f"Fetching Related Artists for: {spotify_id}")
                    rel_resp = await client.get(f"{SPOTIFY_API_ROOT}/artists/{spotify_id}/related-artists?market=US", headers=sp_headers)
                    if rel_resp.status_code == 200:
                        rel_data = rel_resp.json()
                        metadata["similar_artists"] = [a["name"] for a in rel_data.get("artists", [])[:10]]
                        logger.debug(f"Found {len(metadata['similar_artists'])} similar artists via API")
                    else:
                        logger.debug(f"Spotify Related API Failed: {rel_resp.status_code}. Attempting scrape...")
                        # Fallback: Scrape public page
                        try:
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
                    logger.debug(f"Fetching Top Tracks for: {spotify_id}")
                    top_resp = await client.get(f"{SPOTIFY_API_ROOT}/artists/{spotify_id}/top-tracks?market=US", headers=sp_headers)
                    if top_resp.status_code == 200:
                        top_data = top_resp.json()
                        tracks = []
                        for t in top_data.get("tracks", [])[:10]: # Top 10
                            tracks.append({
                                "name": t["name"],
                                "album": t["album"]["name"],
                                "date": t["album"]["release_date"],
                                "duration_ms": t["duration_ms"],
                                "popularity": t["popularity"],
                                "preview_url": t["preview_url"]
                            })
                        metadata["top_tracks"] = tracks
                        logger.debug(f"Found {len(tracks)} top tracks")
                    else:
                        logger.error(f"Spotify Top Tracks Failed: {top_resp.status_code}")
            else:
                logger.error("Failed to get Spotify token")



            # 4. MusicBrainz Singles (Release Groups)
            metadata["singles"] = await fetch_artist_singles(mbid, client)
            
            # 5. MusicBrainz Albums (Missing Albums)
            metadata["albums"] = await fetch_artist_albums(mbid, metadata["name"], client)

    except Exception as e:
        logger.error(f"Error fetching metadata for {artist_name}: {e}")

    # Fallback: If no Qobuz URL found, generate a search link
    if not metadata["qobuz_url"]:
         # https://play.qobuz.com/search?q=Artist%20Name
         from urllib.parse import quote
         final_name = metadata.get("name") or artist_name
         if final_name and final_name != "Unknown Artist":
             encoded_name = quote(final_name)
             search_url = f"https://play.qobuz.com/search?q={encoded_name}&type=artists"
             metadata["qobuz_url"] = search_url
             logger.debug(f"Generated Qobuz search fallback for {final_name}")
             
             # User Request: "store the correct links when its found the relevant pages"
             # Attempt to resolve the search to a real artist page
             try:
                 logger.debug(f"Attempting to resolve Qobuz search: {search_url}")
                 # Note: play.qobuz.com is a SPA (Single Page App). Fetching the search URL directly might return mostly JS.
                 # The user said "scanner to do the search".
                 # We can try to search via their public web store search which is easier to scrape:
                 # https://www.qobuz.com/us-en/search?q=Artist&i=boutique
                 store_search_url = f"https://www.qobuz.com/us-en/search?q={encoded_name}&i=boutique"
                 
                 async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as resolution_client:
                    resp = await resolution_client.get(store_search_url, follow_redirects=True)
                    if resp.status_code == 200:
                        # Look for artist links: /interpreter/name/ID or /artist/ID
                        # Regex for store artist link: /interpreter/([a-z0-9-]+)/([0-9]+) or /artist/([0-9]+)
                        import re
                        # Prioritize /interpreter/name/ID links which are common in store results
                        match = re.search(r'href=".*?(?:/interpreter/[^/]+/|/artist/)([0-9]+)"', resp.text)
                        if match:
                            artist_id = match.group(1)
                            resolved_url = f"https://play.qobuz.com/artist/{artist_id}"
                            metadata["qobuz_url"] = resolved_url
                            logger.info(f"Resolved Qobuz Search to: {resolved_url}")
             except Exception as e:
                 logger.warning(f"Failed to resolve Qobuz search: {e}")

    return metadata

async def fetch_artist_singles(mbid: str, client: httpx.AsyncClient = None):
    """
    Fetches singles (Release Groups) for an artist from MusicBrainz.
    """
    singles = []
    should_close = False
    if client is None:
        client = httpx.AsyncClient(headers={"User-Agent": "Jamarr/0.1 ( jamarr@example.com )"})
        should_close = True
        
    try:
        offset = 0
        limit = 100
        seen_titles = set()

        while True:
            # https://musicbrainz.org/ws/2/release-group?artist=<MBID>&type=single&fmt=json
            rg_url = f"{MB_API_ROOT}/release-group?artist={mbid}&type=single&fmt=json&limit={limit}&offset={offset}&inc=artist-credits"
            logger.debug(f"Fetching singles from: {rg_url}")
            rg_resp = await client.get(rg_url)
            
            if rg_resp.status_code == 200:
                rg_data = rg_resp.json()
                release_groups = rg_data.get("release-groups", [])
                
                for rg in release_groups:
                    # Filter out if artist is not primary
                    credits = rg.get("artist-credit", [])
                    if not credits: continue
                    
                    # Check if primary artist ID matches
                    is_primary = False
                    for c in credits:
                        if c.get("artist", {}).get("id") == mbid:
                            is_primary = True
                            break
                    
                    if not is_primary:
                        continue

                    # Filter out "junk" secondary types (Remix, Live, etc.)
                    # If the user wants ONLY singles, we should exclude anything with a secondary type.
                    # Secondary types: Live, Remix, Compilation, Demo, DJ-mix, Mixtape/Street, etc.
                    secondary_types = rg.get("secondary-types", [])
                    if secondary_types:
                        logger.debug(f"Skipping {rg.get('title')} due to secondary types: {secondary_types}")
                        continue

                    title = rg.get("title")
                    
                    # Deduplicate by title
                    norm_title = title.lower().strip()
                    if norm_title in seen_titles:
                        continue
                    seen_titles.add(norm_title)

                    singles.append({
                        "mbid": rg.get("id"),
                        "title": title,
                        "date": rg.get("first-release-date"),
                        "artist": rg.get("artist-credit-phrase")
                    })

                # Pagination check
                count = rg_data.get("release-group-count", 0)
                if len(release_groups) < limit or (offset + len(release_groups)) >= count:
                    break
                
                offset += limit
                await asyncio.sleep(1.1) # Rate limit
            else:
                logger.error(f"MusicBrainz Singles Fetch Failed: {rg_resp.status_code}")
                break
            
        # Sort by date descending
        singles.sort(key=lambda x: x["date"] or "", reverse=True)
        logger.debug(f"Found {len(singles)} singles")
            
    except Exception as e:
        logger.error(f"Error fetching singles for {mbid}: {e}")
    finally:
        if should_close:
            await client.aclose()
            
    return singles



import time
import asyncio

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
# MB: 1 req/sec (technically allows bursts but be safe)
mb_limit_val = get_musicbrainz_rate_limit()
mb_limiter = RateLimiter(rate_limit=mb_limit_val, burst_limit=5 if mb_limit_val is None else 2)
# Qobuz: Unknown, be polite (2 req/sec)
qobuz_limiter = RateLimiter(rate_limit=2.0, burst_limit=5)
# Store Search: Be very polite (1 req/sec)
store_limiter = RateLimiter(rate_limit=1.0, burst_limit=1)

async def _process_single_album(rg, artist_name, client):
    """
    Process a single release group: fetch MB relations or search Qobuz.
    """
    title = rg.get("title")
    first_date = rg.get("first-release-date")
    
    qobuz_url = None
    qobuz_id = None
    
    # 1. MusicBrainz Direct Lookup
    try:
        await mb_limiter.acquire()
        rg_details_url = f"{MB_API_ROOT}/release-group/{rg.get('id')}?inc=releases&fmt=json"
        rg_d_resp = await client.get(rg_details_url)
        
        if rg_d_resp.status_code == 200:
            rg_full = rg_d_resp.json()
            releases = rg_full.get("releases", [])
            
            # Check first few releases
            for rel in releases[:5]:
                rel_id = rel.get("id")
                await mb_limiter.acquire()
                rel_url = f"{MB_API_ROOT}/release/{rel_id}?inc=url-rels&fmt=json"
                r_resp = await client.get(rel_url)
                
                if r_resp.status_code == 200:
                    r_data = r_resp.json()
                    for relation in r_data.get("relations", []):
                        res_url = relation.get("url", {}).get("resource", "")
                        if "qobuz.com" in res_url and "/album/" in res_url:
                            if "open.qobuz.com" in res_url or "play.qobuz.com" in res_url or "www.qobuz.com" in res_url:
                                    parts = res_url.split("/")
                                    possible_id = parts[-1]
                                    if possible_id:
                                        qobuz_id = possible_id
                                        qobuz_url = f"https://play.qobuz.com/album/{qobuz_id}"
                                        logger.debug(f"Resolved Qobuz ID from MusicBrainz relation: {qobuz_id}")
                                        break
                    if qobuz_id: break
                    
    except Exception as e:
        logger.warning(f"MB Qobuz lookup failed for {title}: {e}")

    # 2. Search Fallback
    if not qobuz_id:
        from urllib.parse import quote
        query = f"{title} {artist_name}"
        encoded_query = quote(query)
        store_search_url = f"https://www.qobuz.com/us-en/search?q={encoded_query}"
        
        try:
            await store_limiter.acquire()
            s_resp = await client.get(store_search_url, follow_redirects=True)
            if s_resp.status_code == 200:
                import re
                matches = re.findall(r'href=".*?(?:/album/([^/]+)/)([0-9a-zA-Z]+)"', s_resp.text)
                
                best_match_id = None
                
                # Normalize artist
                artist_parts = [p.lower() for p in artist_name.split() if len(p) > 2]
                if not artist_parts: artist_parts = [artist_name.lower()]

                def clean_slug_title(t):
                    t = t.lower().strip()
                    t = t.replace("×", "x").replace("+", "plus").replace("÷", "divide").replace("=", "equals")
                    if t.startswith("the "): t = t[4:]
                    elif t.startswith("a "): t = t[2:]
                    elif t.startswith("an "): t = t[3:]
                    return "".join([c if c.isalnum() or c.isspace() else "" for c in t]).split()

                title_words = clean_slug_title(title)
                
                for slug, q_id in matches:
                    slug_clean = slug.lower().replace("-", " ")
                    if not all(part in slug_clean for part in artist_parts): continue
                    if title_words:
                        first_word = title_words[0]
                        if not slug_clean.startswith(first_word): continue
                    
                    if q_id.isdigit():
                        best_match_id = q_id
                        break 
                    if best_match_id is None:
                        best_match_id = q_id
                
                if best_match_id:
                    qobuz_id = best_match_id
                    qobuz_url = f"https://play.qobuz.com/album/{qobuz_id}"
                    logger.debug(f"Resolved Qobuz album {title} -> {qobuz_id}")
                else:
                    qobuz_url = f"https://play.qobuz.com/search?q={encoded_query}&type=albums"
            else:
                    qobuz_url = f"https://play.qobuz.com/search?q={encoded_query}&type=albums"
                    
        except Exception as e:
            logger.warning(f"Qobuz resolution failed for {title}: {e}")
            qobuz_url = f"https://play.qobuz.com/search?q={encoded_query}&type=albums"

    return {
        "mbid": rg.get("id"),
        "title": title,
        "date": first_date,
        "artist": artist_name,
        "qobuz_url": qobuz_url,
        "qobuz_id": qobuz_id,
        "musicbrainz_url": f"{get_musicbrainz_root_url()}/release-group/{rg.get('id')}"
    }

async def fetch_artist_albums(mbid: str, artist_name: str, client: httpx.AsyncClient = None):
    """
    Fetches albums (Release Groups) from MusicBrainz, excluding EPs, Singles, Compilations, etc.
    Attempts to resolve Qobuz IDs for them.
    """
    albums = []
    should_close = False
    if client is None:
        client = httpx.AsyncClient(headers={"User-Agent": "Jamarr/0.1 ( jamarr@example.com )"})
        should_close = True
        
    try:
        offset = 0
        limit = 100
        seen_titles = set()
        
        all_rgs = []

        # 1. Gather all release groups first
        while True:
            # Type 'album'
            rg_url = f"{MB_API_ROOT}/release-group?artist={mbid}&type=album&fmt=json&limit={limit}&offset={offset}&inc=artist-credits"
            await mb_limiter.acquire()
            logger.debug(f"Fetching albums from: {rg_url}")
            rg_resp = await client.get(rg_url)
            
            if rg_resp.status_code == 200:
                rg_data = rg_resp.json()
                release_groups = rg_data.get("release-groups", [])
                
                for rg in release_groups:
                    # Filter out if artist is not primary
                    credits = rg.get("artist-credit", [])
                    if not credits: continue
                    
                    is_primary = False
                    for c in credits:
                        if c.get("artist", {}).get("id") == mbid:
                            is_primary = True
                            break
                    
                    if not is_primary:
                        continue

                    # Filter out secondary types (Compliance with user request: no compilations, live, remix)
                    secondary_types = rg.get("secondary-types", [])
                    if secondary_types:
                        # User explicit list: "not the +compliation, or + live or + remix, no EPs etc..."
                        # EPs are usually primary type 'EP', but here we requested type='album' so EPs shouldn't be here.
                        # But 'Live', 'Remix', 'Compilation' are secondary types.
                        logger.debug(f"Skipping album {rg.get('title')} due to secondary types: {secondary_types}")
                        continue

                    title = rg.get("title")
                    norm_title = title.lower().strip()
                    if norm_title in seen_titles:
                        continue
                    seen_titles.add(norm_title)
                    
                    all_rgs.append(rg)

                # Pagination
                count = rg_data.get("release-group-count", 0)
                if len(release_groups) < limit or (offset + len(release_groups)) >= count:
                    break
                
                offset += limit
            else:
                logger.error(f"MusicBrainz Albums Fetch Failed: {rg_resp.status_code}")
                break
                
        logger.info(f"Processing {len(all_rgs)} unique albums for {artist_name}...")

        # 2. Process concurrently with Semaphore
        sem = asyncio.Semaphore(5) # Limit concurrent album validations
        
        async def sem_process(rg):
            async with sem:
                return await _process_single_album(rg, artist_name, client)

        tasks = [sem_process(rg) for rg in all_rgs]
        results = await asyncio.gather(*tasks)
        
        # Sort by date
        albums = sorted([r for r in results if r], key=lambda x: x["date"] or "", reverse=True)
        logger.debug(f"Found {len(albums)} missing albums candidates")
        
    except Exception as e:
        logger.error(f"Error fetching albums for {mbid}: {e}")
    finally:
        if should_close:
            await client.aclose()
            
    return albums


async def fetch_track_credits(mb_recording_id: str, mb_release_track_id: str = None):
    """
    Fetch artist credits for a track/recording from MusicBrainz.
    Returns a list of tuples: (mbid, name)
    """
    credits = []
    # Prefer Recording ID (which is what we usually have as MBID from tags for track)
    # But some tags might give Release Track ID.
    target_id = mb_recording_id or mb_release_track_id
    if not target_id:
        return []

    # MusicBrainz limits: 1 req/sec. We depend on caller to respect or be slow.
    # Ideally use a semaphore or queue if parallelized.
    
    url = f"{MB_API_ROOT}/recording/{target_id}?inc=artist-credits&fmt=json"
    logger.debug(f"Fetching track credits from: {url}")
    
    
    try:
        async with httpx.AsyncClient(headers={"User-Agent": "Jamarr/0.1 ( jamarr@example.com )"}) as client:
            # Retry loop for initial MB connection
            mb_data = None
            for attempt in range(3):
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        mb_data = resp.json()
                        break
                    elif resp.status_code == 503:
                        # Rate limit, wait and retry
                        await asyncio.sleep(1 * (attempt + 1))
                        continue
                    else:
                        logger.warning(f"MusicBrainz returned status {resp.status_code} for {target_id}")
                        break
                except Exception as e:
                    logger.warning(f"Attempt {attempt + 1}/3 failed to fetch MB data for {target_id}: {e}")
                    if attempt < 2:
                        await asyncio.sleep(1 * (attempt + 1))
                    else:
                        logger.error(f"Error fetching metadata for {target_id}: {e}")
            
            if mb_data:
                for ac in mb_data.get("artist-credit", []):
                    # ac is usually obj with 'artist' dict and 'joinphrase'
                    artist_obj = ac.get("artist", {})
                    mbid = artist_obj.get("id")
                    name = artist_obj.get("name")
                    if mbid and name:
                        credits.append((mbid, name))
            elif mb_data is None and mb_release_track_id and target_id == mb_recording_id:
                 # Logic for 404 fallback if needed, currently just logging warning above if status was not 200/503
                 pass
    except Exception as e:
        logger.error(f"Error fetching track credits: {e}")
        
    return credits

