from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from app.charts import refresh_chart_task
from app.db import get_pool
from app.api.deps import get_current_user_jwt

router = APIRouter(
    prefix="/charts",
    tags=["charts"],
    dependencies=[Depends(get_current_user_jwt)],
)

class ChartAlbum(BaseModel):
    position: int
    title: str
    artist: str
    last_week: Optional[str] = None
    peak: Optional[str] = None
    weeks: Optional[str] = None
    status: str
    release_mbid: Optional[str] = None
    release_group_mbid: Optional[str] = None
    
    # Enriched library state
    in_library: bool = False
    local_album_mbid: Optional[str] = None
    local_title: Optional[str] = None
    local_artist: Optional[str] = None
    artist_mbid: Optional[str] = None
    art_sha1: Optional[str] = None
    musicbrainz_url: Optional[str] = None

@router.get("", response_model=List[ChartAlbum])
async def get_chart():
    from app.config import get_musicbrainz_root_url
    mb_root = get_musicbrainz_root_url()
    
    pool = get_pool()
    async with pool.acquire() as conn:
        # Join chart_album with album to detect library presence
        # Primarily match on release_group_mbid
        query = """
            SELECT 
                c.position,
                c.title,
                c.artist,
                c.last_week,
                c.peak,
                c.weeks,
                c.status,
                c.release_mbid,
                c.release_group_mbid,
                (a.mbid IS NOT NULL) as in_library,
                a.mbid as local_album_mbid,
                a.title as local_title,
                a.artist_name as local_artist,
                a.artist_mbid as artist_mbid,
                art.sha1 as art_sha1
            FROM chart_album c
            LEFT JOIN LATERAL (
                SELECT a.*, ar.name as artist_name, aa.artist_mbid as artist_mbid
                FROM album a
                LEFT JOIN artist_album aa ON a.mbid = aa.album_mbid
                LEFT JOIN artist ar ON aa.artist_mbid = ar.mbid
                WHERE aa.type = 'primary'
                AND c.release_group_mbid IS NOT NULL
                AND c.release_group_mbid <> ''
                AND a.release_group_mbid = c.release_group_mbid
                ORDER BY a.release_date ASC NULLS LAST, a.mbid ASC
                LIMIT 1
            ) a ON TRUE
            LEFT JOIN artwork art ON a.artwork_id = art.id
            ORDER BY c.position ASC
        """
        rows = await conn.fetch(query)
        results = []
        for row in rows:
            data = dict(row)
            if data["release_group_mbid"]:
                data["musicbrainz_url"] = f"{mb_root}/release-group/{data['release_group_mbid']}"
            elif data["release_mbid"]:
                 data["musicbrainz_url"] = f"{mb_root}/release/{data['release_mbid']}"
            results.append(data)
        return results

@router.post("/refresh")
async def refresh_chart(background_tasks: BackgroundTasks):
    background_tasks.add_task(refresh_chart_task)
    return {"status": "refreshing_started"}
