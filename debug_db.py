import aiosqlite
import asyncio
import os

DB_PATH = "cache/library.sqlite"

async def check_db():
    if not os.path.exists(DB_PATH):
        print("DB not found!")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("PRAGMA table_info(artists)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
            print("Columns in artists table:", columns)
            
            missing = [col for col in ["wikipedia_url", "qobuz_url", "musicbrainz_url", "spotify_url"] if col not in columns]
            if missing:
                print("MISSING COLUMNS:", missing)
            else:
                print("All columns present.")

        print("\nChecking Bastille...")
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM artists WHERE name LIKE '%Bastille%'") as cursor:
            row = await cursor.fetchone()
            if row:
                print(f"Found artist: {row['name']}")
                print(f"MBID: {row['mbid']}")
                print(f"MusicBrainz: {row['musicbrainz_url']}")
                print(f"Wikipedia: {row['wikipedia_url']}")
                print(f"Qobuz: {row['qobuz_url']}")
                print(f"Spotify: {row['spotify_url']}")
        print("\nChecking 'Islands' Album...")
        async with db.execute("SELECT id, title, artist, album FROM tracks WHERE album = 'Islands'") as cursor:
            async for row in cursor:
                print(f"Track: {row['title']} (ID: {row['id']})")
                print(f"  Artist Tag: {row['artist']}")
                
                # Check track_artists
                async with db.execute("SELECT mbid FROM track_artists WHERE track_id = ?", (row['id'],)) as ta_cursor:
                    mbids = await ta_cursor.fetchall()
                    print(f"  Linked MBIDs: {[m[0] for m in mbids]}")
                    
        print("\nChecking Artists Table for linked MBIDs...")
        async with db.execute("SELECT name, mbid, image_url FROM artists") as cursor:
            async for row in cursor:
                print(f"Artist: {row['name']}")
                print(f"  MBID: {row['mbid']}")
                print(f"  Image: {row['image_url']}")



if __name__ == "__main__":
    asyncio.run(check_db())
