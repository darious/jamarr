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
        users = await conn.fetch('SELECT id, username FROM "user"')
        print(f"Found {len(users)} users\n")
        
        for user in users:
            user_id = user['id']
            username = user['username']
            
            # Test 7 days
            count_query_7 = """
                SELECT 
                    a.name,
                    COUNT(DISTINCT cph.source_id) as plays
                FROM combined_playback_history_mat cph
                JOIN track t ON cph.track_id = t.id
                JOIN track_artist ta ON ta.track_id = t.id
                JOIN artist a ON ta.artist_mbid = a.mbid
                WHERE cph.user_id = $1
                  AND cph.played_at > NOW() - make_interval(days => 7)
                  AND (a.name LIKE '%Eddie Vedder%' OR a.name LIKE '%Pearl Jam%')
                GROUP BY a.name
            """
            
            # Test 30 days
            count_query_30 = """
                SELECT 
                    a.name,
                    COUNT(DISTINCT cph.source_id) as plays
                FROM combined_playback_history_mat cph
                JOIN track t ON cph.track_id = t.id
                JOIN track_artist ta ON ta.track_id = t.id
                JOIN artist a ON ta.artist_mbid = a.mbid
                WHERE cph.user_id = $1
                  AND cph.played_at > NOW() - make_interval(days => 30)
                  AND (a.name LIKE '%Eddie Vedder%' OR a.name LIKE '%Pearl Jam%')
                GROUP BY a.name
            """
            
            rows_7 = await conn.fetch(count_query_7, user_id)
            rows_30 = await conn.fetch(count_query_30, user_id)
            
            print(f"User {user_id} ({username}):")
            if rows_7:
                for row in rows_7:
                    print(f"  7 days:  {row['name']}: {row['plays']} plays")
            else:
                print("  7 days:  No Eddie Vedder/Pearl Jam plays")
                
            if rows_30:
                for row in rows_30:
                    print(f"  30 days: {row['name']}: {row['plays']} plays")
            else:
                print("  30 days: No Eddie Vedder/Pearl Jam plays")
            print()

if __name__ == "__main__":
    asyncio.run(main())
