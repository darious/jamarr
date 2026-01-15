from fastapi import APIRouter, Depends, HTTPException
from app.db import get_db
import asyncpg
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from app.api.deps import get_current_user_jwt, get_optional_user_jwt

router = APIRouter()

# --- Models ---

class PlaylistCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_public: bool = False
    track_ids: Optional[List[int]] = None

class PlaylistUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_public: Optional[bool] = None

class PlaylistTrackAdd(BaseModel):
    track_ids: List[int]

class PlaylistTrackRemove(BaseModel):
    # We remove by playlist_track ID to handle duplicates precisely, 
    # but initially the UI might just pass position or track_id.
    # Let's support removing specific instance ID if known, or track_id (removes first/all?)
    # Valid spec: "Remove track". Ideally defined by position or instance ID.
    playlist_track_id: int

class PlaylistReorder(BaseModel):
    # New order of playlist_track_ids
    allowed_playlist_track_ids: List[int]

class Playlist(BaseModel):
    id: int
    user_id: int
    name: str
    description: Optional[str]
    is_public: bool
    updated_at: datetime
    track_count: int = 0
    total_duration: float = 0.0
    # Artwork will be handled by a separate endpoint or field in list

class PlaylistTrack(BaseModel):
    id: int # playlist_track_id
    playlist_id: int
    track_id: int
    position: int
    title: Optional[str]
    artist: Optional[str]
    album: Optional[str]
    duration_seconds: Optional[float]
    art_sha1: Optional[str]
    artist_mbid: Optional[str]
    album_mbid: Optional[str]
    # Add other track fields as needed for display

# --- API ---

@router.post("/api/playlists", response_model=Playlist)
async def create_playlist(
    playlist: PlaylistCreate, 
    db: asyncpg.Connection = Depends(get_db),
    user: asyncpg.Record = Depends(get_current_user_jwt),
):
    user_id = user['id']
    
    # Validate track IDs if provided
    if playlist.track_ids:
        # Check that all track IDs exist
        track_check_query = """
            SELECT id FROM track WHERE id = ANY($1::int[])
        """
        existing_tracks = await db.fetch(track_check_query, playlist.track_ids)
        existing_ids = {row['id'] for row in existing_tracks}
        
        missing_ids = set(playlist.track_ids) - existing_ids
        if missing_ids:
            raise HTTPException(
                status_code=400, 
                detail=f"Track IDs not found: {sorted(missing_ids)}"
            )
    
    # Create playlist
    query = """
        INSERT INTO playlist (user_id, name, description, is_public, updated_at)
        VALUES ($1, $2, $3, $4, NOW())
        RETURNING id, user_id, name, description, is_public, updated_at
    """
    row = await db.fetchrow(
        query, 
        user_id, 
        playlist.name, 
        playlist.description,
        playlist.is_public
    )
    
    # Add tracks if provided
    if playlist.track_ids:
        values = []
        for position, track_id in enumerate(playlist.track_ids):
            values.append((row['id'], track_id, position))
        
        if values:
            await db.executemany("""
                INSERT INTO playlist_track (playlist_id, track_id, position)
                VALUES ($1, $2, $3)
            """, values)
    
    return dict(row)

@router.get("/api/playlists", response_model=List[dict])
async def list_playlists(
    user_id: Optional[int] = None, 
    db: asyncpg.Connection = Depends(get_db),
    current_user: Optional[asyncpg.Record] = Depends(get_optional_user_jwt),
):
    # If user_id not provided, list current user's playlists
    target_user_id = user_id
    if target_user_id is None:
        if not current_user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        target_user_id = current_user['id']
    # Fetch all user's playlists + public playlists from others (future proofing)
    # For now, just user's playlists as per spec "user-scoped" but with public flag structure ready
    query = """
        SELECT 
            p.id, p.user_id, p.name, p.description, p.is_public, p.updated_at,
            COUNT(pt.id) as track_count,
            COALESCE(SUM(t.duration_seconds), 0) as total_duration,
            (
                SELECT array_agg(t2.artwork_id)
                FROM (
                    SELECT DISTINCT t.artwork_id 
                    FROM playlist_track pt2
                    JOIN track t ON pt2.track_id = t.id
                    WHERE pt2.playlist_id = p.id AND t.artwork_id IS NOT NULL
                    LIMIT 4
                ) t2
            ) as artwork_ids,
            (
                SELECT array_agg(t2.sha1)
                FROM (
                    SELECT DISTINCT a.sha1 
                    FROM playlist_track pt2
                    JOIN track t ON pt2.track_id = t.id
                    JOIN artwork a ON t.artwork_id = a.id
                    WHERE pt2.playlist_id = p.id
                    LIMIT 4
                ) t2
            ) as artwork_sha1s
        FROM playlist p
        LEFT JOIN playlist_track pt ON p.id = pt.playlist_id
        LEFT JOIN track t ON pt.track_id = t.id
        WHERE p.user_id = $1
        GROUP BY p.id
        ORDER BY p.updated_at DESC
    """
    rows = await db.fetch(query, target_user_id)
    
    results = []
    from app.api.library import sha1_to_hex
    
    for row in rows:
        d = dict(row)
        # Process artwork for 2x2 grid
        # We return simply the implementation logic here
        shas = d.pop('artwork_sha1s', [])
        d.pop("artwork_ids", None)
        if shas:
            d['thumbnails'] = [sha1_to_hex(s) for s in shas if s]
        else:
            d['thumbnails'] = []
        results.append(d)
        
    return results


