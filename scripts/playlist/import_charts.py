#!/usr/bin/env python3
import asyncio
import argparse
import httpx
import sys
import logging
from typing import Dict, Any, List

# Add project root to path
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import db


# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

async def fetch_chart_data(year: int) -> List[Dict[str, Any]]:
    base_url = "https://backstage.officialcharts.com/ce-api"
    # Try common URL patterns
    # The JSON navigation showed format: /charts/end-of-year-singles-chart/{year}0101/37501
    # But let's start with the year-based URL and follow redirects
    
    # 1. Fetch the base chart to get the navigation list
    # The API seems to map "2025" key to the 2024 chart (published Jan 2025)
    # So we need to look for key = year + 1
    
    base_nav_url = f"{base_url}/charts/end-of-year-singles-chart/"
    target_year_key = str(year)
    
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        logger.info(f"Fetching base navigation from {base_nav_url}...")
        resp = await client.get(base_nav_url)
        resp.raise_for_status()
        base_data = resp.json()
        
        # Handle initial redirect if any (though usually base url works)
        if "redirect" in base_data and base_data["redirect"].get("statusCode") == 302:
             # Just follow it to get the list
             redirect_url = base_data["redirect"]["url"]
             full_url = f"{base_url}{redirect_url}"
             logger.info(f"Following base redirect to {full_url}...")
             resp = await client.get(full_url)
             resp.raise_for_status()
             base_data = resp.json()
             
        # Find the correct URL in 'annual' list
        annual_list = []
        content = base_data.get("content", {})
        if "annual" in content:
            annual_list = content["annual"]
        elif "rows" in content and isinstance(content["rows"], list) and content["rows"]:
            # Base landing page often returns a view with rows
            row = content["rows"][0]
            if "annual" in row:
                annual_list = row["annual"]

        target_item = next((item for item in annual_list if item.get("year") == target_year_key), None)
        
        if not target_item:
            logger.warning(f"Could not find entry for year {target_year_key} (for Chart {year}) in annual list.")
            logger.info(f"Available sorted years: {sorted([i.get('year') for i in annual_list], reverse=True)}")
            logger.error("No suitable chart found.")
            sys.exit(1)
        
        chart_url_suffix = target_item["url"]
        final_url = f"{base_url}{chart_url_suffix}"
        
        logger.info(f"Fetching specific chart data from {final_url}...")
        resp = await client.get(final_url)
        resp.raise_for_status()
        data = resp.json()

        # Navigate to chart items
        try:
            # Path discovered: root.content.sections[0].content[0].content[0].chartItems
            # We iterate carefully to avoid crashes
            sections = data.get("content", {}).get("sections", [])
            if not sections:
                raise ValueError("No sections found in response")
            
            section_content = sections[0].get("content", [])
            if not section_content:
                 raise ValueError("Section has no content")
                 
            # Find the block containing chartItems
            # It was the first item in our exploration
            target_block = None
            for item in section_content:
                if "content" in item and isinstance(item["content"], list):
                    for subitem in item["content"]:
                        if "chartItems" in subitem:
                            target_block = subitem
                            break
                if target_block: 
                    break
            
            if not target_block:
                raise ValueError("Could not locate chartItems in JSON structure")
                
            return target_block["chartItems"]
            
        except Exception as e:
            logger.error(f"Error parsing JSON structure: {e}")
            sys.exit(1)

async def main():
    parser = argparse.ArgumentParser(description="Import Official Charts End of Year Singles")
    parser.add_argument("year", type=int, help="Year of the chart (e.g. 2024)")
    parser.add_argument("--limit", type=int, default=100, help="Limit number of tracks to process")
    parser.add_argument("--output", "-o", type=str, help="Output file (default: chart_{year}.txt)")
    parser.add_argument("--db-host", type=str, help="Database host (default: from env or 127.0.0.1)")
    
    args = parser.parse_args()
    output_file = args.output or f"chart_{args.year}.txt"

    # Configure DB host if provided
    if args.db_host:
        db.DB_HOST = args.db_host
    
    # 1. Fetch Chart Data
    try:
        items = await fetch_chart_data(args.year)
    except Exception as e:
        logger.error(f"Failed to fetch chart: {e}")
        return

    # Filter and limit
    items = items[:args.limit]
    # 2. Match Items
    from scripts.playlist.playlist_matcher import match_playlist_items
    
    # Prepare items for matcher
    matcher_items = []
    for item in items:
        matcher_items.append({
            "artist": item["artist"],
            "title": item["title"],
            "album": "",
            "position": item["position"]
        })
        
    results = await match_playlist_items(matcher_items, db_host=args.db_host)
    
    # 3. Write Output
    with open(output_file, "w") as f:
        f.write("track_id,position\n")
        for track_id, position in results:
            f.write(f"{track_id},{position}\n")
        
    logger.info(f"Output written to {output_file}")

if __name__ == "__main__":
    asyncio.run(main())
