"""Queue entry identity, pure (#325)."""

from app.services.player.queue_model import (
    ENTRY_KEY,
    ensure_entry_ids,
    fresh_entries,
    legacy_entry_id,
    reorder,
)


def item(track_id, entry_id=None):
    out = {"id": track_id, "title": f"t{track_id}"}
    if entry_id:
        out[ENTRY_KEY] = entry_id
    return out


def test_fresh_entries_ignore_client_ids_and_are_unique():
    out = fresh_entries([item(1, "forged"), item(1, "forged"), item(2)])
    ids = [t[ENTRY_KEY] for t in out]
    assert "forged" not in ids
    assert len(set(ids)) == 3
    assert [t["id"] for t in out] == [1, 1, 2]


def test_ensure_entry_ids_is_deterministic_for_legacy_queues():
    first = ensure_entry_ids([item(10), item(11), item(10)])
    second = ensure_entry_ids([item(10), item(11), item(10)])
    assert [t[ENTRY_KEY] for t in first] == [t[ENTRY_KEY] for t in second]
    assert first[0][ENTRY_KEY] == legacy_entry_id(0, 10)
    assert first[2][ENTRY_KEY] == legacy_entry_id(2, 10)
    assert len({t[ENTRY_KEY] for t in first}) == 3


def test_ensure_entry_ids_keeps_existing_and_breaks_duplicates():
    q = [item(1, "a"), item(2, "a"), item(3, "c")]
    ensure_entry_ids(q)
    assert q[0][ENTRY_KEY] == "a"
    assert q[1][ENTRY_KEY] != "a"
    assert q[2][ENTRY_KEY] == "c"


def test_reorder_duplicate_track_keeps_the_playing_occurrence():
    # [A, B, A] with the last A playing; move it to the front.
    existing = [item(1, "a1"), item(2, "b"), item(1, "a2")]
    incoming = [item(1, "a2"), item(1, "a1"), item(2, "b")]
    rebuilt, idx = reorder(existing, incoming, current_index=2)
    assert [t[ENTRY_KEY] for t in rebuilt] == ["a2", "a1", "b"]
    assert idx == 0
    assert rebuilt[0] is existing[2]


def test_reorder_removes_one_duplicate_and_leaves_the_other():
    existing = [item(1, "a1"), item(2, "b"), item(1, "a2")]
    rebuilt, idx = reorder(existing, [item(2, "b"), item(1, "a2")], current_index=2)
    assert [t[ENTRY_KEY] for t in rebuilt] == ["b", "a2"]
    assert idx == 1


def test_reorder_removing_the_current_entry_reports_minus_one():
    existing = [item(1, "a1"), item(2, "b")]
    rebuilt, idx = reorder(existing, [item(2, "b")], current_index=0)
    assert [t[ENTRY_KEY] for t in rebuilt] == ["b"]
    assert idx == -1


def test_reorder_without_entry_ids_falls_back_to_first_unused_track_id():
    # An older client echoes track ids only: still a valid reorder.
    existing = [item(1, "a1"), item(2, "b"), item(1, "a2")]
    rebuilt, idx = reorder(existing, [item(2), item(1), item(1)], current_index=1)
    assert [t[ENTRY_KEY] for t in rebuilt] == ["b", "a1", "a2"]
    assert idx == 0


def test_reorder_unknown_items_become_new_occurrences():
    existing = [item(1, "a1")]
    rebuilt, idx = reorder(existing, [item(9, "nope"), item(1, "a1")], current_index=0)
    assert rebuilt[0]["id"] == 9
    assert rebuilt[0][ENTRY_KEY] != "nope"
    assert rebuilt[1] is existing[0]
    assert idx == 1


def test_reorder_entry_id_wins_over_track_id():
    # Two occurrences of track 1; the client names the second explicitly.
    existing = [item(1, "a1"), item(1, "a2")]
    rebuilt, _ = reorder(existing, [item(1, "a2")], current_index=-1)
    assert [t[ENTRY_KEY] for t in rebuilt] == ["a2"]
