from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from app.db import get_db
import asyncpg

router = APIRouter()

class SearchResultArtist(BaseModel):
    name: str
    mbid: str
    image_url: Optional[str] = None
    artwork_id: Optional[int] = None
    art_id: Optional[int] = None
    art_sha1: Optional[str] = None

class SearchResultAlbum(BaseModel):
    title: str
    artist: str
    artwork_id: Optional[int] = None
    art_id: Optional[int] = None
    art_sha1: Optional[str] = None
    
class SearchResultTrack(BaseModel):
    id: int
    title: str
    artist: str
    album: str
    duration_seconds: float
    artwork_id: Optional[int] = None
    art_id: Optional[int] = None
    art_sha1: Optional[str] = None

class SearchResponse(BaseModel):
    artists: List[SearchResultArtist]
    albums: List[SearchResultAlbum]
    tracks: List[SearchResultTrack]

@router.get("/api/search", response_model=SearchResponse)
async def search(q: str, db: asyncpg.Connection = Depends(get_db)):
    if not q or len(q) < 2:
        return SearchResponse(artists=[], albums=[], tracks=[])

    # 1. Search Artists (case-insensitive via citext)
    artists_query = """
        SELECT a.name, a.mbid, a.image_url, a.artwork_id, ar.sha1 as art_sha1
        FROM artist a
        LEFT JOIN artwork ar ON a.artwork_id = ar.id
        WHERE a.name ILIKE $1
        ORDER BY LENGTH(a.name) ASC, a.name ASC 
        LIMIT 5
    """
    artists = []
    rows = await db.fetch(artists_query, f"%{q}%")
    for row in rows:
        artists.append(SearchResultArtist(
            name=row['name'],
            mbid=row['mbid'],
            image_url=row['image_url'],
            artwork_id=row['artwork_id'],
            art_id=row['artwork_id'],
            art_sha1=row['art_sha1']
        ))

    # 2. Search Albums using FTS
    albums_query = """
        SELECT t.album, t.artist, MAX(t.artwork_id) as artwork_id, MAX(a.sha1) as art_sha1
        FROM track t
        LEFT JOIN artwork a ON t.artwork_id = a.id
        WHERE t.fts_vector @@ plainto_tsquery('english', $1)
          AND t.album IS NOT NULL
        GROUP BY t.album, t.artist
        ORDER BY MAX(ts_rank(t.fts_vector, plainto_tsquery('english', $1))) DESC
        LIMIT 5
    """
    albums = []
    rows = await db.fetch(albums_query, q)
    for row in rows:
        albums.append(SearchResultAlbum(
            title=row['album'],
            artist=row['artist'],
            artwork_id=row['artwork_id'],
            art_id=row['artwork_id'],
            art_sha1=row['art_sha1']
        ))

    # 3. Search Tracks using FTS
    tracks_query = """
        SELECT t.id, t.title, t.artist, t.album, t.duration_seconds, t.artwork_id, a.sha1 as art_sha1
        FROM track t
        LEFT JOIN artwork a ON t.artwork_id = a.id
        WHERE t.fts_vector @@ plainto_tsquery('english', $1)
        ORDER BY ts_rank(t.fts_vector, plainto_tsquery('english', $1)) DESC
        LIMIT 20
    """
    tracks = []
    rows = await db.fetch(tracks_query, q)
    for row in rows:
        tracks.append(SearchResultTrack(
            id=row['id'],
            title=row['title'],
            artist=row['artist'],
            album=row['album'],
            duration_seconds=row['duration_seconds'] or 0.0,
            artwork_id=row['artwork_id'],
            art_id=row['artwork_id'],
            art_sha1=row['art_sha1']
        ))

    return SearchResponse(
        artists=artists,
        albums=albums,
        tracks=tracks
    )
