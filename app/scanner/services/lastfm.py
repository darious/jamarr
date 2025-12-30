import httpx
import logging
from app.config import get_lastfm_credentials
from app.scanner.stats import get_api_tracker

logger = logging.getLogger("scanner.services.lastfm")

async def fetch_top_tracks(artist_mbid: str, artist_name: str, client: httpx.AsyncClient):
    """
    Fetch top tracks from Last.fm using MBID strict.
    """
    if not artist_mbid:
        return []

    api_key, _ = get_lastfm_credentials()
    if not api_key:
        logger.warning("Last.fm API key not configured.")
        return []

    url = "http://ws.audioscrobbler.com/2.0/"
    params = {
        "method": "artist.gettoptracks",
        "mbid": artist_mbid,
        "api_key": api_key,
        "format": "json",
        "limit": 15,
    }
    
    try:
        get_api_tracker().increment("lastfm")
        resp = await client.get(url, params=params, timeout=10.0)
        
        if resp.status_code == 200:
            data = resp.json()
            tracks_data = data.get("toptracks", {}).get("track", [])
            
            if not tracks_data:
                return []
                
            if isinstance(tracks_data, dict):
                tracks_data = [tracks_data]
                
            results = []
            rank = 1
            for t in tracks_data:
                if rank > 10:
                    break
                    
                results.append({
                    "name": t.get("name"),
                    "mbid": t.get("mbid"),
                    "rank": rank,
                    "playcount": t.get("playcount"),
                    "popularity": t.get("playcount"), # Map playcount to popularity
                    "album": None
                })
                rank += 1
            return results
        else:
            logger.warning(f"Last.fm Top Tracks error {resp.status_code} for {artist_mbid}")
            return []
            
    except Exception as e:
        logger.error(f"[{artist_name}] Last.fm Top Tracks failed for {artist_mbid}: {e}")
        return []

async def fetch_similar_artists(artist_mbid: str, artist_name: str, client: httpx.AsyncClient):
    """
    Fetch similar artists from Last.fm using MBID strict.
    """
    if not artist_mbid:
        return []
        
    api_key, _ = get_lastfm_credentials()
    if not api_key:
        return []
        
    url = "http://ws.audioscrobbler.com/2.0/"
    params = {
        "method": "artist.getsimilar",
        "mbid": artist_mbid,
        "api_key": api_key,
        "format": "json",
        "limit": 15,
    }
    
    try:
        get_api_tracker().increment("lastfm")
        resp = await client.get(url, params=params, timeout=10.0)
        
        if resp.status_code == 200:
            data = resp.json()
            similar_data = data.get("similarartists", {}).get("artist", [])
            
            if not similar_data:
                return []
                
            if isinstance(similar_data, dict):
                similar_data = [similar_data]
                
            results = []
            count = 0
            for a in similar_data:
                if count >= 10:
                    break
                    
                if a.get("mbid") == artist_mbid:
                    continue
                if a.get("name") == artist_name:
                    continue
                    
                results.append({
                    "name": a.get("name"),
                    "mbid": a.get("mbid"),
                    "match": a.get("match"),
                })
                count += 1
            return results
        else:
            logger.warning(f"Last.fm Similar Artists error {resp.status_code} for {artist_mbid}")
            return []
            
    except Exception as e:
        logger.error(f"[{artist_name}] Last.fm Similar Artists failed for {artist_mbid}: {e}")
        return []


async def fetch_artist_url(artist_mbid: str, client: httpx.AsyncClient):
    """
    Fetch artist URL from Last.fm using MBID.
    """
    if not artist_mbid:
        return None
        
    api_key, _ = get_lastfm_credentials()
    if not api_key:
        return None
        
    url = "http://ws.audioscrobbler.com/2.0/"
    params = {
        "method": "artist.getinfo",
        "mbid": artist_mbid,
        "api_key": api_key,
        "format": "json",
    }
    
    try:
        get_api_tracker().increment("lastfm")
        resp = await client.get(url, params=params, timeout=10.0)
        
        if resp.status_code == 200:
            data = resp.json()
            return data.get("artist", {}).get("url")
        else:
            logger.debug(f"Last.fm Artist Info error {resp.status_code} for {artist_mbid}")
            return None
            
    except Exception as e:
        logger.debug(f"Last.fm Artist Info failed for {artist_mbid}: {e}")
        return None
