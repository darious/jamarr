"""Last.fm matcher regressions found with scripts/match_eval (issue #366).

The xfail(strict=True) cases are known bugs, not yet fixed: each describes
the right answer and fails today. When a fix makes one pass, strict mode
turns it into a failure, so the marker has to come off with the fix.
"""

from collections import defaultdict
from itertools import permutations

import pytest

from app.matching import build_cache_key, normalize_artist, normalize_title
from app.matching.matcher import match_scrobble

KNOWN_BUG = "issue #366"


def scrobble(track_name, artist_name, album_name="", album_mbid=None):
    return {
        "track_mbid": None,
        "artist_mbid": None,
        "album_mbid": album_mbid,
        "artist_name": artist_name,
        "track_name": track_name,
        "album_name": album_name,
    }


def track(track_id, title, artist, album, release_mbid=None, release_type="album"):
    return {
        "id": track_id,
        "track_mbid": None,
        "artist_mbid": f"mbid:{artist}",
        "release_mbid": release_mbid,
        "artist": artist,
        "artist_names": [artist],
        "title": title,
        "album": album,
        "album_artist": artist,
        "release_type": release_type,
    }


def indexes_for(tracks):
    """Index the tracks the way preload_tracks does for name lookups: by
    artist MBID, by (artist, title) and by artist, all under the artist's
    full normalised name."""
    indexes = defaultdict(dict)
    for t in tracks:
        artist = normalize_artist(t["artist"])
        indexes["artist_mbid"].setdefault(t["artist_mbid"], []).append(t)
        indexes["artist_title"].setdefault((artist, normalize_title(t["title"])), []).append(t)
        indexes["artist"].setdefault(artist, []).append(t)
    return indexes


def match(sc, tracks):
    lookup = {normalize_artist(t["artist"]): t["artist_mbid"] for t in tracks}
    result = match_scrobble(
        sc, indexes_for(tracks), artist_lookup=lookup, artist_volume={}, skip_artists=set()
    )
    return result[0] if result else None


# --- order independence ----------------------------------------------------


def test_complete_tie_goes_to_the_lowest_track_id_in_any_order():
    # Two copies of one album in the library, identical in every field.
    copies = [
        track(3888, "Chocolate", "The 1975", "The 1975 (deluxe edition)"),
        track(3800, "Chocolate", "The 1975", "The 1975 (deluxe edition)"),
        track(3950, "Chocolate", "The 1975", "The 1975 (deluxe edition)"),
    ]
    sc = scrobble("Chocolate", "The 1975", "The 1975 (deluxe edition)")
    assert {match(sc, list(order)) for order in permutations(copies)} == {3800}


def test_result_does_not_depend_on_candidate_order():
    tracks = [
        track(10, "Pompeii", "Bastille", "Bad Blood"),
        track(11, "Pompeii", "Bastille", "All This Bad Blood"),
        track(12, "Pompeii", "Bastille", "Greatest Hits", release_type="compilation"),
        track(13, "Pompeii (Live)", "Bastille", "Live at the Hall", release_type="live"),
    ]
    for album in ("Bad Blood", "All This Bad Blood", ""):
        sc = scrobble("Pompeii", "Bastille", album)
        results = {match(sc, list(order)) for order in permutations(tracks)}
        assert len(results) == 1, (album, results)


def test_album_mbid_picks_its_own_edition():
    # Passes today: on its own the scorer gets this right. Prod got it wrong
    # through the cache (see tests/integration/test_lastfm_match_and_store.py).
    tracks = [
        track(245347, "Refuge", "Dermot Kennedy", "The Weight of the Woods (Extended)", release_mbid="ext"),
        track(241976, "Refuge", "Dermot Kennedy", "The Weight of the Woods", release_mbid="og"),
    ]
    sc = scrobble("Refuge", "Dermot Kennedy", "The Weight of the Woods", album_mbid="og")
    assert match(sc, tracks) == 241976


