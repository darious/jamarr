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
        "similar_artists": [],
        "top_tracks": [],
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
                metadata["sort_name"] = mb_data.get("sort-name")
                relations = mb_data.get("relations", [])
                logger.debug(f"Found {len(relations)} relations for {artist_name}")
                
                for rel in relations:
                    target = rel.get("url", {}).get("resource", "")
                    type_ = rel.get("type", "")
                    
                    if type_ == "official homepage" and not metadata["homepage"]:
                        metadata["homepage"] = target
                    elif type_ == "wikidata":
                        wikidata_url = target
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
                    logger.debug(f"Searching Spotify for: {artist_name}")
                    search_url = f"{SPOTIFY_API_ROOT}/search?q={artist_name}&type=artist&limit=1"
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

    except Exception as e:
        logger.error(f"Error fetching metadata for {artist_name}: {e}")

    return metadata

