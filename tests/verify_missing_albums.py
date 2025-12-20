import asyncio
import logging
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from app.scanner.metadata import fetch_artist_albums

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def verify():
    # Test with Daft Punk (MBID: 056e4f3e-d505-4dad-8ec1-d04f521cbb56)
    # Expected: "Homework", "Discovery", "Human After All", "Random Access Memories", etc.
    mbid = "056e4f3e-d505-4dad-8ec1-d04f521cbb56"
    name = "Daft Punk"
    
    print(f"Fetching albums for {name} ({mbid})...")
    albums = await fetch_artist_albums(mbid, name)
    
    print(f"Found {len(albums)} albums:")
    found_discovery = False
    
    for a in albums:
        print(f"- {a['date']} | {a['title']}")
        print(f"  MB: {a['musicbrainz_url']}")
        print(f"  Qobuz URL: {a['qobuz_url']}")
        print(f"  Qobuz ID: {a['qobuz_id']}")
        
        if "Discovery" in a['title']:
            found_discovery = True

    if found_discovery:
        print("\nSUCCESS: Found 'Discovery' album.")
    else:
        print("\nFAILURE: Did not find 'Discovery' album.")

if __name__ == "__main__":
    asyncio.run(verify())
