
import asyncio
import os
import asyncpg

async def main():
    # Use port 8110 for host-mode networking from within other container if accessing via localhost of host, 
    # BUT wait: "docker exec -i jamarr" runs in the jamarr container.
    # The jamarr container sees "localhost" as ITSELF if not host mode?
    # db.py uses host=127.0.0.1 port=8110?
    # dev.sh says: "Network mode: host"
    # So localhost:8110 is correct.
    
    db_url = os.getenv("DATABASE_URL", "postgresql://jamarr:jamarr@localhost:8110/jamarr")
    print(f"Connecting to {db_url}...")
    try:
        conn = await asyncpg.connect(db_url)
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    try:
        print("Restoring albums from track table...")
        # Note: We omit release_type, description etc as they will be re-fetched.
        query = """
        INSERT INTO album (mbid, release_group_mbid, title, release_date, artwork_id)
        SELECT DISTINCT ON (release_mbid)
            release_mbid,
            release_group_mbid,
            album,
            release_date,
            artwork_id
        FROM track
        WHERE release_mbid IS NOT NULL
        ON CONFLICT (mbid) DO NOTHING;
        """
        result = await conn.execute(query)
        print(f"Insertion Result: {result}")
        
        # Verify
        count = await conn.fetchval("SELECT COUNT(*) FROM album")
        print(f"Total Albums in DB: {count}")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
