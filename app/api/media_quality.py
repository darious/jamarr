import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import get_db
from app.media.quality import run_media_quality_checks

router = APIRouter()


class QualityRunRequest(BaseModel):
    force: bool = False


@router.post("/api/media-quality/run")
async def trigger_media_quality_run(request: QualityRunRequest):
    try:
        stats = await run_media_quality_checks(force=request.force)
        return {"status": "ok", "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _safe_json_load(data: str | None) -> Dict[str, Any]:
    if not data:
        return {}
    try:
        return json.loads(data)
    except Exception:
        return {}


async def _fetch_context_maps(db, issues: List[Dict[str, Any]]):
    track_ids = []
    artwork_ids = []
    artist_ids = []
    album_ids = []

    for issue in issues:
        etype = issue["entity_type"]
        eid = issue["entity_id"]
        if not eid:
            continue
        if etype == "track":
            try:
                track_ids.append(int(eid))
            except ValueError:
                pass
        elif etype == "artwork":
            try:
                artwork_ids.append(int(eid))
            except ValueError:
                pass
        elif etype == "artist":
            artist_ids.append(eid)
        elif etype == "album":
            album_ids.append(eid)

    track_map: Dict[int, Dict[str, Any]] = {}
    if track_ids:
        placeholders = ",".join("?" * len(track_ids))
        async with db.execute(
            f"SELECT id, title, artist, album, art_id FROM tracks WHERE id IN ({placeholders})",
            track_ids,
        ) as cursor:
            for row in await cursor.fetchall():
                track_map[row["id"]] = {
                    "title": row["title"],
                    "artist": row["artist"],
                    "album": row["album"],
                    "art_id": row["art_id"],
                }

    artwork_map: Dict[int, Dict[str, Any]] = {}
    if artwork_ids:
        placeholders = ",".join("?" * len(artwork_ids))
        async with db.execute(
            f"""
            SELECT id, sha1, type, width, height, filesize_bytes, image_format, mime, path_on_disk, check_errors
            FROM artwork WHERE id IN ({placeholders})
            """,
            artwork_ids,
        ) as cursor:
            for row in await cursor.fetchall():
                context = {
                    "sha1": row["sha1"],
                    "type": row["type"] or "album",
                    "width": row["width"],
                    "height": row["height"],
                    "filesize_bytes": row["filesize_bytes"],
                    "image_format": row["image_format"],
                    "mime": row["mime"],
                    "path_on_disk": row["path_on_disk"],
                    "check_errors": _safe_json_load(row["check_errors"]),
                }
                # Attach a sample track using this artwork for easier linking
                async with db.execute(
                    """
                    SELECT title, artist, album, album_artist
                    FROM tracks
                    WHERE art_id = ?
                    LIMIT 1
                    """,
                    (row["id"],),
                ) as tcur:
                    trow = await tcur.fetchone()
                    if trow:
                        context["sample_track"] = {
                            "title": trow["title"],
                            "artist": trow["artist"],
                            "album": trow["album"],
                            "album_artist": trow["album_artist"],
                        }

                artwork_map[row["id"]] = context

    artist_map: Dict[str, Dict[str, Any]] = {}
    if artist_ids:
        placeholders = ",".join("?" * len(artist_ids))
        async with db.execute(
            f"SELECT mbid, name, art_id FROM artists WHERE mbid IN ({placeholders})", artist_ids
        ) as cursor:
            for row in await cursor.fetchall():
                artist_map[row["mbid"]] = {"name": row["name"], "art_id": row["art_id"]}

    album_map: Dict[str, Dict[str, Any]] = {}
    if album_ids:
        placeholders = ",".join("?" * len(album_ids))
        async with db.execute(
            f"""
            SELECT al.mbid, al.title, al.art_id,
                   (SELECT COALESCE(t.album_artist, t.artist)
                    FROM tracks t
                    WHERE t.mb_release_group_id = al.mbid OR t.album = al.title
                    LIMIT 1) AS album_artist
            FROM albums al
            WHERE al.mbid IN ({placeholders})
            """,
            album_ids,
        ) as cursor:
            for row in await cursor.fetchall():
                album_map[row["mbid"]] = {
                    "title": row["title"],
                    "art_id": row["art_id"],
                    "album_artist": row["album_artist"],
                }

    return track_map, artwork_map, artist_map, album_map


@router.get("/api/media-quality/issues")
async def list_media_quality_issues(
    entity_type: Optional[str] = None,
    issue_code: Optional[str] = None,
    include_resolved: bool = False,
    limit: int = 200,
):
    async for db in get_db():
        clauses = []
        params: List[Any] = []
        query = "SELECT id, entity_type, entity_id, issue_code, details, created_at, resolved_at FROM media_quality_issues"

        if not include_resolved:
            clauses.append("resolved_at IS NULL")
        if entity_type:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if issue_code:
            clauses.append("issue_code = ?")
            params.append(issue_code)

        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        issues = [
            {
                "id": row["id"],
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "issue_code": row["issue_code"],
                "details": _safe_json_load(row["details"]),
                "created_at": row["created_at"],
                "resolved_at": row["resolved_at"],
            }
            for row in rows
        ]

        track_map, artwork_map, artist_map, album_map = await _fetch_context_maps(db, issues)

        for issue in issues:
            etype = issue["entity_type"]
            eid = issue["entity_id"]
            if etype == "track" and eid:
                try:
                    issue["context"] = track_map.get(int(eid))
                except ValueError:
                    issue["context"] = None
            elif etype == "artwork" and eid:
                try:
                    issue["context"] = artwork_map.get(int(eid))
                except ValueError:
                    issue["context"] = None
            elif etype == "artist" and eid:
                issue["context"] = artist_map.get(eid)
            elif etype == "album" and eid:
                issue["context"] = album_map.get(eid)
            else:
                issue["context"] = None

        return {"issues": issues}


@router.get("/api/media-quality/summary")
async def media_quality_summary():
    async for db in get_db():
        summary: Dict[str, Any] = {"issue_counts": {}, "pending_artwork": 0, "artwork_with_issues": 0}

        async with db.execute(
            "SELECT issue_code, COUNT(*) as cnt FROM media_quality_issues WHERE resolved_at IS NULL GROUP BY issue_code"
        ) as cursor:
            for row in await cursor.fetchall():
                summary["issue_counts"][row["issue_code"]] = row["cnt"]

        async with db.execute("SELECT COUNT(*) FROM artwork WHERE checked_at IS NULL") as cursor:
            row = await cursor.fetchone()
            summary["pending_artwork"] = row[0] if row else 0

        async with db.execute(
            "SELECT COUNT(*) FROM artwork WHERE check_errors IS NOT NULL AND TRIM(check_errors) <> '' AND check_errors <> '[]'"
        ) as cursor:
            row = await cursor.fetchone()
            summary["artwork_with_issues"] = row[0] if row else 0

        return summary
