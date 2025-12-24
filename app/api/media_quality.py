from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from fastapi import APIRouter
from app.db import get_db

router = APIRouter()


class EntityItem(BaseModel):
    name: str
    mbid: str
    image_url: Optional[str] = None
    artist_name: Optional[str] = None


@router.get("/api/media-quality/items", response_model=List[EntityItem])
async def list_media_quality_items(
    category: str,  # 'all' or 'primary'
    filter_type: str,  # 'total', 'background', 'source', 'link_type'
    filter_value: Optional[str] = None,
):
    items = []
    async for db in get_db():
        # Base query
        # Base query
        group_by = ""
        
        if category == "album":
             query = """
                SELECT al.mbid, al.title as name, NULL as image_url, ar.name as artist_name, al.art_id 
                FROM albums al
                LEFT JOIN artist_albums aa ON al.mbid = aa.album_mbid AND aa.type='primary'
                LEFT JOIN artists ar ON aa.artist_mbid = ar.mbid
             """
             group_by = " GROUP BY al.mbid"
             tbl = "al"
        else:
             query = "SELECT mbid, name, image_url, art_id FROM artists ar"
             tbl = "ar"
        
        where_clauses = []
        params = []

        # 1. Category Filter
        if category == "primary":
            where_clauses.append(f"{tbl}.mbid IN (SELECT DISTINCT artist_mbid FROM artist_albums WHERE type='primary')")
        
        # 2. Specific Filter Logic
        if filter_type == "total":
             pass # No extra filter needed beyond category
        
        elif filter_type == "background":
            if category == "album":
                 pass
            else:
                where_clauses.append(f"""
                    {tbl}.mbid IN (
                        SELECT entity_id FROM image_mapping 
                        WHERE entity_type='artist' AND image_type='artistbackground'
                    )
                """)
        
        elif filter_type == "artwork":
             if filter_value == "missing":
                  where_clauses.append(f"{tbl}.art_id IS NULL")
             elif filter_value == "present":
                  where_clauses.append(f"{tbl}.art_id IS NOT NULL")

        elif filter_type == "source":
            if filter_value == "None":
                 where_clauses.append(f"{tbl}.art_id IS NULL")
            elif filter_value == "Fanart":
                 where_clauses.append(f"{tbl}.art_id IN (SELECT id FROM artwork WHERE source LIKE '%fanart%')")
            elif filter_value == "Spotify":
                 where_clauses.append(f"{tbl}.art_id IN (SELECT id FROM artwork WHERE source LIKE '%spotify%')")
            else:
                 where_clauses.append(f"{tbl}.art_id IS NOT NULL")
                 where_clauses.append(f"{tbl}.art_id NOT IN (SELECT id FROM artwork WHERE source LIKE '%fanart%' OR source LIKE '%spotify%')")

        elif filter_type == "link_type":
             entity_type = 'album' if category == 'album' else 'artist'
             if filter_value:
                 where_clauses.append(f"{tbl}.mbid IN (SELECT entity_id FROM external_links WHERE type='{filter_value}' AND entity_type='{entity_type}')")

        elif filter_type == "missing_link_type":
             entity_type = 'album' if category == 'album' else 'artist'
             if filter_value:
                 where_clauses.append(f"{tbl}.mbid NOT IN (SELECT entity_id FROM external_links WHERE type='{filter_value}' AND entity_type='{entity_type}')")

        # Construct final SQL
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        
        if group_by:
            query += group_by

        if category == "album":
             query += " ORDER BY al.title ASC LIMIT 500"
        else:
             query += " ORDER BY ar.sort_name ASC LIMIT 500"

        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                items.append({
                    "name": row["name"] or "Unknown",
                    "mbid": row["mbid"],
                    "image_url": row["image_url"],
                    "artist_name": row["artist_name"] if "artist_name" in row.keys() else None
                })
    
    return items


