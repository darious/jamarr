"""Diff classification in the matcher before/after harness."""
from scripts.match_eval.match_eval import build_subset_ids, diff_runs, render_report


def _row(sid, track_id, title="Refuge", album="The Weight of the Woods"):
    return {
        "scrobble_id": sid,
        "artist_name": "Artist",
        "track_name": "Refuge",
        "album_name": "The Weight of the Woods",
        "track_id": track_id,
        "matched_title": title if track_id else "",
        "matched_album": album if track_id else "",
    }


def test_diff_classifies_and_groups():
    a = {
        "1": _row("1", "10"),
        "2": _row("2", "10"),
        "3": _row("3", "10"),
        "4": _row("4", ""),
        "5": _row("5", "10"),
        "6": _row("6", ""),
    }
    b = {
        "1": _row("1", "10"),  # same
        "2": _row("2", "20", album="Extended"),  # moved
        "3": _row("3", "20", album="Extended"),  # moved, same group as 2
        "4": _row("4", "30"),  # gained
        "5": _row("5", ""),  # lost
        "6": _row("6", ""),  # still unmatched
        "7": _row("7", "10"),  # only in b
    }
    result = diff_runs(a, b)
    counts = result["counts"]
    assert counts["same_match"] == 1
    assert counts["same_unmatched"] == 1
    assert counts["moved"] == 2
    assert counts["gained"] == 1
    assert counts["lost"] == 1
    assert counts["missing_in_a"] == 1
    moved = result["groups"]["moved"]
    assert len(moved) == 1
    ((_key, before, after), n), = moved.items()
    assert n == 2
    assert before == "Refuge [The Weight of the Woods] #10"
    assert after == "Refuge [Extended] #20"


def test_report_shows_metric_changes():
    result = diff_runs({"1": _row("1", "10")}, {"1": _row("1", "20")})
    report = render_report(
        "before", "after",
        {"scrobbles": 1, "matched": 1, "wrong_release": 5},
        {"scrobbles": 1, "matched": 1, "wrong_release": 2},
        result, top=10,
    )
    assert "| wrong_release | 5 | 2 | -3 |" in report
    assert "## Moved to another track (1 scrobbles, 1 distinct)" in report


def test_subset_takes_flagged_moved_and_a_stable_sample():
    run_a = {"1": _row("1", "10"), "2": _row("2", "10"), "3": _row("3", "")}
    run_b = {"1": _row("1", "10"), "2": _row("2", "20"), "3": _row("3", "")}
    all_ids = list(range(1, 101))
    ids, stats = build_subset_ids([5, 7], [run_a, run_b], all_ids, sample=10, seed=1)
    assert {2, 5, 7} <= set(ids)
    assert stats == {"flagged": 2, "moved": 1, "sampled": 10, "total": 13}
    again, _ = build_subset_ids([5, 7], [run_a, run_b], all_ids, sample=10, seed=1)
    assert again == ids
