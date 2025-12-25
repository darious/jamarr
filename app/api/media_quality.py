from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from fastapi import APIRouter
from app.db import get_db

router = APIRouter()


class EntityItem(BaseModel):
    name: str
    mbid: str
    image_url: Optional[str] = None


@router.get("/api/media-quality/items", response_model=List[EntityItem])
async def list_media_quality_items(
    category: str,  # 'all' or 'primary'
    filter_type: str,  # 'total', 'background', 'source'
    filter_value: Optional[str] = None,
):
    items = []
    async for db in get_db():
        # Base query
        query = "SELECT mbid, name, image_url, art_id FROM artists ar"
        where_clauses = []
        params = []

        # 1. Category Filter
        if category == "primary":
            where_clauses.append("mbid IN (SELECT DISTINCT artist_mbid FROM artist_albums WHERE type='primary')")
        
        # 2. Specific Filter Logic
        if filter_type == "total":
             pass # No extra filter needed beyond category
        
        elif filter_type == "background":
            # Must have background art
            where_clauses.append("""
                mbid IN (
                    SELECT entity_id FROM image_mapping 
                    WHERE entity_type='artist' AND image_type='artistbackground'
                )
            """)
        
        elif filter_type == "source":
            # Join artwork to filter by source
            # Note: We do a LEFT JOIN in the base query concept, but here we can just check art_id logic
            # However, since we need to filter by the source column on the joined table, we need to handle the join or subquery.
            
            if filter_value == "None":
                 where_clauses.append("art_id IS NULL")
            elif filter_value == "Fanart":
                 where_clauses.append("art_id IN (SELECT id FROM artwork WHERE source LIKE '%fanart%')")
            elif filter_value == "Spotify":
                 where_clauses.append("art_id IN (SELECT id FROM artwork WHERE source LIKE '%spotify%')")
            else:
                 # Other
                 where_clauses.append("art_id IS NOT NULL")
                 where_clauses.append("art_id NOT IN (SELECT id FROM artwork WHERE source LIKE '%fanart%' OR source LIKE '%spotify%')")

        # Construct final SQL
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        
        query += " ORDER BY sort_name ASC LIMIT 500" # Cap results for safety

        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                items.append({
                    "name": row["name"] or "Unknown",
                    "mbid": row["mbid"],
                    "image_url": row["image_url"] 
                })
    
    return items


@router.get("/api/media-quality/summary")
async def media_quality_summary():
    async for db in get_db():
        stats = {
            "all": {"total": 0, "with_background": 0, "sources": {}},
            "primary": {"total": 0, "with_background": 0, "sources": {}},
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

        return {"artist_stats": stats}
