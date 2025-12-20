from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from app.db import get_db
import aiosqlite

router = APIRouter()

class SearchResultArtist(BaseModel):
    name: str
    mbid: str
    image_url: Optional[str] = None

class SearchResultAlbum(BaseModel):
    title: str
    artist: str
    art_id: Optional[int] = None
    art_sha1: Optional[str] = None
    
class SearchResultTrack(BaseModel):
    id: int
    title: str
    artist: str
    album: str
    duration_seconds: float
    art_id: Optional[int] = None
    art_sha1: Optional[str] = None

class SearchResponse(BaseModel):
    artists: List[SearchResultArtist]
    albums: List[SearchResultAlbum]
    tracks: List[SearchResultTrack]

@router.get("/api/search", response_model=SearchResponse)
async def search(q: str, db: aiosqlite.Connection = Depends(get_db)):
    if not q or len(q) < 2:
        return SearchResponse(artists=[], albums=[], tracks=[])

    # 1. Search Artists
    # Use index on name for prefix search
    artists_query = """
        SELECT name, mbid, image_url 
        FROM artists 
        WHERE name LIKE ? 
        ORDER BY LENGTH(name) ASC, name ASC 
        LIMIT 5
    """
    artists = []
    async with db.execute(artists_query, (f"{q}%",)) as cursor:
        async for row in cursor:
            artists.append(SearchResultArtist(
                name=row['name'],
                mbid=row['mbid'],
                image_url=row['image_url']
            ))

    # If few artists found with prefix, try FTS via tracks (optional, maybe later for robustness)
    
    # 2. Search Albums
    # Use FTS on tracks for album matches, strictly matching album name
    # We group by album/artist and pick the max art_id (usually they are all same/similar for an album)
    # Also fetch the matching SHA1 for that art_id
    albums_query = """
        SELECT t.album, t.artist, MAX(t.art_id) as art_id, a.sha1 as art_sha1
        FROM tracks t
        LEFT JOIN artwork a ON t.art_id = a.id
        WHERE t.rowid IN (
            SELECT rowid FROM tracks_fts WHERE tracks_fts MATCH ?
        )
        GROUP BY t.album, t.artist
        LIMIT 5
    """
    albums = []
    # FTS query for album column only
    fts_album_query = f"album:{q}*"
    async with db.execute(albums_query, (fts_album_query,)) as cursor:
        async for row in cursor:
            albums.append(SearchResultAlbum(
                title=row['album'],
                artist=row['artist'],
                art_id=row['art_id'],
                art_sha1=row['art_sha1']
            ))

    # 3. Search Tracks
    # Use FTS for title match only, ignore album/artist matches
    tracks_query = """
        SELECT t.id, t.title, t.artist, t.album, t.duration_seconds, t.art_id, a.sha1 as art_sha1
        FROM tracks t
        JOIN tracks_fts f ON f.rowid = t.id
        LEFT JOIN artwork a ON t.art_id = a.id
        WHERE f.tracks_fts MATCH ?
        ORDER BY f.rank
        LIMIT 20
    """
    tracks = []
    # FTS query for title column only
    fts_track_query = f"title:{q}*"
    async with db.execute(tracks_query, (fts_track_query,)) as cursor:
        async for row in cursor:
            tracks.append(SearchResultTrack(
                id=row['id'],
                title=row['title'],
                artist=row['artist'],
                album=row['album'],
                duration_seconds=row['duration_seconds'] or 0.0,
                art_id=row['art_id'],
                art_sha1=row['art_sha1']
            ))

    return SearchResponse(
        artists=artists,
        albums=albums,
        tracks=tracks
    )
