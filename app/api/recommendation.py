from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.db import get_pool
from app.auth import require_current_user


router = APIRouter(prefix="/recommendations", tags=["recommendations"])

class SeedArtist(BaseModel):
    mbid: str
    name: str
    score: float
    play_count: int
    last_played_at: datetime
    image_url: Optional[str] = None
    art_sha1: Optional[str] = None

class RecommendedArtist(BaseModel):
    mbid: str
    name: str
    score: float
    support_count: int
    image_url: Optional[str] = None
    art_sha1: Optional[str] = None
    similar_to: List[str] = []

class RecommendedAlbum(BaseModel):
    mbid: str  # Release ID
    title: str
    artist: str
    artist_mbid: str
    score: float
    art_sha1: Optional[str] = None
    year: Optional[str] = None

class FeedbackStats(BaseModel):
    seed_count: int
    candidate_count: int
    final_count: int

class TrackArtist(BaseModel):
    name: str
    mbid: Optional[str] = None

class TrackAlbum(BaseModel):
    name: str
    mbid: Optional[str] = None
    mb_release_id: Optional[str] = None
    year: Optional[str] = None

class TrackArtwork(BaseModel):
    sha1: Optional[str] = None

class RecommendedTrack(BaseModel):
    id: int
    title: str
    artist: TrackArtist
    album: TrackAlbum
    artwork: TrackArtwork
    duration_seconds: Optional[float] = None
    codec: Optional[str] = None
    bit_depth: Optional[int] = None
    sample_rate_hz: Optional[int] = None
    bitrate: Optional[int] = None
    rec_score: Optional[float] = None

# --- Core Logic ---

async def get_seeds(conn, user_id: int, days: int) -> List[dict]:
    """
    Get seed artists from user's history in the last `days`.
    Score = sum( exp(-days_ago / 7) ) * log(play_count + 1)
    """
    if days <= 0:
        # All time
        since_clause = "1=1"
        params = [user_id]
        recency_expr = "EXTRACT(EPOCH FROM (NOW() - played_at)) / 86400.0"
    else:
        # Use calendar days to match History page behavior
        # History uses: today - timedelta(days=6) for 7 days
        # So we want: played_at >= (CURRENT_DATE - (days - 1))
        since_clause = "played_at >= (CURRENT_DATE - make_interval(days => $2 - 1))"
        params = [user_id, days]
        recency_expr = "EXTRACT(EPOCH FROM (NOW() - played_at)) / 86400.0"

    query = f"""
        WITH recent_plays AS (
            SELECT 
                a.mbid as artist_mbid,
                a.name as artist_name,
                cph.source_id, -- Needed for distinct count
                cph.played_at,
                EXP(-LEAST(({recency_expr}) / 7.0, 100)) as weight
            FROM combined_playback_history_mat cph
            JOIN track t ON cph.track_id = t.id
            JOIN track_artist ta ON ta.track_id = t.id
            JOIN artist a ON ta.artist_mbid = a.mbid
            WHERE cph.user_id = $1
              AND cph.played_at <= NOW()
              AND {since_clause}
        ),
        scored_artists AS (
            SELECT
                artist_mbid,
                MAX(artist_name) as name,
                -- Score combines recency weight with play volume
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
        ORDER BY sa.play_count DESC, sa.score DESC
        LIMIT 50
    """
    return await conn.fetch(query, *params)