@router.get("/api/artists/{artist_mbid}/playlists", response_model=List[dict])
async def list_playlists_for_artist(
    artist_mbid: str,
    db: asyncpg.Connection = Depends(get_db),
    current_user: Optional[asyncpg.Record] = Depends(get_optional_user_jwt),
):
    params = [artist_mbid]
    visibility_clause = "p.is_public = TRUE"
    if current_user:
        params.append(current_user["id"])
        visibility_clause = "p.is_public = TRUE OR p.user_id = $2"

    query = f"""
        SELECT 
            p.id, p.user_id, p.name, p.description, p.is_public, p.updated_at,
            COUNT(pt.id) as track_count,
            COALESCE(SUM(t.duration_seconds), 0) as total_duration,
            (
                SELECT array_agg(t2.artwork_id)
                FROM (
                    SELECT DISTINCT t.artwork_id 
                    FROM playlist_track pt2
                    JOIN track t ON pt2.track_id = t.id
                    WHERE pt2.playlist_id = p.id AND t.artwork_id IS NOT NULL
                    LIMIT 4
                ) t2
            ) as artwork_ids,
            (
                SELECT array_agg(t2.sha1)
                FROM (
                    SELECT DISTINCT a.sha1 
                    FROM playlist_track pt2
                    JOIN track t ON pt2.track_id = t.id
                    JOIN artwork a ON t.artwork_id = a.id
                    WHERE pt2.playlist_id = p.id
                    LIMIT 4
                ) t2
            ) as artwork_sha1s
        FROM playlist p
        LEFT JOIN playlist_track pt ON p.id = pt.playlist_id
        LEFT JOIN track t ON pt.track_id = t.id
        WHERE ({visibility_clause})
          AND EXISTS (
              SELECT 1
              FROM playlist_track pt2
              JOIN track_artist ta2 ON ta2.track_id = pt2.track_id
              WHERE pt2.playlist_id = p.id AND ta2.artist_mbid = $1
          )
        GROUP BY p.id
        ORDER BY p.updated_at DESC
    """
    rows = await db.fetch(query, *params)

    results = []
    from app.api.library import sha1_to_hex

    for row in rows:
        d = dict(row)
        shas = d.pop("artwork_sha1s", [])
        d.pop("artwork_ids", None)
        if shas:
            d["thumbnails"] = [sha1_to_hex(s) for s in shas if s]
        else:
            d["thumbnails"] = []
        results.append(d)

    return results

