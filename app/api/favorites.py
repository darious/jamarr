import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_current_user_jwt
from app.api.library import sha1_to_hex
from app.db import get_db


router = APIRouter(
    prefix="/api/favorites",
    tags=["favorites"],
    dependencies=[Depends(get_current_user_jwt)],
)


class FavoriteToggleRequest(BaseModel):
    favorite: bool


@router.get("/artists")
async def list_favorite_artists(
    user: asyncpg.Record = Depends(get_current_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch(
        """
        SELECT
            a.mbid,
            a.name,
            ar.sha1 AS art_sha1,
            COALESCE(lp.listens, 0) AS listens,
            f.created_at
        FROM favorite_artist f
        JOIN artist a ON a.mbid = f.artist_mbid
        LEFT JOIN artwork ar ON a.artwork_id = ar.id
        LEFT JOIN LATERAL (
            SELECT COUNT(h.source_id) AS listens
            FROM track_artist ta
            JOIN combined_playback_history_mat h ON h.track_id = ta.track_id
            WHERE ta.artist_mbid = a.mbid
        ) lp ON TRUE
        WHERE f.user_id = $1
        ORDER BY f.created_at DESC
        """,
        user["id"],
    )
    return [
        {
            "mbid": r["mbid"],
            "name": r["name"],
            "art_sha1": sha1_to_hex(r["art_sha1"]),
            "listens": r["listens"],
        }
        for r in rows
    ]


@router.get("/releases")
async def list_favorite_releases(
    user: asyncpg.Record = Depends(get_current_user_jwt),
    db: asyncpg.Connection = Depends(get_db),
):
    rows = await db.fetch(
        """
        SELECT
            al.mbid AS album_mbid,
            al.title,
            COALESCE(MAX(t.album_artist), MAX(t.artist)) AS artist_name,
            al.release_date,
            ar.sha1 AS art_sha1,
            f.created_at
        FROM favorite_release f
        JOIN album al ON al.mbid = f.album_mbid
        LEFT JOIN artwork ar ON al.artwork_id = ar.id
        LEFT JOIN track t ON t.release_mbid = al.mbid
        WHERE f.user_id = $1
        GROUP BY al.mbid, al.title, al.release_date, ar.sha1, f.created_at
        ORDER BY f.created_at DESC
        """,
        user["id"],
    )
    return [
        {
            "album_mbid": r["album_mbid"],
            "title": r["title"],
            "artist_name": r["artist_name"],
            "year": r["release_date"],
            "art_sha1": sha1_to_hex(r["art_sha1"]),
        }
        for r in rows
    ]


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
