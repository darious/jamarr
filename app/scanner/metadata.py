import httpx
import json
import time
import asyncio
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)

MB_API_ROOT = "https://musicbrainz.org/ws/2"
WIKI_API_ROOT = "https://en.wikipedia.org/api/rest_v1/page/summary"

import base64

from app.config import get_spotify_credentials

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
        "similar_artists": [],
        "top_tracks": [],
        "singles": [],
        "last_updated": time.time()
    }

    try:
        async with httpx.AsyncClient(headers={"User-Agent": "Jamarr/0.1 ( jamarr@example.com )"}) as client:
            # 1. MusicBrainz
            mb_url = f"{MB_API_ROOT}/artist/{mbid}?inc=url-rels&fmt=json"
            logger.debug(f"Fetching MB data from: {mb_url}")
            resp = await client.get(mb_url)
            
            wikidata_url = None
            spotify_id = None
            
            if resp.status_code == 200:
                mb_data = resp.json()
                if mb_data.get("name"):
                    metadata["name"] = mb_data.get("name")
                metadata["sort_name"] = mb_data.get("sort-name")
                relations = mb_data.get("relations", [])
                logger.debug(f"Found {len(relations)} relations for {artist_name}")
                
                # Set MusicBrainz URL
                metadata["musicbrainz_url"] = f"https://musicbrainz.org/artist/{mbid}"

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
                    if search_query and search_query != "Unknown Artist":
                        logger.debug(f"Searching Spotify for: {search_query}")
                        from urllib.parse import quote
                        search_url = f"{SPOTIFY_API_ROOT}/search?q={quote(search_query)}&type=artist&limit=1"
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
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                for ac in data.get("artist-credit", []):
                    # ac is usually obj with 'artist' dict and 'joinphrase'
                    artist_obj = ac.get("artist", {})
                    mbid = artist_obj.get("id")
                    name = artist_obj.get("name")
                    if mbid and name:
                        credits.append((mbid, name))
            elif resp.status_code == 404 and mb_release_track_id and target_id == mb_recording_id:
                # If Recording ID failed (maybe it WAS a Track ID?), try fetching as Track?
                # MB Track ID endpoint: /track/{id}
                # But usually tags have Recording ID.
                pass
            else:
                logger.warning(f"Failed to fetch track credits for {target_id}: {resp.status_code}")
    except Exception as e:
        logger.error(f"Error fetching track credits: {e}")
        
    return credits