@router.get("/api/playlists/{playlist_id}", response_model=dict)
async def get_playlist(
    playlist_id: int,
    db: asyncpg.Connection = Depends(get_db),
    current_user: Optional[asyncpg.Record] = Depends(get_optional_user_jwt),
):
    # Optional auth for checking visibility
    current_user_id = current_user["id"] if current_user else None
    # Get metadata
    p_query = """
        SELECT id, user_id, name, description, is_public, updated_at
        FROM playlist
        WHERE id = $1 AND (($2::int IS NOT NULL AND user_id = $2) OR is_public = TRUE)
    """
    p_row = await db.fetchrow(p_query, playlist_id, current_user_id)
    if not p_row:
        raise HTTPException(status_code=404, detail="Playlist not found")
    
    # Check visibility
    if p_row['user_id'] != current_user_id and not p_row['is_public']:
         raise HTTPException(status_code=403, detail="Access denied")

    # Get tracks
    # Get tracks
    t_query = """
        SELECT 
            pt.id as playlist_track_id, pt.position,
            t.id as track_id, t.title, t.artist, t.album, t.duration_seconds,
            a.sha1 as art_sha1, t.path,
            t.codec, t.sample_rate_hz, t.bit_depth,
            t.artist_mbid, t.release_mbid, t.release_group_mbid as album_mbid,
            COALESCE(tp.plays, 0) as plays,
            (SELECT jsonb_agg(jsonb_build_object('name', a2.name, 'mbid', a2.mbid) ORDER BY a2.name) 
             FROM track_artist ta2 
             JOIN artist a2 ON ta2.artist_mbid = a2.mbid 
             WHERE ta2.track_id = t.id) as aggregated_artists_json
        FROM playlist_track pt
        JOIN track t ON pt.track_id = t.id
        LEFT JOIN artwork a ON t.artwork_id = a.id
        LEFT JOIN (
            SELECT h.track_id, COUNT(*) as plays
            FROM combined_playback_history_mat h
            GROUP BY h.track_id
        ) tp ON tp.track_id = t.id
        WHERE pt.playlist_id = $1
        ORDER BY pt.position ASC
    """
    t_rows = await db.fetch(t_query, playlist_id)
    
    from app.api.library import sha1_to_hex
    tracks = []
    total_duration = 0
    for r in t_rows:
        d = dict(r)
        d['art_sha1'] = sha1_to_hex(d['art_sha1'])
        d.pop("art_id", None)
        if d.get("release_mbid"):
            d["mb_release_id"] = d["release_mbid"]
        
        # Parse aggregated artists JSON
        if d.get("aggregated_artists_json"):
            import json
            val = d["aggregated_artists_json"]
            if isinstance(val, str):
                try:
                    d["artists"] = json.loads(val)
                except Exception:
                    d["artists"] = []
            else:
                d["artists"] = val
        else:
             d["artists"] = [{"name": d["artist"]}] if d.get("artist") else []
        d.pop("aggregated_artists_json", None)

        tracks.append(d)
        if d['duration_seconds']:
            total_duration += d['duration_seconds']

    return {
        **dict(p_row),
        "tracks": tracks,
        "track_count": len(tracks),
        "total_duration": total_duration
    }

@router.put("/api/playlists/{playlist_id}")
async def update_playlist(
    playlist_id: int,
    updates: PlaylistUpdate,
    db: asyncpg.Connection = Depends(get_db),
    user: asyncpg.Record = Depends(get_current_user_jwt),
):
    user_id = user['id']
    # Verify owner
    check_q = "SELECT user_id FROM playlist WHERE id = $1"
    row = await db.fetchrow(check_q, playlist_id)
    if not row:
         raise HTTPException(status_code=404, detail="Playlist not found")
    if row['user_id'] != user_id:
         raise HTTPException(status_code=403, detail="Not owner")
    
    # Build update
    fields = []
    params = []
    i = 1
    if updates.name is not None:
        fields.append(f"name = ${i}")
        params.append(updates.name)
        i += 1
    if updates.description is not None:
        fields.append(f"description = ${i}")
        params.append(updates.description)
        i += 1
    if updates.is_public is not None:
        fields.append(f"is_public = ${i}")
        params.append(updates.is_public)
        i += 1
        
    if not fields:
        return {}
        
    fields.append("updated_at = NOW()")
    
    params.append(playlist_id)
    
    query = f"""
        UPDATE playlist 
        SET {', '.join(fields)}
        WHERE id = ${i}
    """
    await db.execute(query, *params)
    return {"status": "updated"}

@router.delete("/api/playlists/{playlist_id}")
async def delete_playlist(
    playlist_id: int,
    db: asyncpg.Connection = Depends(get_db),
    user: asyncpg.Record = Depends(get_current_user_jwt),
):
    user_id = user['id']
    check_q = "SELECT user_id FROM playlist WHERE id = $1"
    row = await db.fetchrow(check_q, playlist_id)
    if not row:
         raise HTTPException(status_code=404, detail="Playlist not found")
    if row['user_id'] != user_id:
         raise HTTPException(status_code=403, detail="Not owner")
         
    await db.execute("DELETE FROM playlist WHERE id = $1", playlist_id)
    return {"status": "deleted"}

