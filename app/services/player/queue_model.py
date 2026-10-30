"""Queue entry identity and revision semantics (#325, #332).

A queue item is a track *occurrence*: the same library track can sit in a
queue twice, so edits cannot be matched by track id. Every item carries an
``entry_id`` the server assigns when the item enters a queue and keeps across
reorder, persistence and clients. The queue as a whole carries a
``queue_revision`` that moves whenever its content (membership or order)
changes, so a client can say which queue its edit was made against.

Pure functions only; the DB side is in ``state.py``.
"""

from __future__ import annotations

import secrets
from typing import Any

ENTRY_KEY = "entry_id"


def new_entry_id() -> str:
    """Opaque, short, unique enough within one queue (and across restarts)."""
    return secrets.token_hex(6)


def legacy_entry_id(index: int, track_id: Any) -> str:
    """Identity for an item persisted before entry ids existed.

    Deterministic in position and track, so two reads of the same stored
    queue agree, and a client that read the queue can still address it. It is
    written back by the next full write and never regenerated afterwards.
    """
    return f"legacy-{index}-{track_id}"


def ensure_entry_ids(queue: list[Any]) -> list[Any]:
    """Give every dict item a unique ``entry_id`` in place.

    Items that already have one keep it, except duplicates (a client echoing
    the same id twice), which get fresh ids after the first.
    """
    seen: set[str] = set()
    for index, item in enumerate(queue):
        if not isinstance(item, dict):
            continue
        entry_id = item.get(ENTRY_KEY)
        if not isinstance(entry_id, str) or not entry_id or entry_id in seen:
            entry_id = legacy_entry_id(index, item.get("id"))
            if entry_id in seen:
                entry_id = new_entry_id()
            item[ENTRY_KEY] = entry_id
        seen.add(entry_id)
    return queue


def fresh_entries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """New occurrences: every item gets a new id, whatever the client sent.

    Used when tracks enter a queue (set, append, play). Client-supplied ids
    are ignored so one client cannot forge another entry's identity.
    """
    out: list[dict[str, Any]] = []
    for item in items:
        copy = dict(item)
        copy[ENTRY_KEY] = new_entry_id()
        out.append(copy)
    return out


def reorder(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    current_index: int,
) -> tuple[list[dict[str, Any]], int]:
    """Rebuild ``existing`` in the order ``incoming`` lists it.

    Items are matched by ``entry_id`` first. Items without one (older
    clients) fall back to the first unused occurrence of the same track id,
    which is the pre-#325 behaviour and is only ambiguous for duplicates.
    Items matching nothing are new occurrences and get fresh ids; existing
    items left out of ``incoming`` are removed.

    Returns the new queue and the new index of the entry that was current,
    or -1 when it was removed.
    """
    by_entry: dict[str, int] = {}
    by_track: dict[Any, list[int]] = {}
    for pos, item in enumerate(existing):
        entry_id = item.get(ENTRY_KEY)
        if isinstance(entry_id, str):
            by_entry.setdefault(entry_id, pos)
        by_track.setdefault(item.get("id"), []).append(pos)

    current_entry = (
        existing[current_index].get(ENTRY_KEY)
        if 0 <= current_index < len(existing)
        else None
    )

    used: set[int] = set()
    rebuilt: list[dict[str, Any]] = []
    for item in incoming:
        pos: int | None = None
        entry_id = item.get(ENTRY_KEY)
        if isinstance(entry_id, str) and entry_id in by_entry and by_entry[entry_id] not in used:
            pos = by_entry[entry_id]
        elif not entry_id:
            for candidate in by_track.get(item.get("id"), []):
                if candidate not in used:
                    pos = candidate
                    break
        if pos is None:
            fresh = dict(item)
            fresh[ENTRY_KEY] = new_entry_id()
            rebuilt.append(fresh)
            continue
        used.add(pos)
        rebuilt.append(existing[pos])

    new_index = -1
    if current_entry is not None:
        for pos, item in enumerate(rebuilt):
            if item.get(ENTRY_KEY) == current_entry:
                new_index = pos
                break
    return rebuilt, new_index


def find_entry(queue: list[Any], entry_id: str) -> int:
    """Index of the item with ``entry_id``, or -1."""
    for pos, item in enumerate(queue):
        if isinstance(item, dict) and item.get(ENTRY_KEY) == entry_id:
            return pos
    return -1


class QueueConflict(Exception):
    """A queue edit named a revision that is no longer current.

    Carries what the client needs to recover: the live revision and state,
    so it can refresh and reapply its operation against the queue as it is.
    """

    def __init__(self, expected: int, state: dict[str, Any]) -> None:
        self.expected = expected
        self.state = state
        self.revision = int(state.get("queue_revision") or 0)
        super().__init__(
            f"queue revision {expected} is stale; the queue is at {self.revision}"
        )


def state_payload(state: dict[str, Any], renderer: str) -> dict[str, Any]:
    """The queue state as every mutation answers it (and as 409 carries it)."""
    return {
        "queue": state.get("queue") or [],
        "current_index": state.get("current_index", -1),
        "queue_revision": int(state.get("queue_revision") or 0),
        "position_seconds": state.get("position_seconds", 0),
        "is_playing": state.get("is_playing", False),
        "transport_state": state.get("transport_state", "STOPPED"),
        "renderer": renderer,
        "volume": state.get("volume"),
    }
