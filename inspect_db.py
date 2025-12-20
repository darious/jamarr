import aiosqlite
import asyncio
from app.db import DB_PATH

async def inspect():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT name, mbid, image_url, art_id FROM artists WHERE name LIKE '%Bastille%' OR name LIKE '%Biffy%' OR name LIKE '%Bear%' OR name LIKE '%Maisie%'") as cursor:
            rows = await cursor.fetchall()
            print(f"Found {len(rows)} rows:")
            for row in rows:
                print(f"Name: {row['name']}")
                print(f"MBID: {row['mbid']}")
                print(f"Image URL: {row['image_url']}")
                print(f"Art ID: {row['art_id']}")
                if row['art_id']:
                    async with db.execute("SELECT sha1 FROM artwork WHERE id = ?", (row['art_id'],)) as art_cursor:
                        art_row = await art_cursor.fetchone()
                        if art_row:
                            print(f"SHA1: {art_row[0]}")
                print("-" * 20)

if __name__ == "__main__":
    asyncio.run(inspect())