@router.get("/api/media-quality/summary")
async def media_quality_summary():
    async for db in get_db():
        stats = {
            "all": {"total": 0, "with_background": 0, "sources": {}, "link_stats": {}},
            "primary": {"total": 0, "with_background": 0, "sources": {}, "link_stats": {}},
        }

        # --- ALL ARTISTS ---
        async with db.execute("SELECT COUNT(*) FROM artists") as cursor:
            row = await cursor.fetchone()
            if row:
                stats["all"]["total"] = row[0]

        async with db.execute(
            "SELECT COUNT(DISTINCT entity_id) FROM image_mapping WHERE entity_type='artist' AND image_type='artistbackground'"
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                stats["all"]["with_background"] = row[0]

        async with db.execute("""
            SELECT 
                CASE 
                    WHEN art_id IS NULL THEN 'None'
                    WHEN a.source LIKE '%fanart%' THEN 'Fanart'
                    WHEN a.source LIKE '%spotify%' THEN 'Spotify'
                    ELSE 'Other'
                END as src,
                COUNT(*)
            FROM artists ar
            LEFT JOIN artwork a ON ar.art_id = a.id
            GROUP BY src
        """) as cursor:
            for row in await cursor.fetchall():
                stats["all"]["sources"][row[0]] = row[1]

        async with db.execute("""
            SELECT type, COUNT(*) 
            FROM external_links 
            WHERE entity_type='artist' 
            GROUP BY type
        """) as cursor:
            for row in await cursor.fetchall():
                stats["all"]["link_stats"][row[0]] = row[1]

        # --- PRIMARY ARTISTS ---
        # Filter artists that have at least one album where they are 'primary'
        primary_filter = "mbid IN (SELECT DISTINCT artist_mbid FROM artist_albums WHERE type='primary')"
        
        async with db.execute(f"SELECT COUNT(*) FROM artists WHERE {primary_filter}") as cursor:
            row = await cursor.fetchone()
            if row:
                stats["primary"]["total"] = row[0]

        async with db.execute(
            f"SELECT COUNT(DISTINCT entity_id) FROM image_mapping WHERE entity_type='artist' AND image_type='artistbackground' AND entity_id IN (SELECT mbid FROM artists WHERE {primary_filter})"
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                stats["primary"]["with_background"] = row[0]

        async with db.execute(f"""
            SELECT 
                CASE 
                    WHEN art_id IS NULL THEN 'None'
                    WHEN a.source LIKE '%fanart%' THEN 'Fanart'
                    WHEN a.source LIKE '%spotify%' THEN 'Spotify'
                    ELSE 'Other'
                END as src,
                COUNT(*)
            FROM artists ar
            LEFT JOIN artwork a ON ar.art_id = a.id
            WHERE {primary_filter}
            GROUP BY src
        """) as cursor:
            for row in await cursor.fetchall():
                stats["primary"]["sources"][row[0]] = row[1]

        async with db.execute(f"""
            SELECT el.type, COUNT(*) 
            FROM external_links el
            WHERE el.entity_type='artist' AND el.entity_id IN (
                SELECT DISTINCT artist_mbid FROM artist_albums WHERE type='primary'
            )
            GROUP BY el.type
        """) as cursor:
            for row in await cursor.fetchall():
                stats["primary"]["link_stats"][row[0]] = row[1]

        # --- ALBUMS ---
        stats["album_stats"] = {"total": 0, "with_artwork": 0, "sources": {}, "link_stats": {}}
        
        async with db.execute("SELECT COUNT(*) FROM albums") as cursor:
            row = await cursor.fetchone()
            if row:
                stats["album_stats"]["total"] = row[0]

        async with db.execute("SELECT COUNT(*) FROM albums WHERE art_id IS NOT NULL") as cursor:
            row = await cursor.fetchone()
            if row:
                stats["album_stats"]["with_artwork"] = row[0]

        async with db.execute("""
            SELECT type, COUNT(*) 
            FROM external_links 
            WHERE entity_type='album' 
            GROUP BY type
        """) as cursor:
            for row in await cursor.fetchall():
                stats["album_stats"]["link_stats"][row[0]] = row[1]

        return {"artist_stats": stats, "album_stats": stats["album_stats"]}
