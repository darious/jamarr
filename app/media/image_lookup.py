import itertools
from typing import Dict, Iterable, Optional

from aiosqlite import Connection

async def fetch_primary_images(
    db: Connection,
    entity_type: str,
    entity_ids: Iterable[str],
    image_type: str,
) -> Dict[str, Dict[str, Optional[str]]]:
    """
    Fetch primary artwork mapping for a set of entities.
    Returns a dict of entity_id -> {art_id, art_sha1, source, source_url}.
    """
    ids = [str(e) for e in entity_ids if e]
    if not ids:
        return {}

    placeholders = ",".join("?" * len(ids))
    query = f"""
        SELECT im.entity_id, im.artwork_id, im.score, aw.sha1, aw.source, aw.source_url
        FROM image_mapping im
        JOIN artwork aw ON aw.id = im.artwork_id
        WHERE im.entity_type = ? AND im.image_type = ? AND im.entity_id IN ({placeholders})
        ORDER BY im.entity_id, COALESCE(im.score, 0) DESC, im.created_at DESC
    """
    params = [entity_type, image_type, *ids]

    results: Dict[str, Dict[str, Optional[str]]] = {}
    async with db.execute(query, params) as cursor:
        rows = await cursor.fetchall()
        for row in rows:
            entity_id = row["entity_id"]
            # First row per entity (ordered by score/created_at) is primary
            if entity_id not in results:
                results[entity_id] = {
                    "art_id": row["artwork_id"],
                    "art_sha1": row["sha1"],
                    "source": row["source"],
                    "source_url": row["source_url"],
                }

    return results
