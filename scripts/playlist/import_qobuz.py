#!/usr/bin/env python3
import asyncio
import argparse
import sys
import logging
import re
from typing import List, Dict, Any

# Add project root to path
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.scanner.services.qobuz import QobuzClient
from scripts.playlist.playlist_matcher import match_playlist_items

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

def parse_playlist_id(url: str) -> str:
    """Extract playlist ID from Qobuz URL."""
    # Matches https://play.qobuz.com/playlist/123456
    match = re.search(r"playlist/(\d+)", url)
    if match:
        return match.group(1)
    # Also support raw ID if passed
    if url.isdigit():
        return url
    return None

async def fetch_playlist_tracks(client: QobuzClient, playlist_id: str) -> List[Dict[str, Any]]:
    """Fetch all tracks from a playlist."""
    await client.login()
    
    url = "https://www.qobuz.com/api.json/0.2/playlist/get"
    headers = {
        "X-App-Id": client.app_id,
        "X-User-Auth-Token": client.user_auth_token
    }
    params = {
        "playlist_id": playlist_id,
        "limit": 500, # Try to get reasonable chunk
        "offset": 0,
        "extra": "tracks" 
    }
    
    logger.info(f"Fetching playlist {playlist_id}...")
    resp = await client.client.get(url, params=params, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    
    tracks_data = data.get("tracks", {}).get("items", [])
    
    # Check if we need pagination (simplified for now, assuming 500 covers most)
    # If total > 500, we might need loop.
    total = data.get("tracks", {}).get("total", 0)
    if total > len(tracks_data):
        logger.warning(f"Playlist has {total} tracks, but only fetched {len(tracks_data)}. Pagination not fully implemented.")
        
    formatted_items = []
    for i, item in enumerate(tracks_data):
        # API structure for tracks usually simpler or nested?
        # A quick check on structure: usually item is the track object directly or wrapper?
        # In playlist/get, items are usually track objects.
        
        artist = item.get("performer", {}).get("name")
        title = item.get("title")
        album = item.get("album", {}).get("title")
        position = i + 1
        
        formatted_items.append({
            "artist": artist,
            "title": title,
            "album": album,
            "position": position
        })
        
    return formatted_items

async def main():
    parser = argparse.ArgumentParser(description="Import Qobuz Playlist")
    parser.add_argument("url", help="Qobuz Playlist URL or ID")
    parser.add_argument("--output", "-o", type=str, help="Output file (default: qobuz_{id}.txt)")
    parser.add_argument("--db-host", type=str, help="Database host")
    
    args = parser.parse_args()
    
    playlist_id = parse_playlist_id(args.url)
    if not playlist_id:
        logger.error("Invalid playlist URL or ID")
        sys.exit(1)
        
    output_file = args.output or f"qobuz_{playlist_id}.txt"
    
    # 1. Fetch from Qobuz
    client = QobuzClient()
    try:
        items = await fetch_playlist_tracks(client, playlist_id)
    except Exception as e:
        logger.error(f"Failed to fetch playlist: {e}")
        await client.close()
        return
    finally:
        await client.close()
        
    if not items:
        logger.warning("No tracks found in playlist.")
        return

    # 2. Match
    results = await match_playlist_items(items, db_host=args.db_host)
    
    # 3. Write Output
    with open(output_file, "w") as f:
        f.write("track_id,position\n")
        for track_id, position in results:
            f.write(f"{track_id},{position}\n")
            
    logger.info(f"Output written to {output_file}")

if __name__ == "__main__":
    asyncio.run(main())
