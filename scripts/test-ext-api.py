#!/usr/bin/env python
"""
Verify external API connectivity using credentials from .env.
"""
from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path
from typing import Callable, Tuple

import httpx
from rich.console import Console
from rich.table import Table

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import (  # type: ignore # noqa: E402
    get_fanarttv_api_key,
    get_lastfm_credentials,
    get_musicbrainz_root_url,
    get_pearlarr_url,
    get_qobuz_credentials,
    get_spotify_credentials,
    get_tidal_credentials,
    get_user_agent,
)

TEST_MBID = "65f4f0c5-ef9e-490c-aee3-909e7ae6b2ab"  # Metallica
TEST_SPOTIFY_ARTIST_ID = "43ZHCT0cAZBISjO8DG9PnE"  # Elvis Presley
TEST_WIKIDATA_QID = "Q2831"  # Metallica
TEST_WIKIPEDIA_TITLE = "Metallica"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and value[0] in ("'", '"') and value[-1] == value[0]:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _missing_env_error(exc: Exception) -> str:
    return str(exc) or "missing environment variable"


def check_spotify(client: httpx.Client) -> Tuple[bool, str]:
    try:
        client_id, client_secret = get_spotify_credentials()
    except ValueError as exc:
        return False, _missing_env_error(exc)

    token_resp = client.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
    )
    if token_resp.status_code != 200:
        return False, f"token request failed ({token_resp.status_code})"
    token = token_resp.json().get("access_token")
    if not token:
        return False, "token response missing access_token"

    artist_resp = client.get(
        f"https://api.spotify.com/v1/artists/{TEST_SPOTIFY_ARTIST_ID}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if artist_resp.status_code != 200:
        return False, f"artist request failed ({artist_resp.status_code})"
    name = artist_resp.json().get("name")
    if not name:
        return False, "artist response missing name"
    return True, f"artist={name}"


def check_fanart(client: httpx.Client) -> Tuple[bool, str]:
    try:
        api_key = get_fanarttv_api_key()
    except ValueError as exc:
        return False, _missing_env_error(exc)

    resp = client.get(
        f"https://webservice.fanart.tv/v3/music/{TEST_MBID}",
        params={"api_key": api_key},
    )
    if resp.status_code != 200:
        return False, f"request failed ({resp.status_code})"
    data = resp.json()
    if not isinstance(data, dict) or not data:
        return False, "empty response"
    return True, "data returned"


def check_lastfm(client: httpx.Client) -> Tuple[bool, str]:
    try:
        api_key, _secret = get_lastfm_credentials()
    except ValueError as exc:
        return False, _missing_env_error(exc)

    resp = client.get(
        "https://ws.audioscrobbler.com/2.0/",
        params={
            "method": "artist.getinfo",
            "mbid": TEST_MBID,
            "api_key": api_key,
            "format": "json",
        },
    )
    if resp.status_code != 200:
        return False, f"request failed ({resp.status_code})"
    data = resp.json()
    if data.get("error"):
        return False, f"api error: {data.get('message')}"
    name = data.get("artist", {}).get("name")
    if not name:
        return False, "artist response missing name"
    return True, f"artist={name}"


def check_musicbrainz(client: httpx.Client) -> Tuple[bool, str]:
    mb_root = get_musicbrainz_root_url().rstrip("/")
    url = f"{mb_root}/ws/2/artist/{TEST_MBID}"
    resp = client.get(
        url,
        params={"fmt": "json"},
        headers={"User-Agent": get_user_agent()},
    )
    if resp.status_code != 200:
        return False, f"request failed ({resp.status_code})"
    data = resp.json()
    name = data.get("name")
    if not name:
        return False, "artist response missing name"
    return True, f"artist={name}"


def check_wikidata(client: httpx.Client) -> Tuple[bool, str]:
    resp = client.get(
        f"https://www.wikidata.org/wiki/Special:EntityData/{TEST_WIKIDATA_QID}.json",
        headers={"User-Agent": get_user_agent()},
    )
    if resp.status_code != 200:
        return False, f"request failed ({resp.status_code})"
    entities = resp.json().get("entities") or {}
    entity = entities.get(TEST_WIKIDATA_QID) or {}
    labels = entity.get("labels") or {}
    label = labels.get("en", {}).get("value")
    if not label and labels:
        first_label = next(iter(labels.values()), {})
        label = first_label.get("value")
    if not label:
        title = (entity.get("sitelinks") or {}).get("enwiki", {}).get("title")
        if title:
            return True, f"title={title}"
        return False, "entity response missing label/title"
    return True, f"label={label}"


def check_wikipedia(client: httpx.Client) -> Tuple[bool, str]:
    resp = client.get(
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{TEST_WIKIPEDIA_TITLE}",
        headers={"User-Agent": get_user_agent()},
    )
    if resp.status_code != 200:
        return False, f"request failed ({resp.status_code})"
    extract = resp.json().get("extract")
    if not extract:
        return False, "summary response missing extract"
    return True, "summary returned"


def check_pearlarr(client: httpx.Client) -> Tuple[bool, str]:
    try:
        pearlarr_url = get_pearlarr_url()
    except ValueError as exc:
        return False, _missing_env_error(exc)

    resp = client.get(pearlarr_url)
    if resp.status_code == 405:
        return True, "reachable (method not allowed for GET)"
    if resp.status_code != 200:
        return False, f"request failed ({resp.status_code})"
    if not resp.text.strip():
        return False, "empty response"
    return True, "data returned"


def _qobuz_login(
    client: httpx.Client, app_id: str, secret: str, email: str, password: str
) -> Tuple[bool, str | None, str]:
    timestamp = str(int(time.time()))
    sig = hashlib.new('md5', f"userlogin{timestamp}{secret}".encode(), usedforsecurity=False).hexdigest()
    resp = client.get(
        "https://www.qobuz.com/api.json/0.2/user/login",
        params={
            "email": email,
            "password": hashlib.new('md5', password.encode(), usedforsecurity=False).hexdigest(),
            "app_id": app_id,
            "request_ts": timestamp,
            "request_sig": sig,
            "device_manufacturer_id": "jamarr_scanner",
        },
        headers={"X-App-Id": app_id},
    )
    if resp.status_code != 200:
        return False, None, f"login failed ({resp.status_code})"
    token = resp.json().get("user_auth_token")
    if not token:
        return False, None, "login missing user_auth_token"
    return True, token, "login ok"


def check_qobuz(client: httpx.Client) -> Tuple[bool, str]:
    try:
        app_id, secret, email, password = get_qobuz_credentials()
    except ValueError as exc:
        return False, _missing_env_error(exc)

    headers = {"X-App-Id": app_id}
    resp = client.get(
        "https://www.qobuz.com/api.json/0.2/artist/search",
        params={"query": "Metallica", "limit": 5},
        headers=headers,
    )
    if resp.status_code == 401:
        ok, token, msg = _qobuz_login(client, app_id, secret, email, password)
        if not ok:
            return False, msg
        headers["X-User-Auth-Token"] = token  # type: ignore[assignment]
        resp = client.get(
            "https://www.qobuz.com/api.json/0.2/artist/search",
            params={"query": "Metallica", "limit": 5},
            headers=headers,
        )

    if resp.status_code != 200:
        return False, f"search failed ({resp.status_code})"
    items = (resp.json().get("artists") or {}).get("items") or []
    if not items:
        return False, "no artists returned"
    return True, f"artists={len(items)}"


def check_tidal(client: httpx.Client) -> Tuple[bool, str]:
    try:
        client_id, client_secret = get_tidal_credentials()
    except ValueError as exc:
        return False, _missing_env_error(exc)

    token_resp = client.post(
        "https://auth.tidal.com/v1/oauth2/token",
        data={"grant_type": "client_credentials"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        auth=(client_id, client_secret),
    )
    if token_resp.status_code != 200:
        return False, f"token request failed ({token_resp.status_code})"
    token = token_resp.json().get("access_token")
    if not token:
        return False, "token response missing access_token"

    resp = client.get(
        "https://openapi.tidal.com/v2/searchResults/Metallica/relationships/artists",
        params={"countryCode": "GB", "include": "artists"},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.api+json",
        },
    )
    if resp.status_code != 200:
        return False, f"search failed ({resp.status_code})"
    included = resp.json().get("included") or []
    if not included:
        return False, "no artists returned"
    return True, f"artists={len(included)}"


def run_check(
    name: str, func: Callable[[httpx.Client], Tuple[bool, str]], client: httpx.Client
) -> bool:
    try:
        return func(client)
    except Exception as exc:  # noqa: BLE001
        return False, f"error: {exc}"


def main() -> int:
    load_dotenv(ROOT / ".env")
    checks = [
        ("spotify", check_spotify),
        ("fanart", check_fanart),
        ("lastfm", check_lastfm),
        ("musicbrainz", check_musicbrainz),
        ("wikidata", check_wikidata),
        ("wikipedia", check_wikipedia),
        ("pearlarr", check_pearlarr),
        ("qobuz", check_qobuz),
        ("tidal", check_tidal),
    ]
    console = Console()
    table = Table(title="External API Check", show_lines=False)
    table.add_column("API", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Detail")
    with httpx.Client(timeout=10.0) as client:
        results = []
        for name, func in checks:
            ok, detail = run_check(name, func, client)
            status = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
            table.add_row(name, status, detail)
            results.append(ok)
    console.print(table)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