@router.post("/api/playlists/{playlist_id}/tracks")
async def add_tracks(
    playlist_id: int,
    payload: PlaylistTrackAdd,
    db: asyncpg.Connection = Depends(get_db),
    user: asyncpg.Record = Depends(get_current_user_jwt),
):
    user_id = user['id']
    # Verify owner
    check_q = "SELECT user_id FROM playlist WHERE id = $1"
    p_row = await db.fetchrow(check_q, playlist_id)
    if not p_row:
         raise HTTPException(status_code=404, detail="Playlist not found")
    if p_row['user_id'] != user_id:
         raise HTTPException(status_code=403, detail="Not owner")

    # Get max position
    pos_row = await db.fetchrow("SELECT MAX(position) as max_pos FROM playlist_track WHERE playlist_id = $1", playlist_id)
    current_pos = (pos_row['max_pos'] if pos_row and pos_row['max_pos'] is not None else -1) + 1
    
    # Add tracks
    # We can do this in a loop or executemany. Executemany is better but asyncpg uses list of tuples.
    values = []
    for tid in payload.track_ids:
        values.append((playlist_id, tid, current_pos))
        current_pos += 1
        
    if values:
        await db.executemany("""
            INSERT INTO playlist_track (playlist_id, track_id, position)
            VALUES ($1, $2, $3)
        """, values)
        
    # Update timestamp
    await db.execute("UPDATE playlist SET updated_at = NOW() WHERE id = $1", playlist_id)
    
    return {"status": "added", "count": len(values)}

@router.delete("/api/playlists/{playlist_id}/tracks/{playlist_track_id}")
async def remove_track(
    playlist_id: int,
    playlist_track_id: int,
    db: asyncpg.Connection = Depends(get_db),
    user: asyncpg.Record = Depends(get_current_user_jwt),
):
    user_id = user['id']
    # Verify owner
    check_q = "SELECT user_id FROM playlist WHERE id = $1"
    row = await db.fetchrow(check_q, playlist_id)
    if not row:
         raise HTTPException(status_code=404, detail="Playlist not found")
    if row['user_id'] != user_id:
         raise HTTPException(status_code=403, detail="Not owner")
    
    # Delete and maybe shift positions? 
    # Spec says "Manual track ordering (explicit positions)".
    # If we delete one in middle, we have a gap. Reordering logic should handle gaps, 
    # but strictly we might want to shift everything down.
    # For now, let's just delete. Ordering relies on 'position' sort, gaps are fine.
    
    res = await db.execute("DELETE FROM playlist_track WHERE id = $1 AND playlist_id = $2", playlist_track_id, playlist_id)
    if res == "DELETE 0":
        raise HTTPException(status_code=404, detail="Track not found in playlist")

    await db.execute("UPDATE playlist SET updated_at = NOW() WHERE id = $1", playlist_id)
    return {"status": "removed"}

@router.post("/api/playlists/{playlist_id}/reorder")
async def reorder_tracks(
    playlist_id: int,
    payload: PlaylistReorder,
    db: asyncpg.Connection = Depends(get_db),
    user: asyncpg.Record = Depends(get_current_user_jwt),
):
    user_id = user['id']
    # Payload is list of playlist_track_ids in NEW order.
    
    # Verify owner
    check_q = "SELECT user_id FROM playlist WHERE id = $1"
    row = await db.fetchrow(check_q, playlist_id)
    if not row:
         raise HTTPException(status_code=404, detail="Playlist not found")
    if row['user_id'] != user_id:
         raise HTTPException(status_code=403, detail="Not owner")

    # Update positions
    # We use a temporary table or CASE statement.
    # Because payload might be partial (?), spec says "Atomic Reorder".
    # Assuming payload contains ALL track IDs in the playlist or just the ones being moved?
    # Simpler: payload contains the ordered list of playlist_track_ids. 
    # Any IDs not in payload are either deleted or appended? 
    # Let's assume payload IS the new full state for simplicity and robustness.
    
    # However, to be safe, we only update the positions of the IDs provided.
    
    async with db.transaction():
        for index, pt_id in enumerate(payload.allowed_playlist_track_ids):
            await db.execute("""
                UPDATE playlist_track 
                SET position = $1 
                WHERE id = $2 AND playlist_id = $3
            """, index, pt_id, playlist_id)
            
        await db.execute("UPDATE playlist SET updated_at = NOW() WHERE id = $1", playlist_id)

    return {"status": "reordered"}
