import httpx
import logging
from urllib.parse import quote, unquote
from app.scanner.stats import get_api_tracker

logger = logging.getLogger("scanner.services.wikipedia")

WIKI_API_ROOT = "https://en.wikipedia.org/api/rest_v1/page/summary"

async def fetch_bio(client: httpx.AsyncClient, wikipedia_url: str):
    """
    Fetch bio from Wikipedia URL.
    """
    if not wikipedia_url:
        return None
        
    try:
        wiki_title = wikipedia_url.split("/wiki/")[-1]
        if not wiki_title:
             return None
             
        # Normalize title
        safe_title = unquote(wiki_title)
        
        wiki_summary_url = f"{WIKI_API_ROOT}/{quote(safe_title)}"
        get_api_tracker().increment("wikipedia")
        
        resp = await client.get(wiki_summary_url)
        if resp.status_code == 200:
            wiki_data = resp.json()
            return wiki_data.get("extract")
            
    except Exception as e:
        logger.warning(f"Wikipedia bio fetch failed for {wikipedia_url}: {e}")
        
    return None
