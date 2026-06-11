import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.charts import refresh_chart_task
from app.db import get_pool
from app.api.deps import get_current_admin_user_jwt, get_current_user_jwt

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
    overridden: bool = False

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
                art.sha1 as art_sha1,
                (o.release_group_mbid IS NOT NULL) as overridden
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
            LEFT JOIN chart_match_override o
                ON lower(o.artist) = lower(c.artist) AND lower(o.title) = lower(c.title)
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

@router.post("/refresh", dependencies=[Depends(get_current_admin_user_jwt)])
async def refresh_chart():
    await refresh_chart_task()
    return {"status": "refreshed"}


_MBID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.IGNORECASE
)


class ChartOverride(BaseModel):
    artist: str
    title: str
    # Bare release-group MBID or any MusicBrainz URL containing one.
    release_group_mbid: str


class ChartOverrideKey(BaseModel):
    artist: str
    title: str


@router.put("/override", dependencies=[Depends(get_current_admin_user_jwt)])
async def set_chart_override(body: ChartOverride):
    match = _MBID_RE.search(body.release_group_mbid)
    if not match:
        raise HTTPException(status_code=422, detail="No valid MBID found in release_group_mbid")
    rg_mbid = match.group(1).lower()

    artist = body.artist.strip()
    title = body.title.strip()
    if not artist or not title:
        raise HTTPException(status_code=422, detail="artist and title are required")

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO chart_match_override (artist, title, release_group_mbid)
                VALUES ($1, $2, $3)
                ON CONFLICT (lower(artist), lower(title))
                DO UPDATE SET release_group_mbid = $3, updated_at = NOW()
                """,
                artist, title, rg_mbid,
            )
            # Reflect immediately in the current chart instead of waiting for
            # the next weekly refresh.
            await conn.execute(
                """
                UPDATE chart_album
                SET release_group_mbid = $1, release_mbid = ''
                WHERE lower(artist) = lower($2) AND lower(title) = lower($3)
                """,
                rg_mbid, artist, title,
            )
    return {"status": "ok", "release_group_mbid": rg_mbid}


@router.delete("/override", dependencies=[Depends(get_current_admin_user_jwt)])
async def delete_chart_override(body: ChartOverrideKey):
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM chart_match_override
            WHERE lower(artist) = lower($1) AND lower(title) = lower($2)
            """,
            body.artist.strip(), body.title.strip(),
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="No override for that entry")
    return {"status": "deleted"}
