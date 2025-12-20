
import asyncio
from app.db import init_db, get_db

async def debug_search():
    await init_db()
    async for db in get_db():
        print("--- Searching Artists Table ---")
        async with db.execute("SELECT * FROM artists WHERE name LIKE '%Chance%'") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                print(f"Artist Found: {row}")
        
        print("\n--- Searching Tracks Table ---")
        async with db.execute("SELECT id, artist, mb_artist_id, title FROM tracks WHERE artist LIKE '%Chance%'") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                print(f"Track Found: ID={row[0]}, Artist='{row[1]}', MBID='{row[2]}', Title='{row[3]}'")

if __name__ == "__main__":
    asyncio.run(debug_search())