def test_plain_scrobble_beats_a_lower_id_acoustic_bonus_track():
    # Back to Bedlam's acoustic bonus tracks have lower ids than the album
    # versions; a lowest-id tie-break alone moved 79 "Goodbye My Lover" plays.
    tracks = [
        track(13211, "Goodbye My Lover (acoustic version)", "James Blunt", "Back to Bedlam"),
        track(13226, "Goodbye My Lover", "James Blunt", "Back to Bedlam"),
    ]
    sc = scrobble("Goodbye My Lover", "James Blunt", "Back to Bedlam")
    assert match(sc, tracks) == 13226


# --- cache key ------------------------------------------------------------


def _keyed(track_name, album_name="", album_mbid=None, track_mbid=None, artist="Dermot Kennedy"):
    sc = scrobble(track_name, artist, album_name, album_mbid)
    sc["track_mbid"] = track_mbid
    return build_cache_key(sc)


def test_cache_key_separates_editions_with_one_track_mbid():
    og = _keyed("Refuge", "The Weight of the Woods", "og", track_mbid="t")
    ext = _keyed("Refuge", "The Weight of the Woods (Extended)", "ext", track_mbid="t")
    assert og != ext


def test_cache_key_falls_back_to_the_album_name():
    assert _keyed("Refuge", "The Weight of the Woods", track_mbid="t") != _keyed(
        "Refuge", "The Weight of the Woods (Extended)", track_mbid="t"
    )


def test_cache_key_keeps_version_labels():
    album = "The Weight of the Woods (Extended)"
    assert _keyed("Funeral", album) != _keyed("Funeral (Acoustic)", album)


def test_cache_key_ignores_case_spacing_and_apostrophes():
    assert _keyed("Don’t  Forget", "Sonder") == _keyed("don't forget", "SONDER")


def test_cache_key_needs_an_mbid_or_artist_and_title():
    assert _keyed("", "Sonder", artist="") is None
    assert _keyed("Refuge", artist="") is None


# --- artist names ------------------------------------------------------------


def test_duo_credit_still_matches_each_artist():
    # The full-name lookup must not stop a split credit finding its parts.
    tracks = [track(1, "Under Pressure", "Queen", "Hot Space")]
    assert match(scrobble("Under Pressure", "Queen & David Bowie"), tracks) == 1


def test_single_name_artist_without_album_matches():
    tracks = [track(1, "Home", "Phillip Phillips", "The World from the Side of the Moon")]
    assert match(scrobble("Home", "Phillip Phillips"), tracks) == 1


@pytest.mark.parametrize(
    "artist", ["Of Monsters and Men", "Mumford & Sons", "Iron & Wine", "Christine and the Queens"]
)
def test_band_name_with_and_matches_without_album(artist):
    tracks = [track(1, "Little Talks", artist, "My Head Is an Animal")]
    assert match(scrobble("Little Talks", artist), tracks) == 1


# --- known bugs ---


@pytest.mark.xfail(strict=True, reason=f"{KNOWN_BUG}: '(Live)' is stripped, so the studio track wins")
def test_live_scrobble_matches_the_live_track():
    tracks = [
        track(1, "Chasing Cars", "Snow Patrol", "Eyes Open"),
        track(2, "Chasing Cars (Live)", "Snow Patrol", "Live at Somewhere", release_type="live"),
    ]
    assert match(scrobble("Chasing Cars (Live)", "Snow Patrol"), tracks) == 2


def test_acoustic_scrobble_matches_the_acoustic_track_on_the_same_album():
    # Studio and acoustic tie on every scoring rule, because normalize_title
    # strips "(Acoustic)"; the raw-title tie-break settles it.
    album = "The Weight of the Woods (Extended)"
    tracks = [
        track(1, "Funeral", "Dermot Kennedy", album),
        track(2, "Funeral (acoustic)", "Dermot Kennedy", album),
    ]
    assert match(scrobble("Funeral (Acoustic)", "Dermot Kennedy", album), tracks) == 2


def test_studio_scrobble_still_matches_the_studio_track():
    # Guard for the two fixes above: they must not push studio plays onto
    # the live or acoustic version.
    album = "The Weight of the Woods (Extended)"
    tracks = [
        track(1, "Funeral", "Dermot Kennedy", album),
        track(2, "Funeral (acoustic)", "Dermot Kennedy", album),
    ]
    assert match(scrobble("Funeral", "Dermot Kennedy", album), tracks) == 1
