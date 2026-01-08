from fastapi import APIRouter, Depends
from typing import List, Optional
from pydantic import BaseModel
from app.db import get_db
import asyncpg

router = APIRouter()


class SearchResultArtist(BaseModel):
    name: str
    mbid: str
    image_url: Optional[str] = None
    art_sha1: Optional[str] = None


class SearchResultAlbum(BaseModel):
    title: str
    artist: str
    mbid: Optional[str] = None
    art_sha1: Optional[str] = None


class SearchResultTrack(BaseModel):
    id: int
    title: str
    artist: str
    album: str
    mb_release_id: Optional[str] = None
    duration_seconds: float
    art_sha1: Optional[str] = None


class SearchResponse(BaseModel):
    artists: List[SearchResultArtist]
    albums: List[SearchResultAlbum]
    tracks: List[SearchResultTrack]


@router.get("/api/search", response_model=SearchResponse)
async def search(q: str, db: asyncpg.Connection = Depends(get_db)):
    if not q or len(q) < 2:
        return SearchResponse(artists=[], albums=[], tracks=[])

    limit = 20

    # 1. Search Artists (case-insensitive via citext)
    artists_query = """
        SELECT a.name, a.mbid, a.image_url, a.artwork_id, ar.sha1 as art_sha1
        FROM artist a
        LEFT JOIN artwork ar ON a.artwork_id = ar.id
        WHERE a.name ILIKE $1
        ORDER BY LENGTH(a.name) ASC, a.name ASC 
        LIMIT $2
    """
    artists = []
    rows = await db.fetch(artists_query, f"%{q}%", limit)
    for row in rows:
        artists.append(
            SearchResultArtist(
                name=row["name"],
                mbid=row["mbid"],
                image_url=row["image_url"],
                art_sha1=row["art_sha1"],
            )
        )

    # 2. Search Albums from `album` table (using title FTS)
    # We join artist_album to get a "primary" artist. 
    # Prioritize correct album title matches first.
    albums_query = """
        SELECT 
            al.title, 
            al.mbid, 
            al.artwork_id, 
            ar.sha1 as art_sha1,
            -- Get the first artist (prioritizing primary)
            (
                SELECT art.name 
                FROM artist_album aa
                JOIN artist art ON aa.artist_mbid = art.mbid
                WHERE aa.album_mbid = al.mbid
                ORDER BY (CASE WHEN aa.type = 'primary' THEN 1 ELSE 2 END), art.name
                LIMIT 1
            ) as artist
        FROM album al
        LEFT JOIN artwork ar ON al.artwork_id = ar.id
        WHERE to_tsvector('english', al.title) @@ plainto_tsquery('english', $1)
        ORDER BY 
            -- Primary Sort: Does it match using 'simple' dictionary (stopwords included)?
            (to_tsvector('simple', al.title) @@ plainto_tsquery('simple', $1)) DESC,
            -- Secondary Sort: FTS Rank
            ts_rank(to_tsvector('english', al.title), plainto_tsquery('english', $1)) DESC, 
            al.title
        LIMIT $2
    """
    albums = []
    rows = await db.fetch(albums_query, q, limit)
    for row in rows:
        albums.append(
            SearchResultAlbum(
                title=row["title"],
                artist=row["artist"] or "Unknown Artist",
                mbid=row["mbid"],
                art_sha1=row["art_sha1"],
            )
        )

    # 3. Search Tracks using FTS (existing logic but new limit)
    tracks_query = """
        SELECT 
            t.id, 
            t.title, 
            t.artist, 
            t.album, 
            t.release_mbid as mb_release_id,
            t.duration_seconds, 
            t.artwork_id, 
            a.sha1 as art_sha1
        FROM track t
        LEFT JOIN artwork a ON t.artwork_id = a.id
        WHERE t.fts_vector @@ plainto_tsquery('english', $1)
        ORDER BY ts_rank(t.fts_vector, plainto_tsquery('english', $1)) DESC
        LIMIT $2
    """
    tracks = []
    rows = await db.fetch(tracks_query, q, limit)
    for row in rows:
        tracks.append(
            SearchResultTrack(
                id=row["id"],
                title=row["title"],
                artist=row["artist"],
                album=row["album"],
                mb_release_id=row["mb_release_id"],
                duration_seconds=row["duration_seconds"] or 0.0,
                art_sha1=row["art_sha1"],
            )
        )

    return SearchResponse(artists=artists, albums=albums, tracks=tracks)
