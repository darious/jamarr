import os
import json
import mimetypes
import asyncpg
from typing import Dict, Any, List
from app.config import get_music_path

def track_path_exists(track: Dict[str, Any]) -> bool:
    path = track.get("path")
    if not path:
        return False
    abs_path = path
    if not os.path.isabs(abs_path):
        abs_path = os.path.join(get_music_path(), abs_path)
    return os.path.exists(abs_path)


async def enrich_track_metadata(
    track: Dict[str, Any], db: asyncpg.Connection
) -> Dict[str, Any]:
    """Ensure track dict has path, mime, and artwork; fallback to DB lookup."""
    enriched = dict(track)
    # Always fetch missing critical fields including artists
    if (
        not enriched.get("path")
        or not enriched.get("mime")
        or not enriched.get("art_sha1")
        or enriched.get("artists") is None
    ):
        row = await db.fetchrow(
            """
            WITH track_artists AS (
                SELECT 
                    ta.track_id, 
                    jsonb_agg(jsonb_build_object('name', a.name, 'mbid', a.mbid)) as artists
                FROM track_artist ta
                JOIN artist a ON ta.artist_mbid = a.mbid
                WHERE ta.track_id = $1
                GROUP BY ta.track_id
            )
            SELECT t.path, t.codec, t.artwork_id, a.sha1 as art_sha1,
                   COALESCE(ta.artists, '[]'::jsonb) as artists
            FROM track t
            LEFT JOIN artwork a ON t.artwork_id = a.id
            LEFT JOIN track_artists ta ON t.id = ta.track_id
            WHERE t.id = $1 LIMIT 1
            """,
            enriched.get("id"),
        )
        if row:
            if not enriched.get("path"):
                enriched["path"] = row[0]
            if not enriched.get("art_sha1"):
                enriched["art_sha1"] = row[3]
                if not enriched.get("mime"):
                    mime, _ = mimetypes.guess_type(row[0])
                    if not mime:
                        ext = os.path.splitext(row[0])[1].lower()
                        if ext == ".flac":
                            mime = "audio/flac"
                        elif ext == ".mp3":
                            mime = "audio/mpeg"
                        elif ext == ".m4a":
                            mime = "audio/mp4"
                        elif ext == ".wav":
                            mime = "audio/wav"
                        elif ext == ".ogg":
                            mime = "audio/ogg"
                        else:
                            mime = "audio/flac"
                    enriched["mime"] = mime
            
            if enriched.get("artists") is None:
                artists_val = row[4]
                if isinstance(artists_val, str):
                    artists_val = json.loads(artists_val)
                enriched["artists"] = artists_val

    return enriched


def strip_art_ids(queue: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ensure renderer_state queues never persist art_id/artwork_id."""
    cleaned = []
    for item in queue:
        if not isinstance(item, dict):
            cleaned.append(item)
            continue
        item.pop("art_id", None)
        item.pop("artwork_id", None)
        cleaned.append(item)
    return cleaned


async def get_active_renderer(db: asyncpg.Connection, client_id: str) -> str:
    """Get active renderer UDN for client. Defaults to local:<client_id>."""
    row = await db.fetchrow(
        "SELECT active_renderer_udn FROM client_session WHERE client_id = $1", client_id
    )
    if row and row[0]:
        return row[0]

    # If no session found, implicitly create one for observability
    default_udn = f"local:{client_id}"
    await db.execute(
        """
        INSERT INTO client_session (client_id, active_renderer_udn, last_seen_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (client_id) DO NOTHING
    """,
        client_id,
        default_udn,
    )

    return default_udn


async def get_renderer_state_db(db: asyncpg.Connection, udn: str) -> Dict[str, Any]:
    """Get state from DB for a renderer. Returns default if not found."""
    row = await db.fetchrow(
        """
        SELECT queue, current_index, position_seconds, is_playing, transport_state, volume
        FROM renderer_state
        WHERE renderer_udn = $1
        """,
        udn,
    )
    if not row:
        return {
            "queue": [],
            "current_index": -1,
            "position_seconds": 0,
            "is_playing": False,
            "transport_state": "STOPPED",
            "volume": None,
        }

    try:
        queue = json.loads(row[0])
        if not isinstance(queue, list):
            queue = []
    except Exception:
        queue = []

    for t in queue:
        t.pop("art_id", None)
        t.pop("artwork_id", None)

    return {
        "queue": queue,
        "current_index": row[1],
        "position_seconds": row[2],
        "is_playing": bool(row[3]),
        "transport_state": row[4] if len(row) > 4 else "STOPPED",
        "volume": row[5] if len(row) > 5 else None,
    }


async def update_renderer_state_db(
    db: asyncpg.Connection, udn: str, state: Dict[str, Any]
):
    """Upsert renderer state."""
    queue_json = json.dumps(strip_art_ids(state.get("queue", [])))
    volume = state.get("volume")
    await db.execute(
        """
        INSERT INTO renderer_state (renderer_udn, queue, current_index, position_seconds, is_playing, transport_state, volume, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
        ON CONFLICT(renderer_udn) DO UPDATE SET
            queue = excluded.queue,
            current_index = excluded.current_index,
            position_seconds = excluded.position_seconds,
            is_playing = excluded.is_playing,
            transport_state = excluded.transport_state,
            volume = excluded.volume,
            updated_at = NOW()
    """,
        udn,
        queue_json,
        state.get("current_index", -1),
        state.get("position_seconds", 0),
        bool(state.get("is_playing")),
        state.get("transport_state", "STOPPED"),
        volume,
    )
