import json
import os
import time
from typing import Any, Dict, List, Tuple

from PIL import Image, UnidentifiedImageError

from app.db import get_db
from app.media.art import _get_art_path

ART_MIN_SIZE = 500
ART_MAX_SIZE = 2800
ASPECT_THRESHOLD = 2.0
TINY_FILESIZE_BYTES = 15 * 1024


def _compute_art_path(sha1: str, art_type: str, path_on_disk: str | None) -> str:
    """Choose the best-known path for an artwork file."""
    if path_on_disk and os.path.exists(path_on_disk):
        return path_on_disk
    return _get_art_path(sha1, art_type or "album")


def _check_artwork_file(path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Inspect a cached artwork file and return issue list plus metadata.
    Issues are returned as a list of {code, details}.
    """
    issues: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {
        "width": None,
        "height": None,
        "mime": None,
        "format": None,
        "filesize": None,
        "path": path,
    }

    if not os.path.exists(path):
        issues.append({"code": "missing_cache_file", "details": {"path": path}})
        return issues, meta

    try:
        meta["filesize"] = os.path.getsize(path)
    except OSError:
        meta["filesize"] = None

    try:
        with Image.open(path) as img:
            width, height = img.size
            meta.update(
                {
                    "width": width,
                    "height": height,
                    "format": img.format,
                    "mime": Image.MIME.get(img.format, None),
                }
            )
            min_dim = min(width, height)
            max_dim = max(width, height)
            aspect = max_dim / min_dim if min_dim else None

            if min_dim < ART_MIN_SIZE:
                issues.append(
                    {"code": "art_too_small", "details": {"width": width, "height": height}}
                )
            if max_dim > ART_MAX_SIZE:
                issues.append(
                    {"code": "art_too_large", "details": {"width": width, "height": height}}
                )
            if aspect and aspect > ASPECT_THRESHOLD:
                issues.append(
                    {
                        "code": "extreme_aspect",
                        "details": {"width": width, "height": height, "aspect": aspect},
                    }
                )
    except (UnidentifiedImageError, OSError) as e:
        issues.append({"code": "unreadable_image", "details": {"path": path, "error": str(e)}})

    if meta.get("filesize") is not None and meta["filesize"] < TINY_FILESIZE_BYTES:
        issues.append({"code": "tiny_filesize", "details": {"bytes": meta["filesize"]}})

    return issues, meta


async def _insert_issue(
    db, entity_type: str, entity_id: Any, issue_code: str, details: Dict[str, Any] | None
):
    payload = json.dumps(details or {})
    await db.execute(
        """
        INSERT INTO media_quality_issues (entity_type, entity_id, issue_code, details, created_at, resolved_at)
        VALUES (?, ?, ?, ?, ?, NULL)
        """,
        (entity_type, str(entity_id) if entity_id is not None else None, issue_code, payload, time.time()),
    )


async def run_media_quality_checks(force: bool = False) -> Dict[str, int]:
    """
    Run media quality checks against cached artwork and metadata.
    Artwork checks only process rows missing checked_at unless force=True.
    Results are stored on artwork rows and in media_quality_issues.
    """
    stats: Dict[str, int] = {
        "artwork_checked": 0,
        "artwork_issues": 0,
        "missing_art_records": 0,
        "metadata_issues": 0,
        "orphan_cache_files": 0,
    }

    async for db in get_db():
        # --- Artwork checks ---
        art_query = "SELECT id, sha1, type, path_on_disk FROM artwork"
        if not force:
            art_query += " WHERE checked_at IS NULL"
        async with db.execute(art_query) as cursor:
            art_rows = await cursor.fetchall()

        stats["artwork_checked"] = len(art_rows)

        for row in art_rows:
            art_id = row["id"]
            art_type = row["type"] or "album"
            path = _compute_art_path(row["sha1"], art_type, row["path_on_disk"])

            await db.execute(
                "DELETE FROM media_quality_issues WHERE entity_type='artwork' AND entity_id = ?",
                (str(art_id),),
            )

            issues, meta = _check_artwork_file(path)
            meta["path"] = path  # ensure stored path is the computed one

            await db.execute(
                """
                UPDATE artwork
                SET width=?, height=?, mime=COALESCE(mime, ?), path_on_disk=?, filesize_bytes=?, image_format=?, checked_at=?, check_errors=?
                WHERE id=?
                """,
                (
                    meta.get("width"),
                    meta.get("height"),
                    meta.get("mime"),
                    meta.get("path"),
                    meta.get("filesize"),
                    meta.get("format"),
                    time.time(),
                    json.dumps(issues),
                    art_id,
                ),
            )

            for issue in issues:
                await _insert_issue(db, "artwork", art_id, issue["code"], {**issue.get("details", {}), "path": path})
            stats["artwork_issues"] += len(issues)

        # --- Missing artwork on entities ---
        await db.execute(
            "DELETE FROM media_quality_issues WHERE entity_type IN ('track','album','artist','cache_file')"
        )

        async with db.execute(
            "SELECT id, title, artist FROM tracks WHERE art_id IS NULL OR art_id = ''"
        ) as cursor:
            missing_tracks = await cursor.fetchall()
        for row in missing_tracks:
            await _insert_issue(
                db, "track", row["id"], "missing_artwork", {"title": row["title"], "artist": row["artist"]}
            )
        stats["missing_art_records"] += len(missing_tracks)

        async with db.execute(
            """
            SELECT t.id, t.title, t.artist, t.art_id
            FROM tracks t
            LEFT JOIN artwork a ON t.art_id = a.id
            WHERE t.art_id IS NOT NULL AND a.id IS NULL
            """
        ) as cursor:
            broken_track_art = await cursor.fetchall()
        for row in broken_track_art:
            await _insert_issue(
                db,
                "track",
                row["id"],
                "artwork_missing_record",
                {"title": row["title"], "artist": row["artist"], "art_id": row["art_id"]},
            )
        stats["missing_art_records"] += len(broken_track_art)

        async with db.execute(
            "SELECT mbid, name FROM artists WHERE art_id IS NULL OR art_id = ''"
        ) as cursor:
            missing_artists = await cursor.fetchall()
        for row in missing_artists:
            await _insert_issue(
                db, "artist", row["mbid"], "missing_artwork", {"name": row["name"], "mbid": row["mbid"]}
            )
        stats["missing_art_records"] += len(missing_artists)

        async with db.execute(
            """
            SELECT a.mbid, a.name, a.art_id
            FROM artists a
            LEFT JOIN artwork aw ON a.art_id = aw.id
            WHERE a.art_id IS NOT NULL AND aw.id IS NULL
            """
        ) as cursor:
            broken_artist_art = await cursor.fetchall()
        for row in broken_artist_art:
            await _insert_issue(
                db,
                "artist",
                row["mbid"],
                "artwork_missing_record",
                {"name": row["name"], "mbid": row["mbid"], "art_id": row["art_id"]},
            )
        stats["missing_art_records"] += len(broken_artist_art)

        async with db.execute(
            "SELECT mbid, title FROM albums WHERE art_id IS NULL OR art_id = ''"
        ) as cursor:
            missing_albums = await cursor.fetchall()
        for row in missing_albums:
            await _insert_issue(
                db, "album", row["mbid"], "missing_artwork", {"title": row["title"], "mbid": row["mbid"]}
            )
        stats["missing_art_records"] += len(missing_albums)

        async with db.execute(
            """
            SELECT al.mbid, al.title, al.art_id
            FROM albums al
            LEFT JOIN artwork aw ON al.art_id = aw.id
            WHERE al.art_id IS NOT NULL AND aw.id IS NULL
            """
        ) as cursor:
            broken_album_art = await cursor.fetchall()
        for row in broken_album_art:
            await _insert_issue(
                db,
                "album",
                row["mbid"],
                "artwork_missing_record",
                {"title": row["title"], "mbid": row["mbid"], "art_id": row["art_id"]},
            )
        stats["missing_art_records"] += len(broken_album_art)

        # --- Metadata + MusicBrainz checks ---
        async with db.execute(
            """
            SELECT id, title, artist, album, genre, date, track_no,
                   mb_artist_id, mb_album_artist_id, mb_track_id, mb_release_track_id, mb_release_id, mb_release_group_id
            FROM tracks
            """
        ) as cursor:
            track_rows = await cursor.fetchall()

        for row in track_rows:
            missing_fields: List[str] = []
            missing_mb: List[str] = []
            if not row["title"]:
                missing_fields.append("title")
            if not row["artist"]:
                missing_fields.append("artist")
            if not row["album"]:
                missing_fields.append("album")
            if not row["date"]:
                missing_fields.append("date")
            if not row["track_no"]:
                missing_fields.append("track_no")

            for key in [
                "mb_artist_id",
                "mb_album_artist_id",
                "mb_track_id",
                "mb_release_track_id",
                "mb_release_id",
                "mb_release_group_id",
            ]:
                if not row[key]:
                    missing_mb.append(key)

            if missing_fields:
                stats["metadata_issues"] += 1
                await _insert_issue(
                    db,
                    "track",
                    row["id"],
                    "metadata_missing",
                    {"missing": missing_fields, "title": row["title"], "artist": row["artist"]},
                )
            if missing_mb:
                stats["metadata_issues"] += 1
                await _insert_issue(
                    db,
                    "track",
                    row["id"],
                    "musicbrainz_missing",
                    {"missing": missing_mb, "title": row["title"], "artist": row["artist"]},
                )

        # --- Cache/DB consistency (orphans) ---
        async with db.execute("SELECT sha1, type FROM artwork") as cursor:
            art_rows = await cursor.fetchall()
        known_shas = {(r["sha1"], (r["type"] or "album")) for r in art_rows}

        cache_root = "cache/art"
        for subdir in ("album", "artist"):
            root = os.path.join(cache_root, subdir)
            if not os.path.isdir(root):
                continue
            for bucket in os.listdir(root):
                bucket_path = os.path.join(root, bucket)
                if not os.path.isdir(bucket_path):
                    continue
                for filename in os.listdir(bucket_path):
                    file_path = os.path.join(bucket_path, filename)
                    if not os.path.isfile(file_path):
                        continue
                    sha = os.path.basename(filename)
                    if (sha, subdir) not in known_shas:
                        stats["orphan_cache_files"] += 1
                        await _insert_issue(
                            db,
                            "cache_file",
                            sha,
                            "orphan_cache_file",
                            {"path": file_path, "type": subdir},
                        )

        await db.commit()
        return stats