async def get_recommendations(conn, user_id: int, seeds: List[dict], days: int) -> List[dict]:
    """
    Generate artist recommendations based on seeds.
    """
    if not seeds:
        return []

    # 1. Expand seeds to candidates
    seed_values = []
    for s in seeds:
        # (mbid, score)
        seed_values.append(f"('{s['artist_mbid']}', {s['score']})")
    
    values_clause = ",".join(seed_values)
    
    # Build the time filter clause based on days parameter
    # The exclusion period should match the seed period
    if days <= 0:
        # All time - exclude ALL artists we've ever played
        time_filter = ""  # No time constraint - exclude everything we've played
    else:
        # Use the same time window as seeds
        time_filter = f"AND cph.played_at >= (CURRENT_DATE - make_interval(days => {days} - 1))"
    
    query = f"""
        WITH seeds(mbid, score) AS (
            VALUES {values_clause}
        ),
        candidates AS (
            SELECT
                sa.similar_artist_mbid as mbid,
                sa.similar_artist_name as name,
                SUM(s.score) as base_score,
                COUNT(DISTINCT s.mbid) as support_count,
                array_agg(DISTINCT a_seed.name) as similar_to_names
            FROM seeds s
            JOIN similar_artist sa ON s.mbid = sa.artist_mbid
            JOIN artist a_seed ON s.mbid = a_seed.mbid
            WHERE sa.similar_artist_mbid IS NOT NULL
            GROUP BY sa.similar_artist_mbid, sa.similar_artist_name
        ),
        boosted AS (
            SELECT
                c.*,
                -- Boost score if we have local content (tracks) for this artist
                -- Check existence of tracks for this artist in our library
                CASE 
                    WHEN EXISTS (SELECT 1 FROM track t WHERE t.artist_mbid = c.mbid) THEN
                        (c.base_score * (1 + LN(1 + c.support_count))) * 1.5 -- 50% boost
                    ELSE
                        (c.base_score * (1 + LN(1 + c.support_count)))
                END as final_score
            FROM candidates c
        ),
        filtered AS (
            SELECT b.*, a.image_url, art.sha1 as art_sha1
            FROM boosted b
            JOIN artist a ON b.mbid = a.mbid
            LEFT JOIN artwork art ON a.artwork_id = art.id
            WHERE 
            -- STRICT FILTER: Only show artists that have a primary album in our library
            EXISTS (
                SELECT 1 
                FROM artist_album aa
                WHERE aa.artist_mbid = b.mbid 
                  AND aa.type = 'primary'
            )
            AND NOT EXISTS (
                -- Exclude artists played in the same time window as seeds
                SELECT 1 
                FROM combined_playback_history_mat cph
                JOIN track t ON cph.track_id = t.id
                WHERE t.artist_mbid = b.mbid
                  AND cph.user_id = {user_id}
                  {time_filter}
            )
            AND b.mbid NOT IN (SELECT mbid FROM seeds)
        )
        SELECT * FROM filtered
        ORDER BY final_score DESC
        LIMIT 50
    """
    return await conn.fetch(query)

# --- Endpoints ---

@router.get("/seeds", response_model=List[SeedArtist])
async def get_model_seeds(
    days: int = Query(30, description="Number of days to look back (0 for all time)"),
    user_data: tuple = Depends(require_current_user)
):
    user = user_data[0]
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await get_seeds(conn, user['id'], days)
        return [
            {
                "mbid": r["artist_mbid"],
                "name": r["name"],
                "score": r["score"],
                "play_count": r["play_count"],
                "last_played_at": r["last_played_at"],
                "image_url": r["image_url"],
                "art_sha1": r["art_sha1"]
            }
            for r in rows
        ]

@router.get("/artists", response_model=List[RecommendedArtist])
async def get_recommended_artists(
    days: int = Query(30, description="Number of days to look back"),
    user_data: tuple = Depends(require_current_user)
):
    user = user_data[0]
    pool = get_pool()
    async with pool.acquire() as conn:
        seeds = await get_seeds(conn, user['id'], days)
        recs = await get_recommendations(conn, user['id'], seeds, days)
        
        # Limit to 10 as requested
        return [
            {
                "mbid": r["mbid"],
                "name": r["name"],
                "score": r["final_score"],
                "support_count": r["support_count"],
                "image_url": r["image_url"],
                "art_sha1": r["art_sha1"],
                "similar_to": r["similar_to_names"][:3] # Show top 3 reasons
            }
            for r in recs[:10]
        ]

