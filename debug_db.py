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
        print("\nChecking Bear's Den Artist Row...")
        async with db.execute("SELECT name, mbid, qobuz_url, musicbrainz_url FROM artists WHERE mbid = 'f11f6e85-a39a-4dd8-875b-cd84839ddec6'") as cursor:
            row = await cursor.fetchone()
            if row:
                print(f"Name: '{row[0]}'") # Quote to see if empty or space
                print(f"MBID: {row[1]}")
                print(f"Qobuz: {row[2]}")
                print(f"MB URL: {row[3]}")
            else:
                print("Row not found for Bear's Den MBID")
                
        print("\nChecking 'reputation' Album Tracks (for Appears On debug)...")
        async with db.execute("SELECT title, artist, album_artist, mb_artist_id, mb_album_artist_id FROM tracks WHERE album = 'reputation' LIMIT 5") as cursor:
             async for row in cursor:
                 print(f"Track: {row[0]}")
                 print(f"  Artist Tag: {row[1]}")
                 print(f"  Album Artist Tag: {row[2]}")
                 print(f"  MB Artist ID: {row[3]}")
                 print(f"  MB Album Artist ID: {row[4]}")
                 
        print("\nChecking 'Promises' (Track 7) Linkage...")
        query = "SELECT id, title, mb_artist_id, mb_track_id FROM tracks WHERE title = 'Promises' AND album = 'Give Me the Future'"
        async with db.execute(query) as cursor:
            async for row in cursor:
                tid = row[0]
                print(f"Track ID: {tid}, Title: {row[1]}")
                print(f"Tag MB Artist ID: {row[2]}")
                print(f"Tag MB Track ID: {row[3]}")
                
                # Check track_artists
                print("  Linked Artists in track_artists:")
                q2 = "SELECT mbid, (SELECT name FROM artists WHERE mbid = ta.mbid) as name FROM track_artists ta WHERE track_id = ?"
                async with db.execute(q2, (tid,)) as c2:
                    async for r2 in c2:
                         print(f"    MBID: {r2[0]} (Name: {r2[1]})")



if __name__ == "__main__":
    asyncio.run(check_db())
