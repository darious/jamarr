import asyncio
import os
import asyncpg

async def main():
    db_url = os.getenv("DATABASE_URL", "postgresql://jamarr:jamarr@jamarr_db/jamarr")
    conn = await asyncpg.connect(db_url)
    
    print("--- Searching for Eddie Vedder Plays (Last 7 Days) ---")
    
    # Check History Table directly
    query = """
        SELECT 
            t.artist, 
            t.album_artist, 
            t.artist_mbid,
            count(*) as plays,
            min(h.played_at) as first_play,
            max(h.played_at) as last_play
        FROM combined_playback_history_mat h
        JOIN track t ON h.track_id = t.id
        WHERE (t.artist ILIKE '%Eddie Vedder%' OR t.album_artist ILIKE '%Eddie Vedder%')
          AND h.played_at > NOW() - INTERVAL '7 days'
        GROUP BY t.artist, t.album_artist, t.artist_mbid
    """
    
    rows = await conn.fetch(query)
    for r in rows:
        print(dict(r))
        
    print("\n--- Checking Artist Table for MBIDs ---")
    # Verify if these MBIDs exist in Artist table
    mbids = set([r['artist_mbid'] for r in rows if r['artist_mbid']])
    if mbids:
        for mbid in mbids:
            a_row = await conn.fetchrow("SELECT * FROM artist WHERE mbid = $1", mbid)
            if a_row:
                print(f"MBID {mbid} FOUND in Artist table: {a_row['name']}")
                if not a_row['image_url'] and not a_row['artwork_id']:
                    print("  -> Has NO image_url or artwork_id")
            else:
                print(f"MBID {mbid} NOT FOUND in Artist table!")
    else:
        print("No MBIDs found on tracks.")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
