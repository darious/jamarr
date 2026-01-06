import httpx
import logging
from app.scanner.stats import get_api_tracker
from app.config import get_user_agent

logger = logging.getLogger("scanner.services.wikidata")

# Rate limit tracking
_rate_limited = False

async def fetch_external_links(
    client: httpx.AsyncClient,
    wikidata_url: str,
    existing_links: dict,
    cached_entity: dict = None,
) -> dict:
    """
    Fetch external service IDs from Wikidata.
    only returns links that are missing from existing_links.
    """
    global _rate_limited
    
    # Skip if we've been rate limited
    if _rate_limited:
        logger.warning("Skipping Wikidata fetch - previously rate limited (403)")
        return {}
    
    missing_links = {}

    try:
        qid = wikidata_url.split("/")[-1]

        if cached_entity:
            entity = cached_entity
        else:
            wd_api = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
            get_api_tracker().increment("wikidata")
            # Wikidata requires User-Agent header
            headers = {"User-Agent": get_user_agent()}
            resp = await client.get(wd_api, headers=headers)
            if resp.status_code == 403:
                logger.error("Wikidata rate limit detected (403) - stopping further requests")
                _rate_limited = True
                return missing_links
            if resp.status_code != 200:
                logger.warning(f"Wikidata fetch failed: {resp.status_code}")
                return missing_links

            wd_data = resp.json()
            entities = wd_data.get("entities", {})
            entity = entities.get(qid, {})

        claims = entity.get("claims", {})

        property_map = {
            "P1902": ("spotify_url", "https://open.spotify.com/artist/{}"),
            "P5749": ("tidal_url", "https://tidal.com/browse/artist/{}"),
            "P6573": ("qobuz_url", "https://play.qobuz.com/artist/{}"),
            "P3192": ("lastfm_url", "https://www.last.fm/music/{}"),
            "P1953": ("discogs_url", "https://www.discogs.com/artist/{}"),
            "P856": ("homepage", None), 
        }

        for prop_id, (service_name, url_template) in property_map.items():
            if existing_links.get(service_name):
                continue

            if prop_id not in claims:
                continue

            try:
                mainsnak = claims[prop_id][0].get("mainsnak", {})
                datavalue = mainsnak.get("datavalue", {})
                value = datavalue.get("value")

                if not value:
                    continue

                if url_template:
                    url = url_template.format(value)
                else:
                    url = value

                missing_links[service_name] = url

            except Exception as e:
                logger.warning(f"Failed to extract {service_name} from Wikidata: {e}")
                continue
        
        # Also extract Wikipedia URL from sitelinks if not already present
        if not existing_links.get("wikipedia_url"):
            try:
                sitelinks = entity.get("sitelinks", {})
                enwiki = sitelinks.get("enwiki", {})
                wiki_title = enwiki.get("title")
                if wiki_title:
                    wiki_url = f"https://en.wikipedia.org/wiki/{wiki_title.replace(' ', '_')}"
                    missing_links["wikipedia_url"] = wiki_url
            except Exception as e:
                logger.warning(f"Failed to extract Wikipedia URL from Wikidata: {e}")

    except Exception as e:
        logger.warning(f"Wikidata external links fetch failed: {e}")

    return missing_links

async def fetch_wikipedia_title(client: httpx.AsyncClient, wikidata_url: str) -> str:
    """
    Fetch Wikipedia title (English) from Wikidata URL.
    Returns: title string or None.
    """
    global _rate_limited
    
    # Skip if we've been rate limited
    if _rate_limited:
        logger.warning("Skipping Wikipedia title fetch - Wikidata previously rate limited (403)")
        return None
    
    try:
        qid = wikidata_url.split("/")[-1]
        wd_api = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
        get_api_tracker().increment("wikidata")
        
        # Wikidata requires User-Agent header
        headers = {"User-Agent": get_user_agent()}
        resp = await client.get(wd_api, headers=headers)
        if resp.status_code == 403:
            logger.error("Wikidata rate limit detected (403) in Wikipedia title fetch - stopping further requests")
            _rate_limited = True
            return None
        if resp.status_code == 200:
            wd_data = resp.json()
            entities = wd_data.get("entities", {})
            entity = entities.get(qid, {})
            sitelinks = entity.get("sitelinks", {})
            enwiki = sitelinks.get("enwiki", {})
            return enwiki.get("title")
    except Exception as e:
        logger.warning(f"Wikidata title resolution failed: {e}")
    return None
