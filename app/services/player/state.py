import os
import json
import mimetypes
import asyncpg
import logging
from typing import Dict, Any, List, Optional
from app.config import get_music_path
from app.services.player.queue_model import ENTRY_KEY, ensure_entry_ids, find_entry

logger = logging.getLogger(__name__)

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
        "SELECT active_renderer_udn, active_renderer_id FROM client_session WHERE client_id = $1",
        client_id,
    )
    if row and row["active_renderer_udn"]:
        return row["active_renderer_udn"]

    # If no session found, implicitly create one for observability
    default_udn = f"local:{client_id}"
    await db.execute(
        """
        INSERT INTO client_session (client_id, active_renderer_udn, active_renderer_id, last_seen_at)
        VALUES ($1, $2, $2, NOW())
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
        SELECT queue, current_index, position_seconds, is_playing, transport_state, volume,
               queue_revision
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
            "queue_revision": 0,
        }

    queue = _decode_queue(row["queue"])

    return {
        "queue": queue,
        "current_index": row["current_index"],
        "position_seconds": row["position_seconds"],
        "is_playing": bool(row["is_playing"]),
        "transport_state": row["transport_state"] or "STOPPED",
        "volume": row["volume"],
        "queue_revision": int(row["queue_revision"] or 0),
    }


def _decode_queue(raw: Any) -> List[Dict[str, Any]]:
    """Stored queue JSON -> list of items, each with an ``entry_id``.

    Queues persisted before #325 carry none; they get deterministic ids here
    (see ``queue_model.legacy_entry_id``) so every reader agrees until the
    next full write stores them.
    """
    try:
        queue = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(queue, list):
            queue = []
    except Exception:
        queue = []
    for t in queue:
        if isinstance(t, dict):
            t.pop("art_id", None)
            t.pop("artwork_id", None)
    return ensure_entry_ids(queue)


async def update_renderer_state_db(
    db: asyncpg.Connection,
    udn: str,
    state: Dict[str, Any],
    expected_revision: Optional[int] = None,
) -> Optional[int]:
    """Upsert renderer state (all fields) and return the queue revision.

    The revision moves only when the stored queue text changes, so progress
    and index writes through here leave it alone. With ``expected_revision``
    the write is conditional: when the row has moved on, nothing is written
    and ``None`` comes back (the caller raises ``QueueConflict``). The check
    and the write are one statement, so two racing edits cannot both win.
    """
    queue_json = json.dumps(strip_art_ids(ensure_entry_ids(state.get("queue", []))))
    volume = state.get("volume")
    revision = await db.fetchval(
        """
        INSERT INTO renderer_state (renderer_udn, queue, current_index, position_seconds,
                                    is_playing, transport_state, volume, queue_revision, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, 1, NOW())
        ON CONFLICT(renderer_udn) DO UPDATE SET
            queue = excluded.queue,
            current_index = excluded.current_index,
            position_seconds = excluded.position_seconds,
            is_playing = excluded.is_playing,
            transport_state = excluded.transport_state,
            volume = excluded.volume,
            queue_revision = CASE
                WHEN renderer_state.queue IS DISTINCT FROM excluded.queue
                THEN renderer_state.queue_revision + 1
                ELSE renderer_state.queue_revision
            END,
            updated_at = NOW()
        WHERE $8::bigint IS NULL OR renderer_state.queue_revision = $8::bigint
        RETURNING queue_revision
    """,
        udn,
        queue_json,
        state.get("current_index", -1),
        state.get("position_seconds", 0),
        bool(state.get("is_playing")),
        state.get("transport_state", "STOPPED"),
        volume,
        expected_revision,
    )
    if revision is not None:
        state["queue_revision"] = int(revision)
        return int(revision)
    return None


async def update_playback_progress_db(
    db: asyncpg.Connection, udn: str, state: Dict[str, Any]
):
    """Update only progress fields — never current_index or queue.
    Safe to call concurrently from status listeners and polling.
    """
    await db.execute(
        """
        INSERT INTO renderer_state (renderer_udn, queue, current_index, position_seconds, is_playing, transport_state, volume, updated_at)
        VALUES ($1, '[]'::jsonb, 0, $2, $3, $4, $5, NOW())
        ON CONFLICT(renderer_udn) DO UPDATE SET
            position_seconds = excluded.position_seconds,
            is_playing = excluded.is_playing,
            transport_state = excluded.transport_state,
            volume = excluded.volume,
            updated_at = NOW()
    """,
        udn,
        state.get("position_seconds", 0),
        bool(state.get("is_playing")),
        state.get("transport_state", "STOPPED"),
        state.get("volume"),
    )


_STATUS_COLUMNS = ("position_seconds", "is_playing", "transport_state", "volume")


async def update_renderer_status_db(
    db: asyncpg.Connection, udn: str, **fields: Any
) -> None:
    """Write only the given status columns (``position_seconds``,
    ``is_playing``, ``transport_state``, ``volume``).

    For control handlers (pause/resume/seek/volume): a read-modify-write of
    the whole row would put back a queue read before a concurrent edit landed.
    """
    columns = [c for c in _STATUS_COLUMNS if c in fields]
    if not columns:
        return
    values = [bool(fields[c]) if c == "is_playing" else fields[c] for c in columns]
    placeholders = ", ".join(f"${n + 2}" for n in range(len(columns)))
    updates = ", ".join(f"{c} = excluded.{c}" for c in columns)
    await db.execute(
        f"""
        INSERT INTO renderer_state (renderer_udn, {", ".join(columns)}, updated_at)
        VALUES ($1, {placeholders}, NOW())
        ON CONFLICT(renderer_udn) DO UPDATE SET {updates}, updated_at = NOW()
        """,
        udn,
        *values,
    )


async def mark_entry_logged(
    db: asyncpg.Connection, udn: str, entry_id: str, attempts: int = 3
) -> bool:
    """Set ``logged`` on one queue entry without disturbing anything else.

    Re-reads the stored queue, flips the flag on the entry with ``entry_id``
    and writes the queue back only if it is still the text that was read, so
    a queue edit that landed in between is never overwritten (it is retried
    on the fresh queue instead). The revision does not move: the queue's
    membership and order are unchanged. Returns False when the entry is gone
    or the write kept losing the race.
    """
    for _ in range(attempts):
        row = await db.fetchrow(
            "SELECT queue FROM renderer_state WHERE renderer_udn = $1", udn
        )
        if not row:
            return False
        before = row["queue"]
        queue = _decode_queue(before)
        pos = find_entry(queue, entry_id)
        if pos < 0:
            return False
        if queue[pos].get("logged"):
            return True
        queue[pos]["logged"] = True
        result = await db.execute(
            """
            UPDATE renderer_state SET queue = $2, updated_at = NOW()
            WHERE renderer_udn = $1 AND queue = $3
            """,
            udn,
            json.dumps(strip_art_ids(queue)),
            before,
        )
        if result.rsplit(" ", 1)[-1] == "1":
            return True
    logger.warning("Could not mark %s logged on %s: queue kept changing", entry_id, udn)
    return False


def entry_id_of(item: Any) -> Optional[str]:
    """The entry id of a queue item, when it is one."""
    if isinstance(item, dict):
        value = item.get(ENTRY_KEY)
        return value if isinstance(value, str) and value else None
    return None
