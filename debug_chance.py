import asyncio
import logging
import sys
from app.scanner.metadata import fetch_artist_metadata
import json

# Configure logging to see details
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

async def test_fetch():
    mbid = "373a4c98-a46b-48e4-86ec-f6ca65b4f438"
    name = "Chance the Rapper"
    
    print(f"Fetching metadata for {name} ({mbid})...")
    meta = await fetch_artist_metadata(mbid, name)
    print("\n--- Result ---")
    print(json.dumps(meta, indent=2))

if __name__ == "__main__":
    asyncio.run(test_fetch())
