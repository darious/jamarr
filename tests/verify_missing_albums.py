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
    # Test with Haim (MBID: aef06569-098f-4218-a577-b413944d9493)
    mbid = "aef06569-098f-4218-a577-b413944d9493"
    name = "Haim"
    
    print(f"Fetching albums for {name} ({mbid})...")
    albums = await fetch_artist_albums(mbid, name)
    
    found_women = False
    correct_id_women = False
    found_stty = False
    correct_id_stty = False

    for a in albums:
        if "Women in Music" in a['title']: 
             found_women = True
             if a['qobuz_id'] == "wpwvp04bzobta":
                 correct_id_women = True
        
        if "Something to Tell You" in a['title']:
             found_stty = True
             # We expect the ID that works with GET: 0060255775158 or similar valid one
             print(f"DEBUG: Found STTY - ID: {a['qobuz_id']}")
             if a['qobuz_id'] in ["0060255775158", "0060255767157"]: # Accepted IDs seen in debug
                 correct_id_stty = True

    if found_women and correct_id_women:
        print("SUCCESS: 'Women in Music, Pt. III' verified.")
    else:
        print("FAILURE: 'Women in Music, Pt. III' check failed.")

    if found_stty and correct_id_stty:
        print("SUCCESS: 'Something to Tell You' verified.")
    else:
        print("FAILURE: 'Something to Tell You' check failed.")

if __name__ == "__main__":
    asyncio.run(verify())
