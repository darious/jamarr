from fastapi import APIRouter, Depends
from app.db import get_db
import asyncpg
from typing import Optional

router = APIRouter()


@router.get("/api/media-quality/items")
async def get_media_quality_items(
    category: str,
    filter_type: str,  # 'total', 'background', 'artwork', 'source', 'link_type', 'missing_link_type'
    filter_value: Optional[str] = None,
    db: asyncpg.Connection = Depends(get_db),
):

    # Base query
    query = ""
    params = []
    where_clauses = []

    if category == "album":
        query = """
            SELECT al.mbid, al.title as name, NULL as image_url, ar.name as artist_name, al.artwork_id 
            FROM album al
            LEFT JOIN artist_album aa ON al.mbid = aa.album_mbid AND aa.type='primary'
            LEFT JOIN artist ar ON aa.artist_mbid = ar.mbid
         """
        # Postgres requires grouping by all selected columns or using an aggregate
        # But here we are selecting specific rows. We might need DISTINCT if joins cause dupes.
        # Actually, one album can have multiple primary artists. We should probably just pick one for display or group.
        # For simplicity let's rely on DISTINCT in the SELECT or handle it

        # Retaining the logic from before, but fixing for Postgres strictness if needed.
        # The previous code had "GROUP BY al.mbid" which implies non-aggregated columns.
        # In Postgres, we must include them in GROUP BY.
        # Let's verify if we need GROUP BY. If we join artist_album, we might get duplicates.
        # Let's filter first, then join.

        tbl = "al"
    else:
        query = "SELECT mbid, name, image_url, artwork_id FROM artist ar"
        tbl = "ar"

    # 1. Category Filter handled by table selection
    # But for "primary" artists, we need a specific filter
    if category == "primary":
        where_clauses.append(
            f"{tbl}.mbid IN (SELECT DISTINCT artist_mbid FROM artist_album WHERE type='primary')"
        )

    # 2. Specific Filter Logic
    if filter_type == "total":
        pass  # No extra filter needed beyond category

    elif filter_type == "background":
        if category == "album":
            pass
        else:
            where_clauses.append(f"""
                {tbl}.mbid IN (
                    SELECT entity_id FROM image_map 
                    WHERE entity_type='artist' AND image_type='artistbackground'
                )
            """)

    elif filter_type == "artwork":
        if filter_value == "missing":
            where_clauses.append(f"{tbl}.artwork_id IS NULL")
        elif filter_value == "present":
            where_clauses.append(f"{tbl}.artwork_id IS NOT NULL")

    elif filter_type == "source":
        # Need to join artwork table to filter by source
        # We can use a subquery for cleanliness
        if filter_value == "None":
            where_clauses.append(f"{tbl}.artwork_id IS NULL")
        elif filter_value == "Fanart":
            where_clauses.append(
                f"{tbl}.artwork_id IN (SELECT id FROM artwork WHERE source ILIKE '%fanart%')"
            )
        elif filter_value == "Spotify":
            where_clauses.append(
                f"{tbl}.artwork_id IN (SELECT id FROM artwork WHERE source ILIKE '%spotify%')"
            )
        else:
            where_clauses.append(f"{tbl}.artwork_id IS NOT NULL")
            where_clauses.append(
                f"{tbl}.artwork_id NOT IN (SELECT id FROM artwork WHERE source ILIKE '%fanart%' OR source ILIKE '%spotify%')"
            )

    elif filter_type == "missing_link_type":
        if filter_value:
            # Handle special metadata filters that reuse the link UI
            if filter_value == "release type":
                where_clauses.append(f"{tbl}.release_type_raw = '<none>'")
            elif filter_value == "release date":
                where_clauses.append(f"{tbl}.release_date IS NULL")
            else:
                idx = len(params) + 1
                where_clauses.append(
                    f"{tbl}.mbid NOT IN (SELECT entity_id FROM external_link WHERE type=${idx} AND entity_type=CASE WHEN '{category}'='album' THEN 'album' ELSE 'artist' END)"
                )
                params.append(filter_value)
    
    elif filter_type == "link_type":
        if filter_value:
            if filter_value == "release type":
                where_clauses.append(f"{tbl}.release_type_raw != '<none>'")
            elif filter_value == "release date":
                where_clauses.append(f"{tbl}.release_date IS NOT NULL")
            else:
                idx = len(params) + 1
                where_clauses.append(
                    f"{tbl}.mbid IN (SELECT entity_id FROM external_link WHERE type=${idx} AND entity_type=CASE WHEN '{category}'='album' THEN 'album' ELSE 'artist' END)"
                )
                params.append(filter_value)


    # Construct final SQL
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    if category == "album":
        query += " ORDER BY al.title ASC LIMIT 500"
    else:
        query += " ORDER BY ar.sort_name ASC LIMIT 500"

    rows = await db.fetch(query, *params)

    val_items = []
    for row in rows:
        r = dict(row)
        val_items.append(
            {
                "name": r["name"] or "Unknown",
                "mbid": r["mbid"],
                "image_url": r.get("image_url"),
                "artist_name": r.get("artist_name"),
            }
        )

    return val_items


