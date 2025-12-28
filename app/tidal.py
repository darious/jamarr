import base64
import difflib
import json
import logging
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_tidal_credentials

logger = logging.getLogger(__name__)

OPENAPI_BASE = "https://openapi.tidal.com/v2"
TOKEN_URL = "https://auth.tidal.com/v1/oauth2/token"
ACCEPT_JSONAPI = "application/vnd.api+json"


def norm(s: str) -> str:
    return " ".join(s.lower().strip().split())


def fuzzy(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


_VERSION_RE = re.compile(
    r"\s*[\(\[\-–—]\s*(deluxe|expanded|remaster(ed)?|anniversary|edition|version|live).*?$",
    re.IGNORECASE,
)


def normalise_title(title: str) -> str:
    return _VERSION_RE.sub("", title).strip()


def year_from_date(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        return int(s[:4])
    except Exception:
        return None


class TidalClient:
    def __init__(self):
        self.client_id, self.client_secret = get_tidal_credentials()
        self.country_code = "GB"  # Default, maybe make configurable?

        self.ssl = ssl.create_default_context()
        self.ssl.check_hostname = False
        self.ssl.verify_mode = (
            ssl.CERT_NONE
        )  # Match cc_tidal2.py behavior for simplicity/robustness in some envs

        self.token: Optional[str] = None
        self.expiry: float = 0.0

    def _token_valid(self) -> bool:
        return self.token and time.time() < self.expiry - 30

    def get_token(self) -> str:
        if self._token_valid():
            return self.token  # type: ignore

        if not self.client_id or not self.client_secret:
            logger.warning("Tidal credentials missing in config.")
            return None

        try:
            creds = f"{self.client_id}:{self.client_secret}"
            b64 = base64.b64encode(creds.encode()).decode()

            data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
            req = urllib.request.Request(TOKEN_URL, data=data)
            req.add_header("Authorization", f"Basic {b64}")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")

            with urllib.request.urlopen(req, context=self.ssl) as r:
                payload = json.loads(r.read().decode())

            self.token = payload["access_token"]
            self.expiry = time.time() + payload.get("expires_in", 3600)
            return self.token
        except Exception as e:
            logger.error(f"Failed to get Tidal token: {e}")
            return None

    def get_json(self, url: str) -> Dict[str, Any]:
        token = self.get_token()
        if not token:
            return {}

        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", ACCEPT_JSONAPI)

        try:
            with urllib.request.urlopen(req, context=self.ssl) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                logger.warning(f"Tidal Rate Limit: {url}")
                time.sleep(1)  # Simple backoff
                # Retry logic? For now return empty
            # logger.debug(f"Tidal API error {e.code}: {e}")
            return {}
        except Exception as e:
            logger.error(f"Tidal/Network error: {e}")
            return {}

    def search_albums(self, query: str) -> List[Dict[str, Any]]:
        q = urllib.parse.quote(query, safe="")
        url = (
            f"{OPENAPI_BASE}/searchResults/{q}/relationships/albums"
            f"?countryCode={self.country_code}&include=albums"
        )
        payload = self.get_json(url)
        included = {
            r["id"]: r for r in payload.get("included", []) if r["type"] == "albums"
        }
        out = []
        for rel in payload.get("data", []):
            rid = rel.get("id")
            if rid in included:
                out.append(included[rid])
        return out

    def verify_album_artists(self, album_id: str) -> List[str]:
        url = (
            f"{OPENAPI_BASE}/albums/{album_id}/relationships/artists"
            f"?countryCode={self.country_code}&include=artists"
        )
        payload = self.get_json(url)
        artists = []
        for a in payload.get("included", []):
            if a["type"] == "artists":
                name = a.get("attributes", {}).get("name")
                if name:
                    artists.append(name)
        return artists

    def find_album_match(
        self, artist_name: str, album_title: str, release_year: Optional[int] = None
    ) -> Optional[str]:
        """
        High-level helper to find a Tidal URL for an album.
        Returns Tidal URL if confidence is high, else None.
        """
        if not self.client_id or not self.client_secret:
            return None

        # Search
        query = f"{artist_name} {album_title}"
        albums = self.search_albums(query)
        if not albums:
            return None

        scored = []
        for alb in albums:
            s = self.score_album(alb, artist_name, album_title, release_year)
            scored.append((s, alb))

        scored.sort(key=lambda x: x[0][0], reverse=True)
        if not scored:
            return None

        best_scores, best_album = scored[0]
        combined, title_s, artist_s, year_s = best_scores

        # Verify artist if missing or weak (from cc_tidal2.py logic)
        if artist_s < 0.4:
            artists = self.verify_album_artists(best_album["id"])
            combined, title_s, artist_s, year_s = self.score_album(
                best_album,
                artist_name,
                album_title,
                release_year,
                verified_artists=artists,
            )
            # Re-evaluate confidence

        confidence = self.confidence_level(title_s, artist_s, year_s)

        if confidence == "high":
            return f"https://tidal.com/album/{best_album['id']}"

        return None

    def score_album(
        self,
        album: Dict[str, Any],
        want_artist: str,
        want_title: str,
        want_year: Optional[int],
        verified_artists: Optional[List[str]] = None,
    ) -> Tuple[float, float, float, float]:
        attrs = album.get("attributes", {})

        title = attrs.get("title", "")
        title_score = fuzzy(
            normalise_title(want_title),
            normalise_title(title),
        )

        artists = verified_artists or [
            a.get("name") for a in attrs.get("artists", []) or [] if isinstance(a, dict)
        ]
        artist_score = max((fuzzy(want_artist, a) for a in artists), default=0.0)

        release_year_val = year_from_date(attrs.get("releaseDate"))
        if want_year and release_year_val:
            year_score = 1.0 if abs(want_year - release_year_val) <= 1 else 0.0
        else:
            year_score = 0.5  # neutral

        combined = (0.7 * title_score) + (0.2 * artist_score) + (0.1 * year_score)
        return combined, title_score, artist_score, year_score

    def confidence_level(self, title: float, artist: float, year: float) -> str:
        if title >= 0.95 and year >= 0.9:
            return "high"
        if title >= 0.90 and artist >= 0.60:
            return "high"
        if title >= 0.80 and year >= 0.5:
            return "medium"
        return "low"
