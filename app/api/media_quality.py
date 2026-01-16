from fastapi import APIRouter, Depends
from app.db import get_db
from app.api.deps import get_current_user_jwt
import asyncpg
from typing import Optional

router = APIRouter(dependencies=[Depends(get_current_user_jwt)])


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
        # Use CTE to calculate has_artwork, then filter on it
        # Check if ANY track in the release group has artwork (matches album page logic)
        query = """
            WITH album_with_artwork AS (
                SELECT DISTINCT ON (al.release_group_mbid)
                    al.release_group_mbid as mbid, 
                    al.title as name, 
                    NULL as image_url, 
                    ar.name as artist_name, 
                    ar.sort_name,
                    al.artwork_id,
                    EXISTS(
                        SELECT 1 FROM track t
                        WHERE t.release_group_mbid = al.release_group_mbid 
                          AND t.artwork_id IS NOT NULL
                    ) as has_artwork
                FROM album al
                LEFT JOIN artist_album aa ON al.mbid = aa.album_mbid AND aa.type='primary'
                LEFT JOIN artist ar ON aa.artist_mbid = ar.mbid
                WHERE al.release_group_mbid IS NOT NULL
                ORDER BY al.release_group_mbid, al.title ASC
            )
            SELECT mbid, name, image_url, artist_name, artwork_id, has_artwork, sort_name
            FROM album_with_artwork
            WHERE 1=1
         """
        tbl = "album_with_artwork"
    else:
        query = "SELECT mbid, name, image_url, artwork_id, sort_name, name as artist_name FROM artist ar"
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
        if category == "album":
            # For albums, use the has_artwork flag which checks all releases in the group
            if filter_value == "missing":
                where_clauses.append("has_artwork = false")
            elif filter_value == "present":
                where_clauses.append("has_artwork = true")
        else:
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
                if category == "album":
                    where_clauses.append("""
                        mbid NOT IN (
                            SELECT DISTINCT release_group_mbid 
                            FROM album 
                            WHERE release_type_raw != '<none>' AND release_group_mbid IS NOT NULL
                        )
                    """)
                else:
                    where_clauses.append(f"{tbl}.release_type_raw = '<none>'")
            elif filter_value == "release date":
                if category == "album":
                    where_clauses.append("""
                        mbid NOT IN (
                            SELECT DISTINCT release_group_mbid 
                            FROM album 
                            WHERE release_date IS NOT NULL AND release_group_mbid IS NOT NULL
                        )
                    """)
                else:
                    where_clauses.append(f"{tbl}.release_date IS NULL")
            else:
                idx = len(params) + 1
                if category == "album":
                    # For albums, join on release_group_mbid
                    where_clauses.append(
                        f"mbid NOT IN (SELECT DISTINCT a.release_group_mbid FROM external_link el JOIN album a ON el.entity_id = a.release_group_mbid WHERE el.type=${idx} AND el.entity_type='album' AND a.release_group_mbid IS NOT NULL)"
                    )
                else:
                    where_clauses.append(
                        f"{tbl}.mbid NOT IN (SELECT entity_id FROM external_link WHERE type=${idx} AND entity_type='artist')"
                    )
                params.append(filter_value)
    
    elif filter_type == "link_type":
        if filter_value:
            if filter_value == "release type":
                if category == "album":
                    where_clauses.append("""
                        mbid IN (
                            SELECT DISTINCT release_group_mbid 
                            FROM album 
                            WHERE release_type_raw != '<none>' AND release_group_mbid IS NOT NULL
                        )
                    """)
                else:
                    where_clauses.append(f"{tbl}.release_type_raw != '<none>'")
            elif filter_value == "release date":
                if category == "album":
                    where_clauses.append("""
                        mbid IN (
                            SELECT DISTINCT release_group_mbid 
                            FROM album 
                            WHERE release_date IS NOT NULL AND release_group_mbid IS NOT NULL
                        )
                    """)
                else:
                    where_clauses.append(f"{tbl}.release_date IS NOT NULL")
            else:
                idx = len(params) + 1
                if category == "album":
                    # For albums, join on release_group_mbid
                    where_clauses.append(
                        f"mbid IN (SELECT DISTINCT a.release_group_mbid FROM external_link el JOIN album a ON el.entity_id = a.release_group_mbid WHERE el.type=${idx} AND el.entity_type='album' AND a.release_group_mbid IS NOT NULL)"
                    )
                else:
                    where_clauses.append(
                        f"{tbl}.mbid IN (SELECT entity_id FROM external_link WHERE type=${idx} AND entity_type='artist')"
                    )
                params.append(filter_value)



    # Construct final SQL
    if where_clauses:
        # For albums with CTE, we already have WHERE 1=1, so use AND
        # For artists, we don't have a WHERE clause, so use WHERE
        if category == "album":
            query += " AND " + " AND ".join(where_clauses)
        else:
            query += " WHERE " + " AND ".join(where_clauses)

    if category == "album":
        # Sort by Artist Sort Name (or Name), then Album Name
        query += " ORDER BY COALESCE(sort_name, artist_name), name ASC LIMIT 500"
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
    # Count unique release groups instead of individual releases
    stats["album_stats"]["total"] = await db.fetchval(
        "SELECT COUNT(DISTINCT release_group_mbid) FROM album WHERE release_group_mbid IS NOT NULL"
    )

    # Count release groups that have at least one track with artwork
    stats["album_stats"]["with_artwork"] = await db.fetchval("""
        SELECT COUNT(DISTINCT t.release_group_mbid) 
        FROM track t
        WHERE t.release_group_mbid IS NOT NULL 
          AND t.artwork_id IS NOT NULL
    """)

    # Count external links by joining on release_group_mbid
    # External links are stored with entity_id = release_group_mbid for albums
    rows = await db.fetch("""
        SELECT el.type, COUNT(DISTINCT a.release_group_mbid) 
        FROM external_link el
        JOIN album a ON el.entity_id = a.release_group_mbid
        WHERE el.entity_type='album' AND a.release_group_mbid IS NOT NULL
        GROUP BY el.type
    """)
    for row in rows:
        stats["album_stats"]["link_stats"][row["type"]] = row["count"]

    # Add Metadata Stats (Release Type, Release Date) disguised as links for UI compatibility
    # Count PRESENT items at the release group level
    
    # Release Date Present - count release groups where at least one release has a date
    stats["album_stats"]["link_stats"]["release date"] = await db.fetchval("""
        SELECT COUNT(DISTINCT release_group_mbid) 
        FROM album 
        WHERE release_group_mbid IS NOT NULL 
          AND release_date IS NOT NULL
    """)
    
    # Release Type Present - count release groups where at least one release has a type
    stats["album_stats"]["link_stats"]["release type"] = await db.fetchval("""
        SELECT COUNT(DISTINCT release_group_mbid) 
        FROM album 
        WHERE release_group_mbid IS NOT NULL 
          AND release_type_raw != '<none>'
    """)


    return {
        "artist_stats": {"all": stats["all"], "primary": stats["primary"]},
        "album_stats": stats["album_stats"],
    }
