import asyncio
import os
import sys

sys.path.append(os.getcwd())

from app.db import get_pool, init_db

async def main():
    print("Connecting to DB...")
    await init_db()
    pool = get_pool()
    
    async with pool.acquire() as conn:
        user = await conn.fetchrow('SELECT id FROM "user" LIMIT 1')
        if not user:
            print("No users found")
            return
        
        user_id = user['id']
        days = 7
        print(f"Testing with user_id: {user_id}, days: {days}")
        
        # Test the exact query from get_seeds with 7 days
        query = """
            WITH recent_plays AS (
                SELECT 
                    a.mbid as artist_mbid,
                    a.name as artist_name,
                    cph.source_id,
                    cph.played_at,
                    EXP(-(EXTRACT(EPOCH FROM (NOW() - cph.played_at)) / 86400.0) / 7.0) as weight
                FROM combined_playback_history_mat cph
                JOIN track t ON cph.track_id = t.id
                JOIN track_artist ta ON ta.track_id = t.id
                JOIN artist a ON ta.artist_mbid = a.mbid
                WHERE cph.user_id = $1
                  AND cph.played_at <= NOW()
                  AND cph.played_at > NOW() - make_interval(days => $2)
            ),
            scored_artists AS (
                SELECT
                    artist_mbid,
                    MAX(artist_name) as name,
                    SUM(weight) * (1 + LN(COUNT(DISTINCT source_id) + 1)) as score,
                    COUNT(DISTINCT source_id) as play_count,
                    MAX(played_at) as last_played_at
                FROM recent_plays
                GROUP BY artist_mbid
            )
            SELECT 
                sa.*,
                a.image_url,
                art.sha1 as art_sha1
            FROM scored_artists sa
            JOIN artist a ON sa.artist_mbid = a.mbid
            LEFT JOIN artwork art ON a.artwork_id = art.id
            ORDER BY sa.score DESC
            LIMIT 50
        """
        
        rows = await conn.fetch(query, user_id, days)
        print(f"\nGot {len(rows)} seeds")
        
        # Find Eddie Vedder
        for row in rows:
            if 'Eddie Vedder' in row['name'] or 'Pearl Jam' in row['name']:
                print(f"\n{row['name']}: {row['play_count']} plays")
                print(f"  Score: {row['score']}")
                print(f"  Last played: {row['last_played_at']}")
                
        # Also test the raw count
        count_query = """
            SELECT 
                a.name,
                COUNT(DISTINCT cph.source_id) as plays
            FROM combined_playback_history_mat cph
            JOIN track t ON cph.track_id = t.id
            JOIN track_artist ta ON ta.track_id = t.id
            JOIN artist a ON ta.artist_mbid = a.mbid
            WHERE cph.user_id = $1
              AND cph.played_at > NOW() - make_interval(days => $2)
              AND (a.name LIKE '%Eddie Vedder%' OR a.name LIKE '%Pearl Jam%')
            GROUP BY a.name
        """
        
        print("\n--- Raw count for Eddie Vedder/Pearl Jam (7 days) ---")
        rows = await conn.fetch(count_query, user_id, days)
        for row in rows:
            print(f"{row['name']}: {row['plays']} plays")

if __name__ == "__main__":
    asyncio.run(main())
