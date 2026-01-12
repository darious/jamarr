
import asyncio
import os
import sys

# Add app to path
sys.path.append(os.getcwd())

from app.db import get_pool, init_db
from app.api.recommendation import get_seeds, get_recommendations, RecommendedTrack, TrackArtist, TrackAlbum, TrackArtwork, SeedArtist

async def main():
    print("Connecting to DB...")
    await init_db()
    pool = get_pool()
    
    # We need a valid user_id. Let's assume 1 or fetch one.
    async with pool.acquire() as conn:
        user = await conn.fetchrow('SELECT id FROM "user" LIMIT 1')
        if not user:
            print("No users found")
            return
        
        user_id = user['id']
        print(f"Testing with user_id: {user_id}")

        # Seed dummy data
        print("Seeding dummy history...")
        # Create dummy artist
        artist_mbid = 'c8b03190-306c-4120-bb0b-6f200cd42fc9'
        await conn.execute("INSERT INTO artist (mbid, name) VALUES ($1, 'The Weeknd') ON CONFLICT (mbid) DO NOTHING", artist_mbid)
        
        # Create dummy track
        track_row = await conn.fetchrow("SELECT id FROM track WHERE path = '/tmp/test.mp3'")
        if track_row:
             track_id = track_row['id']
        else:
             track_id = await conn.fetchval("""
                INSERT INTO track (title, artist, artist_mbid, path, duration_seconds) 
                VALUES ('Blinding Lights', 'The Weeknd', $1, '/tmp/test.mp3', 200) 
                RETURNING id
            """, artist_mbid)

        # Insert track_artist entry
        await conn.execute("INSERT INTO track_artist (track_id, artist_mbid) VALUES ($1, $2) ON CONFLICT DO NOTHING", track_id, artist_mbid)

        # Create dummy playback history
        await conn.execute('INSERT INTO playback_history (user_id, track_id, "timestamp") VALUES ($1, $2, NOW() - INTERVAL \'1 day\')', user_id, track_id)
        
        # Add similar artist
        daft_punk_mbid = '056e4f3e-d505-4dad-8ec1-d04f521cbb56'
        await conn.execute("INSERT INTO artist (mbid, name) VALUES ($1, 'Daft Punk') ON CONFLICT (mbid) DO NOTHING", daft_punk_mbid)
        
        # Check if exists
        exists = await conn.fetchval("SELECT 1 FROM similar_artist WHERE artist_mbid = $1 AND similar_artist_mbid = $2", artist_mbid, daft_punk_mbid)
        if not exists:
            await conn.execute("""
                INSERT INTO similar_artist (artist_mbid, similar_artist_mbid, similar_artist_name, rank)
                VALUES ($1, $2, 'Daft Punk', 1)
            """, artist_mbid, daft_punk_mbid)
        
        print("Refreshing materialized view...")
        await conn.execute("REFRESH MATERIALIZED VIEW combined_playback_history_mat")

        recs = []
        try:
            print("\n--- Testing get_seeds ---")
            seeds = await get_seeds(conn, user_id, 30)
            print(f"Got {len(seeds)} seeds")
            
            # Check for Eddie Vedder specifically in the seed list
            eddie_seeds = [s for s in seeds if 'Eddie Vedder' in s["name"] or 'Pearl Jam' in s["name"]]
            if eddie_seeds:
                print("\n--- EDDIE VEDDER / PEARL JAM SEEDS FOUND ---")
                for s in eddie_seeds:
                    print(f"Name: {s['name']}, Score: {s['score']}, Play Count: {s['play_count']}, Artist MBID: {s['artist_mbid']}")
                    print(f"Image: {s['image_url']}, Art SHA1: {s['art_sha1']}")
            else:
                print("\n--- NO EDDIE VEDDER / PEARL JAM SEEDS FOUND ---")
                
            if seeds:
                # from app.api.recommendation import SeedArtist (Imported at top)
                print("Validating first seed with SeedArtist model...")
                s = seeds[0]
                # Manual mapping as done in endpoint
                sa = SeedArtist(
                    mbid=s["artist_mbid"],
                    name=s["name"],
                    score=s["score"],
                    play_count=s["play_count"],
                    last_played_at=s["last_played_at"],
                    image_url=s["image_url"],
                    art_sha1=s["art_sha1"]
                )
                print(f"Validation success: {sa}")
                
            for s in seeds[:3]:
                print(s)

            print("\n--- Testing get_recommendations ---")
            seeds_dicts = [dict(s) for s in seeds]
            recs = await get_recommendations(conn, user_id, seeds_dicts)
            print(f"Got {len(recs)} recommendations")
            for r in recs[:3]:
                print(r)
                
        except Exception as e:
            print(f"Error in recs: {e}")
            import traceback
            traceback.print_exc()

        if recs:
            top_artist_mbids = [f"'{r['mbid']}'" for r in recs[:20]]
            mbids_in = ",".join(top_artist_mbids)
            
            print(f"\n--- Testing Album Query with artists: {mbids_in} ---")
            try:
                # Corrected query (No popularity)
                query = f"""
                    WITH ranked_albums AS (
                        SELECT
                            a.mbid,
                            a.title,
                            aa.artist_mbid,
                            ar.name as artist_name,
                            art.sha1 as art_sha1,
                            a.release_date,
                            (COUNT(t.id) * 10) as album_score
                        FROM album a
                        JOIN artist_album aa ON a.mbid = aa.album_mbid AND aa.type = 'primary'
                        JOIN artist ar ON aa.artist_mbid = ar.mbid
                        JOIN track t ON t.release_mbid = a.mbid
                        LEFT JOIN artwork art ON a.artwork_id = art.id
                        WHERE aa.artist_mbid IN ({mbids_in})
                        AND NOT EXISTS (
                            SELECT 1
                            FROM combined_playback_history_mat cph
                            JOIN track tr ON cph.track_id = tr.id
                            WHERE tr.release_mbid = a.mbid
                              AND cph.user_id = {user_id}
                              AND cph.played_at > NOW() - INTERVAL '60 days'
                        )
                        GROUP BY a.mbid, a.title, aa.artist_mbid, ar.name, art.sha1, a.release_date
                    )
                    SELECT *, EXTRACT(YEAR FROM release_date)::text as year
                    FROM ranked_albums
                    ORDER BY album_score DESC
                    LIMIT 10
                """
                
                rows = await conn.fetch(query)
                print(f"Got {len(rows)} albums")
            except Exception as e:
                print(f"Error in albums: {e}")
                import traceback
                traceback.print_exc()

            print(f"\n--- Testing Track Query with artists: {mbids_in} ---")
            try:
                # Corrected query (explicit columns, no popularity, no bytea)
                query = f"""
                    WITH candidate_tracks AS (
                        SELECT 
                            t.id, t.title, t.duration_seconds, t.codec, t.bit_depth, t.sample_rate_hz, t.bitrate,
                            ar.name as artist_name, ar.mbid as artist_mbid,
                            al.title as album_name,
                            al.mbid as album_mbid,
                            al.mbid as mb_release_id,
                            al.release_date,
                            art.sha1 as art_sha1,
                            (RANDOM() * 20) as rec_score
                        FROM track t
                        JOIN artist ar ON t.artist_mbid = ar.mbid
                        LEFT JOIN album al ON t.release_mbid = al.mbid
                        LEFT JOIN artwork art ON t.artwork_id = art.id
                        WHERE t.artist_mbid IN ({mbids_in})
                        AND NOT EXISTS (
                            SELECT 1
                            FROM combined_playback_history_mat cph
                            WHERE cph.track_id = t.id
                              AND cph.user_id = {user_id}
                              AND cph.played_at > NOW() - INTERVAL '30 days'
                        )
                    )
                    SELECT *, EXTRACT(YEAR FROM release_date)::text as year
                    FROM candidate_tracks
                    ORDER BY rec_score DESC
                    LIMIT 50
                """
                
                rows = await conn.fetch(query)
                print(f"Got {len(rows)} tracks")
                
                if rows:
                    first_row = rows[0]
                    # Verify keys
                    print("First row keys:", list(first_row.keys()))
                    
                    # Serialize using Pydantic Logic
                    # Already imported at top level
                    
                    results = []
                    for r in rows:
                        results.append(RecommendedTrack(
                            id=r['id'],
                            title=r['title'],
                            artist=TrackArtist(
                                name=r['artist_name'],
                                mbid=r['artist_mbid']
                            ),
                            album=TrackAlbum(
                                name=r['album_name'] or "Unknown Album",
                                mbid=r['album_mbid'],
                                mb_release_id=r['mb_release_id'],
                                year=r['year']
                            ),
                            artwork=TrackArtwork(
                                sha1=r['art_sha1']
                            ),
                            duration_seconds=r['duration_seconds'],
                            codec=r['codec'],
                            bit_depth=r['bit_depth'],
                            sample_rate_hz=r['sample_rate_hz'],
                            bitrate=r['bitrate'],
                            rec_score=r['rec_score']
                        ))
                    
                    print(f"Successfully mapped {len(results)} tracks to Pydantic models.")
                    print("Sample:", results[0].model_dump())
                    
            except Exception as e:
                print(f"Error in tracks: {e}")
                import traceback
                traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
