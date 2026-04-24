import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_current_user_jwt
from app.db import get_db


router = APIRouter(
    prefix="/api/favorites",
    tags=["favorites"],
    dependencies=[Depends(get_current_user_jwt)],
)


class FavoriteToggleRequest(BaseModel):
    favorite: bool


async def _ensure_exists(
    db: asyncpg.Connection, table: str, key_column: str, value: str
) -> None:
    row = await db.fetchrow(
        f"SELECT 1 FROM {table} WHERE {key_column} = $1",
        value,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.put("/artists/{artist_mbid}")
async def toggle_artist_favorite(
    artist_mbid: str,
    payload: FavoriteToggleRequest,
    user: asyncpg.Record = Depends(get_current_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
):
    await _ensure_exists(db, "artist", "mbid", artist_mbid)

    if payload.favorite:
        await db.execute(
            """
            INSERT INTO favorite_artist (user_id, artist_mbid)
            VALUES ($1, $2)
            ON CONFLICT (user_id, artist_mbid) DO NOTHING
            """,
            user["id"],
            artist_mbid,
        )
    else:
        await db.execute(
            "DELETE FROM favorite_artist WHERE user_id = $1 AND artist_mbid = $2",
            user["id"],
            artist_mbid,
        )

    return {"artist_mbid": artist_mbid, "favorite": payload.favorite}


@router.put("/releases/{album_mbid}")
async def toggle_release_favorite(
    album_mbid: str,
    payload: FavoriteToggleRequest,
    user: asyncpg.Record = Depends(get_current_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
):
    await _ensure_exists(db, "album", "mbid", album_mbid)

    if payload.favorite:
        await db.execute(
            """
            INSERT INTO favorite_release (user_id, album_mbid)
            VALUES ($1, $2)
            ON CONFLICT (user_id, album_mbid) DO NOTHING
            """,
            user["id"],
            album_mbid,
        )
    else:
        await db.execute(
            "DELETE FROM favorite_release WHERE user_id = $1 AND album_mbid = $2",
            user["id"],
            album_mbid,
        )

    return {"album_mbid": album_mbid, "favorite": payload.favorite}
