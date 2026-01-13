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
        # Check what NOW() - 7 days actually is
        date_check = await conn.fetchrow("SELECT NOW() as now, NOW() - make_interval(days => 7) as seven_days_ago")
        print(f"NOW(): {date_check['now']}")
        print(f"7 days ago: {date_check['seven_days_ago']}")
        print()
        
        # User's specific query
        user_query = """
            SELECT 
                a.name as artist_name, 
                a.mbid as artist_mbid,
                COUNT(DISTINCT h.source_id) as plays
            FROM combined_playback_history_mat h
            JOIN track t ON t.id = h.track_id
            JOIN track_artist ta ON ta.track_id = t.id
            JOIN artist a ON ta.artist_mbid = a.mbid
            WHERE h.played_at between '2026-01-07' and '2026-01-13'
              AND a.name = 'Eddie Vedder'
            GROUP BY a.name, a.mbid
        """
        
        # My rolling query
        my_query = """
            SELECT 
                a.name as artist_name, 
                a.mbid as artist_mbid,
                COUNT(DISTINCT h.source_id) as plays
            FROM combined_playback_history_mat h
            JOIN track t ON t.id = h.track_id
            JOIN track_artist ta ON ta.track_id = t.id
            JOIN artist a ON ta.artist_mbid = a.mbid
            WHERE h.played_at > NOW() - make_interval(days => 7)
              AND a.name = 'Eddie Vedder'
            GROUP BY a.name, a.mbid
        """
        
        print("User's query (BETWEEN '2026-01-07' and '2026-01-13'):")
        result = await conn.fetchrow(user_query)
        if result:
            print(f"  Eddie Vedder: {result['plays']} plays")
        else:
            print("  No results")
        print()
        
        print("My query (> NOW() - 7 days):")
        result = await conn.fetchrow(my_query)
        if result:
            print(f"  Eddie Vedder: {result['plays']} plays")
        else:
            print("  No results")

if __name__ == "__main__":
    asyncio.run(main())
