import httpx
import logging
import time
import base64
import math
import re
import difflib
from app.config import get_fanarttv_api_key, get_spotify_credentials
from app.scanner.stats import get_api_tracker

logger = logging.getLogger("scanner.services.artwork")

FANART_API_ROOT = "https://webservice.fanart.tv/v3/music"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_ROOT = "https://api.spotify.com/v1"

_spotify_token = None
_token_expiry = 0

class SpotifyRateLimitError(Exception):
    def __init__(self, retry_after=None):
        try:
            self.retry_after = int(retry_after) if retry_after is not None else None
        except (ValueError, TypeError):
            self.retry_after = None
        
        msg = "Spotify Rate Limit Exceeded"
        if self.retry_after:
            msg += f" (Retry after {self.retry_after}s)"
        super().__init__(msg)

async def fetch_fanart_artist_images(mbid: str, client: httpx.AsyncClient):
    """
    Fetch best artist thumb and background URLs from Fanart.tv.
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
            url = "https://" + url[len("http://") :]
        return url

    try:
        get_api_tracker().increment("fanart")
        resp = await client.get(
            f"{FANART_API_ROOT}/{mbid}", params={"api_key": api_key}, timeout=20.0
        )
        if resp.status_code != 200:
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
        get_api_tracker().increment("spotify")
        resp = await client.post(
            SPOTIFY_TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {b64_auth}"},
        )
        if resp.status_code == 200:
            data = resp.json()
            _spotify_token = data["access_token"]
            _token_expiry = time.time() + data["expires_in"] - 60
            return _spotify_token
        elif resp.status_code == 429:
            retry = resp.headers.get("Retry-After")
            raise SpotifyRateLimitError(retry)
        else:
            logger.error(f"Spotify Auth Failed: {resp.status_code}")
    except Exception as e:
        logger.error(f"Spotify Auth Error: {e}")
    return None

def _similarity(a: str, b: str) -> float:
    def normalize(name):
        return re.sub(r"[^a-z0-9]+", "", name.lower()) if name else ""
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()

async def fetch_spotify_artist_images(spotify_id: str, client: httpx.AsyncClient):
    """
    Fetch image URL from Spotify Artist ID.
    Returns: image_url or None.
    """
    if not spotify_id:
        return None
        
    try:
        token = await get_spotify_token(client)
        if not token:
            return None
            
        headers = {"Authorization": f"Bearer {token}"}
        
        get_api_tracker().increment("spotify")
        resp = await client.get(
            f"{SPOTIFY_API_ROOT}/artists/{spotify_id}",
            headers=headers
        )
        
        if resp.status_code == 429:
             retry = resp.headers.get("Retry-After")
             raise SpotifyRateLimitError(retry)
             
        if resp.status_code == 200:
            data = resp.json()
            images = data.get("images", [])
            if images:
                return images[0]["url"]
    except SpotifyRateLimitError:
        raise
    except Exception as e:
        logger.warning(f"Spotify Artwork Fetch Failed for {spotify_id}: {e}")
        
    return None

async def resolve_spotify_id(candidates: list, artist_name: str, client: httpx.AsyncClient):
    """
    Resolve best Spotify ID from a list of candidates (id, url) or strict search.
    """
    token = await get_spotify_token(client)
    if not token:
        logger.debug(f"[{artist_name}] No Spotify token available")
        return None, None
        
    headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Evaluate Candidates
    async def _evaluate(cid):
        try:
            get_api_tracker().increment("spotify")
            resp = await client.get(f"{SPOTIFY_API_ROOT}/artists/{cid}", headers=headers)
            if resp.status_code == 429:
                 retry = resp.headers.get("Retry-After")
                 raise SpotifyRateLimitError(retry)
            if resp.status_code != 200:
                return None
            data = resp.json()
            name = data.get("name") or ""
            pop = data.get("popularity") or 0
            followers = data.get("followers", {}).get("total") or 0

            name_score = _similarity(name, artist_name)
            pop_score = min(max(pop, 0), 100) / 100
            followers_score = min(math.log10(followers + 1) / 7, 1) if followers else 0
            final_score = name_score * 0.7 + pop_score * 0.2 + followers_score * 0.1

            return {
                "id": cid,
                "url": data.get("external_urls", {}).get("spotify"),
                "name": name,
                "popularity": pop,
                "followers": followers,
                "name_score": name_score,
                "final_score": final_score,
            }
        except Exception:
            return None

    scored = []
    for cid, _url in candidates:
        if not cid:
            continue
        logger.debug(f"[{artist_name}] Evaluating Spotify candidate {cid}")
        res = await _evaluate(cid)
        if res:
            scored.append(res)
            
    if scored:
        scored = [c for c in scored if c["name_score"] >= 0.55]
        if scored:
            scored.sort(key=lambda x: (x["final_score"], x["popularity"]), reverse=True)
            best = scored[0]
            return best["id"], best.get("url")

    # 2. Strict Search Fallback (Only if candidates failed)
    # Note: Plan implies we only fallback if explicitly desired, but metadata.py had it.
    # The plan says: "Fetch Artwork from Spotify (fallback)".
    # AND "Spotify Only if Spotify Artist ID is already known... No search-by-name fallback is permitted".
    # WAIT. The plan explicitly says: "No search-by-name fallback is permitted" under app.scanner.services.artwork.
    # AND "Spotify ID must originate from MusicBrainz or Wikidata".
    # So I MUST NOT implement the search fallback here if I follow strict plan.
    # But `metadata.py` lines 1158-1200 HAD search fallback.
    # The plan v2 explicitly REMOVES that fallback ("Explicit Non-Goals").
    # So I will NOT include the search fallback.
    
    return None, None
