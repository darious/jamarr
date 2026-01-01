
import asyncio
import os
import asyncpg

async def main():
    db_url = os.getenv("DATABASE_URL", "postgresql://jamarr:jamarr@localhost:8110/jamarr")
    conn = await asyncpg.connect(db_url)
    try:
        track_count = await conn.fetchval("SELECT COUNT(*) FROM track")
        album_count = await conn.fetchval("SELECT COUNT(*) FROM album")
        print(f"Tracks: {track_count}")
        print(f"Albums: {album_count}")
        
        if album_count == 0 and track_count > 0:
            print("Tracks exist but Albums are empty. Attempting to list some tracks...")
            rows = await conn.fetch("SELECT release_mbid, release_group_mbid FROM track LIMIT 5")
            for r in rows:
                print(f"Track: rel_mbid={r['release_mbid']}, rg_mbid={r['release_group_mbid']}")

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
