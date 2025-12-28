import httpx
import logging
from app.scanner.stats import get_api_tracker

logger = logging.getLogger("scanner.services.wikidata")

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
    missing_links = {}

    try:
        qid = wikidata_url.split("/")[-1]

        if cached_entity:
            entity = cached_entity
        else:
            wd_api = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
            get_api_tracker().increment("wikidata")
            resp = await client.get(wd_api)
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
            "P6573": ("qobuz_url", "https://www.qobuz.com/us-en/interpreter/{}"),
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

    except Exception as e:
        logger.warning(f"Wikidata external links fetch failed: {e}")

    return missing_links

async def fetch_wikipedia_title(client: httpx.AsyncClient, wikidata_url: str) -> str:
    """
    Fetch Wikipedia title (English) from Wikidata URL.
    Returns: title string or None.
    """
    try:
        qid = wikidata_url.split("/")[-1]
        wd_api = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
        get_api_tracker().increment("wikidata")
        
        resp = await client.get(wd_api)
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
