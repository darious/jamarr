"""Last.fm scrobble -> library track matching.

Regression: every track of Pearl Jam's "Ten Redux" scrobbled from Jamarr came
back from the Last.fm sync matched to track 1, "Once (2008 Brendan O'Brien
mix)". Artist + album + album artist + release type already hit the 1.0 score
cap, the shared "(2008 Brendan O'Brien Mix)" suffix carried the fuzzy title
check, and the tie-break never preferred the exact title, so the first
candidate won.
"""

from collections import defaultdict

from app.matching import base_title, base_titles_compatible, score_candidate
from app.matching.matcher import match_scrobble

ARTIST_MBID = "pearl-jam-mbid"


def scrobble(track_name, album_name="Ten Redux", artist_name="Pearl Jam", track_mbid=None):
    return {
        "track_mbid": track_mbid,
        "artist_mbid": None,
        "album_mbid": None,
        "artist_name": artist_name,
        "track_name": track_name,
        "album_name": album_name,
    }


def track(
    track_id,
    title,
    album="Ten Redux",
    artist="Pearl Jam",
    track_mbid=None,
    album_artist=None,
    release_type="album",
):
    return {
        "id": track_id,
        "track_mbid": track_mbid,
        "artist_mbid": ARTIST_MBID,
        "release_mbid": None,
        "artist": artist,
        "artist_names": [artist],
        "title": title,
        "album": album,
        "album_artist": album_artist or artist,
        "release_type": release_type,
    }


TEN_REDUX = [
    track(188661, "Once (2008 Brendan O’Brien mix)"),
    track(188694, "Even Flow (2008 Brendan O’Brien mix)"),
    track(188735, "Jeremy (2008 Brendan O’Brien mix)"),
    track(188789, "Deep (2008 Brendan O’Brien mix)"),
]


def match(sc, tracks):
    """Run the matcher with every track reachable through the artist's MBID,
    which is how the whole album lands in the candidate list on prod."""
    indexes = defaultdict(dict)
    indexes["artist_mbid"][ARTIST_MBID] = list(tracks)
    return match_scrobble(
        sc,
        indexes,
        artist_lookup={"pearl jam": ARTIST_MBID},
        artist_volume={},
        skip_artists=set(),
    )


# --- base_title ------------------------------------------------------------


def test_base_title_drops_bracketed_parts():
    assert base_title("Deep (2008 Brendan O’Brien Mix)") == "deep"
    assert base_title("All Too Well (10 minute version) (Taylor’s version) [Vault]") == "all too well"


def test_base_title_drops_truncated_bracket():
    assert base_title("1000 Mirrors (Feat. Sinead O'c") == "1000 mirrors"


def test_base_title_empty_when_everything_is_bracketed():
    assert base_title("(Intro)") == ""
    assert base_titles_compatible("(Intro)", "Anything")


def test_base_titles_compatible():
    assert not base_titles_compatible("Deep (2008 Mix)", "Once (2008 Mix)")
    assert not base_titles_compatible("Ours (Taylor’s Version)", "Mine (Taylor’s version)")
    assert base_titles_compatible("Rearviewmirror (Live)", "Rear View Mirror (Live)")


# --- score_candidate ------------------------------------------------------------


def test_shared_suffix_is_not_a_fuzzy_title_match():
    score, reason, _, _ = score_candidate(
        scrobble("Deep (2008 Brendan O’Brien Mix)"), TEN_REDUX[0]
    )
    assert "fuzzy_title" not in reason
    assert "track_name" not in reason
    assert score <= 0.6


def test_fuzzy_title_scores_below_exact_title():
    sc = scrobble("Nothing New (Taylor’s Version)", album_name="Red", artist_name="Taylor Swift")
    exact = track(1, "Nothing New (Taylor’s Version)", album="Red", artist="Taylor Swift")
    fuzzy = track(2, "Nothing New (Taylor’s version) (from The Vault)", album="Red", artist="Taylor Swift")

    exact_score, exact_reason, _, _ = score_candidate(sc, exact)
    fuzzy_score, fuzzy_reason, _, _ = score_candidate(sc, fuzzy)

    assert "track_name" in exact_reason
    assert "fuzzy_title" in fuzzy_reason
    assert exact_score == 1.0
    assert fuzzy_score < exact_score


def test_track_mbid_match_skips_base_title_gate():
    sc = scrobble("Deep (2008 Brendan O’Brien Mix)", track_mbid="rec-1")
    cand = track(1, "Once (2008 Brendan O’Brien mix)", track_mbid="rec-1")
    _, reason, _, _ = score_candidate(sc, cand)
    assert "fuzzy_title" in reason
    assert "mbid_title_mismatch" not in reason


# --- match_scrobble ------------------------------------------------------------


def test_each_ten_redux_track_matches_itself():
    for expected in TEN_REDUX:
        title = expected["title"].replace("mix)", "Mix)")  # Last.fm's casing
        track_id, score, method, reason = match(scrobble(title), TEN_REDUX)
        assert track_id == expected["id"], (title, reason)
        assert "track_name" in reason
        assert method == "name_artist_album"
        assert score == 1.0


def test_exact_title_wins_a_tie_against_a_better_method():
    """Both score 0.9: the fuzzy candidate is on the scrobbled album
    (name_artist_album), the exact one is not (name_artist_title). The old
    tie-break preferred the higher method rank; the exact title must win."""
    sc = scrobble("Nothing New (Taylor’s Version)", album_name="Red", artist_name="Taylor Swift")
    common = dict(artist="Taylor Swift", album_artist="Someone Else", release_type=None)
    fuzzy = track(2, "Nothing New (Taylor’s version) (from The Vault)", album="Red", **common)
    exact = track(1, "Nothing New (Taylor’s Version)", album="Other", **common)
    assert score_candidate(sc, fuzzy)[0] == score_candidate(sc, exact)[0]

    indexes = defaultdict(dict)
    indexes["artist_mbid"][ARTIST_MBID] = [fuzzy, exact]
    track_id, _, method, reason = match_scrobble(
        sc, indexes, {"taylor swift": ARTIST_MBID}, {}, set()
    )
    assert track_id == 1
    assert method == "name_artist_title"
    assert "track_name" in reason


def test_missing_track_does_not_fall_back_to_a_sibling():
    """Release isn't in the library: nothing matches, rather than Once."""
    assert match(scrobble("Release (2008 Brendan O’Brien Mix)"), TEN_REDUX) is None


def test_fallback_fuzzy_path_respects_base_title():
    """"Mind" vs "Mine (Taylor's version)" clears the fallback's 92 whole-title
    ratio; the base titles differ, so it must not match."""
    sc = scrobble("Mind (Taylor’s Version)", album_name="Speak Now", artist_name="Taylor Swift")
    mine = track(1, "Mine (Taylor’s version)", album="Speak Now", artist="Taylor Swift")
    indexes = defaultdict(dict)
    indexes["artist_mbid"][ARTIST_MBID] = [mine]
    assert match_scrobble(sc, indexes, {"taylor swift": ARTIST_MBID}, {}, set()) is None


def test_genuine_fuzzy_title_still_matches():
    sc = scrobble("Rearviewmirror", album_name="Vs.")
    cand = track(7, "Rear View Mirror", album="Vs.")
    track_id, score, method, _ = match(sc, [cand])
    assert track_id == 7
    assert method == "fuzzy_title"
    assert score == 0.6