@router.get("/albums", response_model=List[RecommendedAlbum])
async def get_recommended_albums(
    days: int = Query(30, description="Number of days to look back"),
    user_data: tuple = Depends(require_current_user)
):
    """
    Returns recommended albums from the top recommended artists.
    Picks the 'most popular' albums based on track play counts or scrobbles.
    LIMIT: 1 Album per Artist.
    ORDER: Same as Artist Rank.
    """
    user = user_data[0]
    pool = get_pool()
    async with pool.acquire() as conn:
        seeds = await get_seeds(conn, user['id'], days)
        artist_recs = await get_recommendations(conn, user['id'], seeds, days)
        
        if not artist_recs:
            return []

        # Get top 10 artists with their implicit rank
        top_artists = artist_recs[:10]
        if not top_artists:
            return []

        # Create VALUES clause like: ('mbid1', 1), ('mbid2', 2)...
        values_list = []
        for i, r in enumerate(top_artists):
            values_list.append(f"('{r['mbid']}', {i+1})")
        
        values_clause = ",".join(values_list)
        
        # Build album time filter to match seed period
        if days <= 0:
            # All time - exclude all albums we've ever played
            album_time_filter = ""
        else:
            # Use the same time window as seeds
            album_time_filter = f"AND cph.played_at >= (CURRENT_DATE - make_interval(days => {days} - 1))"
        
        query = f"""
            WITH target_artists(mbid, rank) AS (
                VALUES {values_clause}
            ),
            track_scores AS (
                SELECT 
                    t.release_mbid,
                    SUM(CASE WHEN tt.type = 'top' THEN tt.popularity ELSE 0 END) as top_track_score,
                    COUNT(CASE WHEN tt.type = 'single' THEN 1 END) as single_count
                FROM track t
                JOIN top_track tt ON t.id = tt.track_id
                WHERE tt.type IN ('top', 'single')
                  AND t.release_mbid IS NOT NULL
                GROUP BY t.release_mbid
            ),
            ranked_albums AS (
                SELECT
                    a.mbid,
                    a.title,
                    aa.artist_mbid,
                    ar.name as artist_name,
                    art.sha1 as art_sha1,
                    a.release_date,
                    ta.rank,
                    COALESCE(ts.top_track_score, 0) as top_track_score,
                    COALESCE(ts.single_count, 0) as single_count,
                    COALESCE(a.release_date, '1900-01-01'::date) as release_date_sort
                FROM album a
                JOIN artist_album aa ON a.mbid = aa.album_mbid AND aa.type = 'primary'
                JOIN artist ar ON aa.artist_mbid = ar.mbid
                JOIN target_artists ta ON aa.artist_mbid = ta.mbid
                LEFT JOIN artwork art ON a.artwork_id = art.id
                LEFT JOIN track_scores ts ON a.mbid = ts.release_mbid
                WHERE NOT EXISTS (
                    -- Exclude albums played in the same time window as seeds
                    SELECT 1
                    FROM combined_playback_history_mat cph
                    JOIN track tr ON cph.track_id = tr.id
                    WHERE tr.release_mbid = a.mbid
                      AND cph.user_id = {user['id']}
                      {album_time_filter}
                )
                GROUP BY a.mbid, a.title, aa.artist_mbid, ar.name, art.sha1, a.release_date, ta.rank, ts.top_track_score, ts.single_count
            ),
            limited_albums AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY artist_mbid 
                        ORDER BY 
                            top_track_score DESC,  -- Prioritize albums with popular top tracks
                            single_count DESC,      -- Then albums with more singles
                            release_date_sort DESC  -- Then most recent
                    ) as rn
                FROM ranked_albums
            )
            SELECT *, EXTRACT(YEAR FROM release_date)::text as year
            FROM limited_albums
            WHERE rn = 1
            ORDER BY rank ASC
            LIMIT 10
        """
        
        rows = await conn.fetch(query)
        return [
            {
                "mbid": r["mbid"],
                "title": r["title"],
                "artist": r["artist_name"],
                "artist_mbid": r["artist_mbid"],
                "score": float(r["top_track_score"]),
                "art_sha1": r["art_sha1"],
                "year": r["year"]
            }
            for r in rows
        ]

@router.get("/tracks", response_model=List[RecommendedTrack])
async def get_recommended_tracks(
    days: int = Query(30, description="Number of days to look back"),
    user_data: tuple = Depends(require_current_user)
):
    """
    Returns recommended tracks from the top recommended artists.
    LIMIT: 3 Tracks per Artist.
    """
    user = user_data[0]
    pool = get_pool()
    async with pool.acquire() as conn:
        seeds = await get_seeds(conn, user['id'], days)
        artist_recs = await get_recommendations(conn, user['id'], seeds, days)
        
        if not artist_recs:
            return []

        # Get top 10 artists to find tracks for (Strict 1:1 Coherence)
        top_artist_mbids = [f"'{r['mbid']}'" for r in artist_recs[:10]]
        if not top_artist_mbids:
            return []
        
        mbids_in = ",".join(top_artist_mbids)

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
                    -- Add some randomness so we don't always get the same top tracks
                FROM track t
                JOIN artist ar ON t.artist_mbid = ar.mbid
                LEFT JOIN album al ON t.release_mbid = al.mbid
                LEFT JOIN artwork art ON t.artwork_id = art.id
                WHERE t.artist_mbid IN ({mbids_in})
                AND NOT EXISTS (
                    -- Exclude tracks played in last 30 days
                    SELECT 1
                    FROM combined_playback_history_mat cph
                    WHERE cph.track_id = t.id
                      AND cph.user_id = {user['id']}
                      AND cph.played_at > NOW() - INTERVAL '30 days'
                )
            ),
            limited_tracks AS (
                SELECT *,
                    ROW_NUMBER() OVER (PARTITION BY artist_mbid ORDER BY rec_score DESC) as rn
                FROM candidate_tracks
            )
            SELECT *, EXTRACT(YEAR FROM release_date)::text as year
            FROM limited_tracks
            WHERE rn <= 3
            ORDER BY rec_score DESC
            LIMIT 50
        """
        
        rows = await conn.fetch(query)
        
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
            
        return results
