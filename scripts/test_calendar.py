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
        # New calendar-day query
        new_query = """
            SELECT 
                a.name as artist_name, 
                a.mbid as artist_mbid,
                COUNT(DISTINCT h.source_id) as plays
            FROM combined_playback_history_mat h
            JOIN track t ON t.id = h.track_id
            JOIN track_artist ta ON ta.track_id = t.id
            JOIN artist a ON ta.artist_mbid = a.mbid
            WHERE h.played_at >= (CURRENT_DATE - make_interval(days => $1 - 1))
              AND a.name = 'Eddie Vedder'
            GROUP BY a.name, a.mbid
        """
        
        print("New calendar-day query (>= CURRENT_DATE - 6 for 7 days):")
        result = await conn.fetchrow(new_query, 7)
        if result:
            print(f"  Eddie Vedder: {result['plays']} plays")
        else:
            print("  No results")
        
        # Also check what CURRENT_DATE is
        date_check = await conn.fetchrow("SELECT CURRENT_DATE, NOW()")
        print(f"\nCURRENT_DATE: {date_check['current_date']}")
        print(f"NOW(): {date_check['now']}")
        print(f"CURRENT_DATE - 6: {date_check['current_date']} - 6 days")

if __name__ == "__main__":
    asyncio.run(main())
