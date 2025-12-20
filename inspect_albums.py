import aiosqlite
import asyncio
from app.db import DB_PATH

async def inspect():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        print("--- Elysium ---")
        async with db.execute("SELECT id, path, album, art_id FROM tracks WHERE album = 'Elysium'") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                print(f"Track: {row['path']}")
                print(f"Album: {row['album']}")
                print(f"Art ID: {row['art_id']}")
                if row['art_id']:
                     async with db.execute("SELECT sha1, type FROM artwork WHERE id = ?", (row['art_id'],)) as art:
                         arow = await art.fetchone()
                         print(f" -> SHA1: {arow['sha1']} (Type: {arow['type']})")

        print("\n--- Blue Hours ---")
        async with db.execute("SELECT id, path, album, art_id FROM tracks WHERE album = 'Blue Hours'") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                print(f"Track: {row['path']}")
                print(f"Album: {row['album']}")
                print(f"Art ID: {row['art_id']}")
                if row['art_id']:
                     async with db.execute("SELECT sha1, type FROM artwork WHERE id = ?", (row['art_id'],)) as art:
                         arow = await art.fetchone()
                         print(f" -> SHA1: {arow['sha1']} (Type: {arow['type']})")

if __name__ == "__main__":
    asyncio.run(inspect())