@router.get("/api/media-quality/summary")
async def media_quality_summary(db: asyncpg.Connection = Depends(get_db)):
    stats = {
        "all": {"total": 0, "with_background": 0, "sources": {}, "link_stats": {}},
        "primary": {"total": 0, "with_background": 0, "sources": {}, "link_stats": {}},
        "album_stats": {"total": 0, "with_artwork": 0, "sources": {}, "link_stats": {}},
    }

    # --- ALL ARTISTS ---
    stats["all"]["total"] = await db.fetchval("SELECT COUNT(*) FROM artist")

    stats["all"]["with_background"] = await db.fetchval(
        "SELECT COUNT(DISTINCT entity_id) FROM image_map WHERE entity_type='artist' AND image_type='artistbackground'"
    )

    rows = await db.fetch("""
        SELECT 
            CASE 
                WHEN artwork_id IS NULL THEN 'None'
                WHEN a.source ILIKE '%fanart%' THEN 'Fanart'
                WHEN a.source ILIKE '%spotify%' THEN 'Spotify'
                ELSE 'Other'
            END as src,
            COUNT(*)
        FROM artist ar
        LEFT JOIN artwork a ON ar.artwork_id = a.id
        GROUP BY src
    """)
    for row in rows:
        stats["all"]["sources"][row["src"]] = row["count"]

    rows = await db.fetch("""
        SELECT type, COUNT(*) 
        FROM external_link 
        WHERE entity_type='artist' 
        GROUP BY type
    """)
    for row in rows:
        stats["all"]["link_stats"][row["type"]] = row["count"]

    # --- PRIMARY ARTISTS ---
    # Filter artists that have at least one album where they are 'primary'
    # Use EXISTS for better performance than IN with subquery
    primary_filter_sql = "EXISTS (SELECT 1 FROM artist_album aa WHERE aa.artist_mbid = ar.mbid AND aa.type='primary')"

    stats["primary"]["total"] = await db.fetchval(
        f"SELECT COUNT(*) FROM artist ar WHERE {primary_filter_sql}"
    )

    # For backgrounds, we need to join or filter
    stats["primary"]["with_background"] = await db.fetchval("""
        SELECT COUNT(DISTINCT entity_id) 
        FROM image_map im
        WHERE entity_type='artist' 
          AND image_type='artistbackground' 
          AND EXISTS (SELECT 1 FROM artist_album aa WHERE aa.artist_mbid = im.entity_id AND aa.type='primary')
    """)

    rows = await db.fetch(f"""
        SELECT 
            CASE 
                WHEN artwork_id IS NULL THEN 'None'
                WHEN a.source ILIKE '%fanart%' THEN 'Fanart'
                WHEN a.source ILIKE '%spotify%' THEN 'Spotify'
                ELSE 'Other'
            END as src,
            COUNT(*)
        FROM artist ar
        LEFT JOIN artwork a ON ar.artwork_id = a.id
        WHERE {primary_filter_sql}
        GROUP BY src
    """)
    for row in rows:
        stats["primary"]["sources"][row["src"]] = row["count"]

    rows = await db.fetch("""
        SELECT el.type, COUNT(*) 
        FROM external_link el
        WHERE el.entity_type='artist' AND EXISTS (
            SELECT 1 FROM artist_album aa WHERE aa.artist_mbid = el.entity_id AND aa.type='primary'
        )
        GROUP BY el.type
    """)
    for row in rows:
        stats["primary"]["link_stats"][row["type"]] = row["count"]

    # --- ALBUMS ---
    stats["album_stats"]["total"] = await db.fetchval("SELECT COUNT(*) FROM album")

    stats["album_stats"]["with_artwork"] = await db.fetchval(
        "SELECT COUNT(*) FROM album WHERE artwork_id IS NOT NULL"
    )

    rows = await db.fetch("""
        SELECT type, COUNT(*) 
        FROM external_link 
        WHERE entity_type='album' 
        GROUP BY type
    """)
    for row in rows:
        stats["album_stats"]["link_stats"][row["type"]] = row["count"]

    # Add Metadata Stats (Release Type, Release Date) disguised as links for UI compatibility
    # Count PRESENT items, so the UI calculates MISSING correctly (Total - Present)
    
    # Release Date Present
    stats["album_stats"]["link_stats"]["release date"] = await db.fetchval(
        "SELECT COUNT(*) FROM album WHERE release_date IS NOT NULL"
    )
    
    # Release Type Present (NOT <none> and NOT NULL)
    stats["album_stats"]["link_stats"]["release type"] = await db.fetchval(
        "SELECT COUNT(*) FROM album WHERE release_type_raw != '<none>'"
    )


    return {
        "artist_stats": {"all": stats["all"], "primary": stats["primary"]},
        "album_stats": stats["album_stats"],
    }
