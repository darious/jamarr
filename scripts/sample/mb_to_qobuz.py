import asyncio
import hashlib
import os
import time
import httpx
from rapidfuzz import fuzz
import logging
from rich.console import Console
from rich.logging import RichHandler

from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parent.parent.parent


def load_dotenv(path: _Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
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


load_dotenv(ROOT / ".env")

QOBUZ_APP_ID = os.environ.get("QOBUZ_APP_ID", "")
QOBUZ_SECRET = os.environ.get("QOBUZ_SECRET", "")
USER_EMAIL = os.environ.get("QOBUZ_EMAIL", "")
USER_PASS = os.environ.get("QOBUZ_PASSWORD", "")
USER_AGENT = "JamarrScript/1.0"

# --- Setup Output ---
logging.basicConfig(
    level=logging.WARNING,  # Default to WARNING to suppress libraries
    format="%(message)s",
    handlers=[RichHandler(show_time=False, show_path=False)]
)
logger = logging.getLogger("mb_to_qobuz")
logger.setLevel(logging.INFO)

# Suppress httpx info logs
logging.getLogger("httpx").setLevel(logging.WARNING)

console = Console()

class QobuzClient:
    def __init__(self):
        self.app_id = QOBUZ_APP_ID
        self.token = None
        self.user_auth_token = None
        self.client = httpx.AsyncClient(timeout=10)

    async def login(self):
        """Login to Qobuz to get a user auth token."""
        try:
            timestamp = str(int(time.time()))
            # Signature for 'userlogin': md5("userlogin" + ts + secret)
            msg = f"userlogin{timestamp}{QOBUZ_SECRET}"
            sig = hashlib.md5(msg.encode()).hexdigest()
            
            params = {
                "email": USER_EMAIL,
                "password": hashlib.md5(USER_PASS.encode()).hexdigest(),
                "app_id": self.app_id,
                "request_ts": timestamp,
                "request_sig": sig,
                "device_manufacturer_id": "unknown"
            }
            
            headers = {"X-App-Id": self.app_id}
            resp = await self.client.get("https://www.qobuz.com/api.json/0.2/user/login", params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            
            self.user_auth_token = data.get("user_auth_token")
            # logger.info("Qobuz Login Successful")
            return True
            
        except Exception as e:
            console.print(f"[red]Qobuz Login Failed: {repr(e)}[/red]")
            if isinstance(e, httpx.HTTPStatusError):
                 console.print(f"[red]Response: {e.response.text}[/red]")
            return False

    async def search_artist(self, query):
        # 1. Try Public Search (App ID only) first
        url = "https://www.qobuz.com/api.json/0.2/artist/search"
        headers = {"X-App-Id": self.app_id}
        params = {"query": query, "limit": 5}
        
        try:
            resp = await self.client.get(url, headers=headers, params=params)
            # Public search often returns 401 for this endpoint with some IDs
            resp.raise_for_status()
            return resp.json().get("artists", {}).get("items", [])
        except httpx.HTTPStatusError:
             # Fallback to login
             pass
        except Exception:
             pass

        # 2. If Public failed, try Login + Auth Token
        if not self.user_auth_token:
            if not await self.login():
                return []

        headers["X-User-Auth-Token"] = self.user_auth_token
        try:
            resp = await self.client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp.json().get("artists", {}).get("items", [])
        except Exception as e:
            console.print(f"[red]Search Failed: {e}[/red]")
            return []
            
    async def close(self):
        await self.client.aclose()


async def get_mb_metadata(mbid, client):
    """Fetch Artist name and relations from MusicBrainz."""
    url = f"https://musicbrainz.org/ws/2/artist/{mbid}?inc=url-rels&fmt=json"
    headers = {"User-Agent": USER_AGENT}

    for attempt in range(3):
        try:
            await asyncio.sleep(1.1) # Rate limit kindness
            resp = await client.get(url, headers=headers)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
             console.print(f"[yellow]MB Link Error ({e}), retrying {attempt+1}/3...[/yellow]")
             await asyncio.sleep(2)
        except Exception as e:
            console.print(f"[red]MB Error: {repr(e)}[/red]")
            return None

    console.print("[red]MB Error: Max retries exceeded[/red]")
    return None

async def resolve_wikidata(wikidata_url, client):
    """Resolve Qobuz ID from Wikidata URL."""
    qid = wikidata_url.split("/")[-1]
    url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
    # Wikidata REQUIRES a User-Agent
    headers = {"User-Agent": USER_AGENT}
    
    try:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            logger.warning(f"Wikidata returned {resp.status_code}")
            return None
        
        data = resp.json()
        claims = data.get("entities", {}).get(qid, {}).get("claims", {})
        
        # P6573 is Qobuz Artist ID
        if "P6573" in claims:
            mainsnak = claims["P6573"][0].get("mainsnak", {})
            return mainsnak.get("datavalue", {}).get("value")
            
    except Exception as e:
        logger.warning(f"Wikidata resolution error: {e}")
    
    return None



def format_qobuz_link(artist_name, artist_id):
    """Format: https://www.qobuz.com/gb-en/interpreter/artist-name/id"""
    import re
    # Slugify name: lowercase, replace non-alphanumeric with hyphens
    slug = re.sub(r'[^a-z0-9]+', '-', artist_name.lower()).strip('-')
    return f"https://www.qobuz.com/gb-en/interpreter/{slug}/{artist_id}"

async def find_qobuz_artist(mbid):
    console.print(f"[bold blue]Processing MBID:[/bold blue] {mbid}")
    
    # Return structure: (link, artist_name, source)
    # Source: 'mb', 'wikidata', 'search'
    
    async with httpx.AsyncClient() as http_client:
        # 1. MusicBrainz Lookup
        console.print("🔍 Checking MusicBrainz...", end=" ")
        mb_data = await get_mb_metadata(mbid, http_client)
        if not mb_data:
            console.print("[bold red]Artist not found in MusicBrainz[/bold red]")
            return None, None, None
            
        artist_name = mb_data.get("name")
        console.print(f"[green]Found: {artist_name}[/green]")
        
        # 2. Check Relations
        relations = mb_data.get("relations", [])
        wikidata_url = None
        
        for rel in relations:
            target = rel.get("url", {}).get("resource", "")
            if "qobuz.com" in target:
                console.print(f"✅ Found Direct on MB: [link={target}]{target}[/link]")
                # We normalize/reformat found links? No, if on MB, keep as is.
                return target, artist_name, 'mb'
            if "wikidata.org" in target:
                wikidata_url = target
                
        # 3. Check Wikidata
        if wikidata_url:
            console.print(f"🔍 Checking Wikidata ({wikidata_url})...", end=" ")
            q_id = await resolve_wikidata(wikidata_url, http_client)
            if q_id:
                # Format link nicely
                link = format_qobuz_link(artist_name, q_id)
                console.print(f"[green]Found ID: {q_id}[/green]")
                console.print(f"✅ Generated Link: [link={link}]{link}[/link]")
                return link, artist_name, 'wikidata'
            else:
                console.print("[yellow]No Qobuz ID in Wikidata[/yellow]")

    # 4. Fallback: Search Qobuz
    console.print("🔍 Searching Qobuz API...", end=" ")
    q_client = QobuzClient()
    try:
        results = await q_client.search_artist(artist_name)
        
        if not results:
             console.print("[red]No results found[/red]")
             return None, artist_name, None

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
            # Format link nicely using the Qobuz name (might vary slightly but safe) or MB name?
            # User wants: https://www.qobuz.com/gb-en/interpreter/coldplay/40226
            # We used MB Name for slug usually best practice if it's the anchor.
            link = format_qobuz_link(artist_name, q_id)
            
            console.print(f"[green]Found Match: {best_match['name']} (Score: {best_score})[/green]")
            console.print(f"✅ Generated Link: [link={link}]{link}[/link]")
            return link, artist_name, 'search'
        else:
            console.print("[yellow]No matches met criteria (>85)[/yellow]")
            return None, artist_name, None
            
    finally:
        await q_client.close()

async def process_item(mbid):
    """Process a single MBID and log the found link."""
    link, _, _ = await find_qobuz_artist(mbid)
    if link:
        console.print(f"[bold green]Result:[/bold green] {link}")
    else:
        console.print(f"[bold red]No Qobuz link found for {mbid}[/bold red]")
    return link

async def process_file(filepath):
    import os
    
    if not os.path.exists(filepath):
        console.print(f"[bold red]File not found: {filepath}[/bold red]")
        return

    # Read all lines
    with open(filepath, "r") as f:
        lines = f.readlines()

    console.print(f"[bold blue]Processing {len(lines)} lines from {filepath}...[/bold blue]")
    for i, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        
        parts = line.split()
        mbid = parts[0]
        current_link = parts[1] if len(parts) > 1 else None
        
        if current_link and "qobuz.com" in current_link:
            console.print(f"[dim]Line {i+1}: {mbid} already has link {current_link}[/dim]")
            continue
        
        console.print(f"[dim]Line {i+1}: {mbid}[/dim]")
        await process_item(mbid)

    console.print("[bold green]Batch processing complete (read-only).[/bold green]")

if __name__ == "__main__":
    import argparse

    import os

    parser = argparse.ArgumentParser(description="Map MusicBrainz Artist ID to Qobuz Artist Link")
    parser.add_argument("input", help="MusicBrainz Artist ID (UUID) or Path to file containing IDs")
    args = parser.parse_args()
    
    if os.path.isfile(args.input):
        asyncio.run(process_file(args.input))
    else:
        asyncio.run(process_item(args.input))
