import asyncio
import time
import logging
import httpx
from app.scanner.metadata import fetch_artist_albums

# Configure logging to see our debug prints
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
# Silence httpx details
logging.getLogger("httpx").setLevel(logging.WARNING)

async def test_performance():
    # Justin Bieber MBID: e0140a67-e4d1-4f13-8a01-364355bee46e
    mbid = "e0140a67-e4d1-4f13-8a01-364355bee46e" 
    artist_name = "Justin Bieber"
    
    print(f"--- Starting Performance Test for {artist_name} ---")
    start_time = time.time()
    
    # Run the fetch
    async with httpx.AsyncClient(headers={"User-Agent": "JamarrTest/0.1"}) as client:
        albums = await fetch_artist_albums(mbid, artist_name, client)
        
    end_time = time.time()
    duration = end_time - start_time
    
    print(f"\n--- Test Completed ---")
    print(f"Total Time: {duration:.2f} seconds")
    print(f"Total Albums Found: {len(albums)}")
    
    print("\nSample Albums:")
    for a in albums[:5]:
        print(f" - {a['title']} ({a['date']}) -> {a['qobuz_url']}")

if __name__ == "__main__":
    asyncio.run(test_performance())
