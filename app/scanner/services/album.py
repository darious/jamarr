import asyncio
import httpx
import logging
import re
from bs4 import BeautifulSoup, Tag
from app.scanner.services import wikidata
from app.scanner.stats import get_api_tracker
from app.config import get_user_agent

logger = logging.getLogger("scanner.services.album")

async def fetch_album_metadata(mbid: str, client: httpx.AsyncClient, dns_semaphore: asyncio.Semaphore = None):
    """
    Fetch album metadata: Description, Producer, Chart Position, External Links.
    Returns a dict with:
    - description
    - peak_chart_position
    - external_links (list of tuples (type, url))
    """
    result = {
        "description": None,
        "peak_chart_position": None,
        "external_links": [],
        "producer": None, # Optional, if we want to store it later
    }
    
    # 1. Fetch Request Group + Relations from MusicBrainz
    try:
        # We rely on specific MB root if local, else default
        # Using config.get_mb_api_root is cleaner if it exists or use passed client config
        # The script used MB_API_ROOT variable.
        # In app/scanner/services/musicbrainz.py it uses MB_API_ROOT from config.
        # Let's import it or assume client is pre-configured? 
        # Actually musicbrainz.py has get_mb_api_root logic.
        pass
    except Exception:
        pass
        
    # We will use the client passed in, which should be configured.
    # Actually, we need to construct the URL.
    # Let's import the root from config.
    from app.config import get_musicbrainz_root_url
    mb_root = get_musicbrainz_root_url()
    user_agent = get_user_agent()
    
    url = f"{mb_root}/ws/2/release-group/{mbid}?inc=url-rels+artist-credits&fmt=json"
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    
    try:
        get_api_tracker().increment("musicbrainz")
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            logger.warning(f"MB Album fetch failed for {mbid}: {resp.status_code}")
            return result
            
        data = resp.json()
    except Exception as e:
        logger.error(f"MB Request Error for {mbid}: {e}")
        return result
        
    # 2. Parse Relations
    relations = data.get("relations", [])
    wikidata_url = None
    
    for rel in relations:
        target = rel.get("url", {}).get("resource")
        type_ = rel.get("type", "")
        
        if not target:
            continue
            
        if type_ == "wikidata":
            wikidata_url = target
            result["external_links"].append(("wikidata", target))
        elif "discogs.com" in target:
             result["external_links"].append(("discogs", target))
    
    # Ensure we store the MusicBrainz link itself
    # Use the Release Group URL as the album link
    # This matches the user's request to "ensure every album has a musicbrainz link"
    mb_link = f"https://musicbrainz.org/release-group/{mbid}"
    result["external_links"].append(("musicbrainz", mb_link))
    
    
    # 3. Resolve Wikipedia URL via Wikidata
    wikipedia_url = None
    if wikidata_url:
        try:
            # Use semaphore to limit concurrent DNS requests
            if dns_semaphore:
                async with dns_semaphore:
                    wiki_title = await wikidata.fetch_wikipedia_title(client, wikidata_url)
            else:
                wiki_title = await wikidata.fetch_wikipedia_title(client, wikidata_url)
                
            if wiki_title:
                # Construct URL (English)
                wikipedia_url = f"https://en.wikipedia.org/wiki/{wiki_title.replace(' ', '_')}"
                result["external_links"].append(("wikipedia", wikipedia_url))
        except Exception as e:
            # Track DNS errors
            if "Temporary failure in name resolution" in str(e):
                from app.scanner.services.coordinator import _dns_error_count, _dns_error_lock
                async with _dns_error_lock:
                    _dns_error_count += 1
                    if _dns_error_count > 50:
                        logger.error(f"Too many DNS failures ({_dns_error_count}), stopping scan")
                        raise RuntimeError(f"DNS resolver overloaded: {_dns_error_count} failures") from e
            logger.warning(f"Wikidata resolution failed for {mbid}: {e}")
            
    # 4. Scrape Wikipedia if URL found
    if wikipedia_url:
        try:
             scrape_data = await _scrape_wikipedia_details(client, wikipedia_url, user_agent)
             if scrape_data:
                 result["description"] = scrape_data.get("description")
                 result["peak_chart_position"] = scrape_data.get("uk_chart_position")
                 result["producer"] = scrape_data.get("producer")
        except Exception as e:
            logger.warning(f"Wikipedia scrape error for {wikipedia_url}: {e}")
            
    return result

async def _scrape_wikipedia_details(client: httpx.AsyncClient, url: str, user_agent: str):
    """
    Scrapes Wikipedia page for description, producer in infobox, and UK chart position.
    """
    get_api_tracker().increment("wikipedia")
    resp = await client.get(url, headers={"User-Agent": user_agent}, follow_redirects=True)
    if resp.status_code != 200:
        return None
        
    soup = BeautifulSoup(resp.text, "html.parser")
    
    ret = {
        "description": None,
        "producer": None,
        "uk_chart_position": None
    }
    
    # A. Description (First valid paragraph)
    # Refined logic from script
    content_div = soup.find("div", {"id": "mw-content-text"})
    if content_div:
        parser_output = content_div.find("div", class_="mw-parser-output")
        if parser_output:
            for child in parser_output.children:
                if isinstance(child, Tag):
                    if child.name == "p":
                        text = child.get_text().strip()
                        if text:
                            ret["description"] = text
                            break
                    elif child.name in ["div", "table"] and ("infobox" in child.get("class", []) or "tright" in child.get("class", [])):
                        # Skip infoboxes/tables
                        continue
                        
    # B. Producer (Infobox)
    infobox = soup.find("table", class_="infobox")
    if infobox:
        rows = infobox.find_all("tr")
        for row in rows:
            header = row.find("th")
            if header and "Producer" in header.get_text():
                data = row.find("td")
                if data:
                    # Clean up lists (li) or breaks
                    ret["producer"] = data.get_text(separator="\n").strip()
                    break
                    
    # C. UK CHART POSITION
    # Look for table with "Chart" in caption or headers
    tables = soup.find_all("table", class_=["wikitable", "sortable"])
    
    found_chart = False
    for table in tables:
        if found_chart:
             break
        
        # Check headers for "Chart" and "Peak"
        headers = [th.get_text().strip().lower() for th in table.find_all("th")]
        if not any("chart" in h for h in headers):
            continue
            
        # Check rows for "UK" or "United Kingdom"
        # Column index for "Peak position" often varies, usually 2nd column? 
        # But we can assume the numeric column is the position.
        
        # Determine position column index
        pos_idx = -1
        for i, h in enumerate(headers):
            if "peak" in h or "position" in h:
                pos_idx = i
                break
        
        # If no explicit header, assume last or look for digits
        
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["th", "td"])
            if not cells:
                continue
            
            row_text = row.get_text().lower()
            if "united kingdom" in row_text or "uk albums" in row_text or "uk rock" in row_text: # specific chart types?
                 # Try to extract the number
                 # Usually matches the 'Peak position' column if identified
                 target_cell = None
                 if pos_idx != -1 and len(cells) > pos_idx:
                      target_cell = cells[pos_idx]
                 else:
                      # Try to find the cell with a number
                       for cell in cells:
                           txt = cell.get_text().strip()
                           if re.match(r"^\d+$", txt):
                               target_cell = cell
                               break
                               
                 if target_cell:
                     try:
                         # Handle "1[2]" refs
                         clean_txt = re.sub(r"\[.*?\]", "", target_cell.get_text()).strip()
                         val = int(clean_txt)
                         ret["uk_chart_position"] = val
                         found_chart = True
                         break
                     except Exception:
                         pass
                         
    return ret
