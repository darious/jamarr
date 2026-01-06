import httpx
import time
import hashlib
import logging
import asyncio
from rapidfuzz import fuzz
from app.scanner.services.utils import RateLimiter
from app.config import get_qobuz_credentials

logger = logging.getLogger("scanner.services.qobuz")

# Rate Limiter
qobuz_limiter = RateLimiter(rate_limit=2.0, burst_limit=5) # 2 requests per second

class QobuzClient:
    def __init__(self, client: httpx.AsyncClient = None):
        auth = get_qobuz_credentials()
        self.app_id = auth[0]
        self.secret = auth[1]
        self.email = auth[2]
        self.password = auth[3]
        
        self.token = None
        self.user_auth_token = None
        # We prefer using a shared client if provided, else create one
        self._internal_client = None
        if client:
            self.client = client
        else:
            self._internal_client = httpx.AsyncClient(timeout=10)
            self.client = self._internal_client
            
        self._login_lock = asyncio.Lock()

    async def login(self):
        """Login to Qobuz to get a user auth token."""
        async with self._login_lock:
            if self.user_auth_token:
                return True
                
            try:
                await qobuz_limiter.acquire()
                timestamp = str(int(time.time()))
                # Signature for 'userlogin': md5("userlogin" + ts + secret)
                # Signature for 'userlogin': md5("userlogin" + ts + secret)
                msg = f"userlogin{timestamp}{self.secret}"
                sig = hashlib.md5(msg.encode()).hexdigest()
                
                params = {
                    "email": self.email,
                    "password": hashlib.md5(self.password.encode()).hexdigest(),
                    "app_id": self.app_id,
                    "request_ts": timestamp,
                    "request_sig": sig,
                    "device_manufacturer_id": "jamarr_scanner"
                }
                
                headers = {"X-App-Id": self.app_id}
                resp = await self.client.get("https://www.qobuz.com/api.json/0.2/user/login", params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                
                self.user_auth_token = data.get("user_auth_token")
                logger.info("Qobuz Login Successful")
                return True
                
            except Exception as e:
                logger.error(f"Qobuz Login Failed: {e}")
                if isinstance(e, httpx.HTTPStatusError):
                     logger.error(f"Response: {e.response.text}")
                return False

    async def search_artist(self, artist_name):
        """
        Search for an artist and return the best match ID/Link.
        Returns: link string or None
        """
        if not artist_name:
            return None
            
        await qobuz_limiter.acquire()
        
        # 1. Try Public Search (App ID only) first
        url = "https://www.qobuz.com/api.json/0.2/artist/search"
        headers = {"X-App-Id": self.app_id}
        params = {"query": artist_name, "limit": 5}
        
        results = []
        try:
            resp = await self.client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            results = resp.json().get("artists", {}).get("items", [])
            
            # Track API call
            from app.scanner.stats import get_api_tracker
            get_api_tracker().increment("qobuz")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                # 2. Fallback to Login + Auth Token
                if await self.login():
                    headers["X-User-Auth-Token"] = self.user_auth_token
                    try:
                        await qobuz_limiter.acquire()
                        resp = await self.client.get(url, headers=headers, params=params)
                        resp.raise_for_status()
                        results = resp.json().get("artists", {}).get("items", [])
                        
                        # Track API call
                        from app.scanner.stats import get_api_tracker
                        get_api_tracker().increment("qobuz")
                    except Exception as ex:
                        logger.error(f"Qobuz Search Failed (Auth): {ex}")
            else:
                logger.error(f"Qobuz Search Failed (Public): {e}")
        except Exception as e:
             logger.error(f"Qobuz Search Error: {e}")

        if not results:
            return None

        best_match = None
        best_score = 0
        
        for artist in results:
            name = artist.get("name")
            score = fuzz.ratio(artist_name.lower(), name.lower())
            
            if score > 85 and score > best_score:
                best_score = score
                best_match = artist
        
        if best_match:
            q_id = best_match['id']
            link = f"https://play.qobuz.com/artist/{q_id}"
            logger.info(f"Qobuz Match Found: {best_match['name']} ({best_score}%) -> {link}")
            return link
            
        return None

    async def close(self):
        if self._internal_client:
            await self._internal_client.aclose()
