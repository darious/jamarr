"""Top tracks and similar artists from ListenBrainz (scanner service)."""

import pytest

from app import listenbrainz as lb
from app.scanner.services import listenbrainz as service

SEED = "a74b1b7f-71a5-4011-9441-d0b5e4122711"


def mbid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


class FakeLB:
    def __init__(self, recordings=None, ranked=None, radio=None, fail=()):
        self.recordings = recordings or []
        self.ranked = ranked or []
        self.radio = radio or {}
        self.fail = set(fail)
        self.calls = []

    async def top_recordings_for_artist(self, artist_mbid, token=None):
        self.token = token
        self.calls.append("top")
        if "top" in self.fail:
            raise lb.ListenBrainzUnavailableError("502")
        return self.recordings

    async def similar_artists(self, artist_mbid, token=None):
        self.calls.append("labs")
        if "labs" in self.fail:
            raise lb.ListenBrainzUnavailableError("labs down")
        return self.ranked

    async def radio_similar_artists(self, artist_mbid, count=10, token=None):
        self.calls.append("radio")
        if "radio" in self.fail:
            raise lb.ListenBrainzUnavailableError("radio down")
        return self.radio


@pytest.fixture
def use(monkeypatch):
    monkeypatch.setenv("LISTENBRAINZ_TOKEN", "server-token")

    def install(fake):
        monkeypatch.setattr(lb, "_client", fake)
        return fake

    return install


def rec(n, name, listens, album="Album"):
    return {"recording_mbid": mbid(n), "recording_name": name, "total_listen_count": listens, "release_name": album}


@pytest.mark.asyncio
async def test_top_tracks_rank_by_listens_one_recording_per_song(use):
    use(FakeLB(recordings=[
        rec(1, "Karma Police", 3_890_683, "OK Computer"),
        rec(2, "Karma Police (Remastered)", 50_000, "OKNOTOK"),   # same song
        rec(3, "Creep", 2_829_991, "Pablo Honey"),
        rec(4, "Creep - Acoustic", 10_000),                      # same song
        rec(5, "No Listens", 0),
        {"recording_mbid": "junk", "recording_name": "Bad MBID", "total_listen_count": 9},
    ]))
    tracks = await service.fetch_top_tracks(SEED, "Radiohead")
    assert [(t["rank"], t["name"], t["album"]) for t in tracks] == [
        (1, "Karma Police", "OK Computer"),
        (2, "Creep", "Pablo Honey"),
    ]
    assert tracks[0]["mbid"] == mbid(1)
    assert tracks[0]["popularity"] == 3_890_683


@pytest.mark.asyncio
async def test_top_tracks_cap_at_ten(use):
    use(FakeLB(recordings=[rec(i, f"Song {i}", 1000 - i) for i in range(1, 30)]))
    assert len(await service.fetch_top_tracks(SEED, "X")) == 10


@pytest.mark.asyncio
async def test_top_tracks_failure_is_empty_so_existing_data_stays(use):
    use(FakeLB(fail={"top"}))
    assert await service.fetch_top_tracks(SEED, "X") == []


@pytest.mark.asyncio
async def test_similar_artists_from_labs_ranked_without_seed(use):
    fake = use(FakeLB(ranked=[
        {"artist_mbid": SEED, "name": "Radiohead", "score": 99999},
        {"artist_mbid": mbid(1), "name": "Nirvana", "score": 11156},
        {"artist_mbid": mbid(2), "name": "Muse", "score": 5578},
    ]))
    similar = await service.fetch_similar_artists(SEED, "Radiohead")
    assert [(s["name"], s["match"]) for s in similar] == [("Nirvana", 1.0), ("Muse", 0.5)]
    assert fake.calls == ["labs"]


@pytest.mark.asyncio
async def test_similar_artists_fall_back_to_lb_radio(use):
    fake = use(FakeLB(fail={"labs"}, radio={
        SEED: [{"similar_artist_name": "Radiohead"}],
        mbid(3): [{"similar_artist_name": "The Smiths", "similar_artist_mbid": mbid(3)}],
    }))
    similar = await service.fetch_similar_artists(SEED, "Radiohead")
    assert [(s["name"], s["mbid"]) for s in similar] == [("The Smiths", mbid(3))]
    assert fake.calls == ["labs", "radio"]


@pytest.mark.asyncio
async def test_similar_artists_empty_labs_also_falls_back(use):
    fake = use(FakeLB(ranked=[{"artist_mbid": SEED, "name": "Radiohead", "score": 1}], radio={}))
    assert await service.fetch_similar_artists(SEED, "Radiohead") == []
    assert fake.calls == ["labs", "radio"]


@pytest.mark.asyncio
async def test_similar_artists_both_down_is_empty(use):
    use(FakeLB(fail={"labs", "radio"}))
    assert await service.fetch_similar_artists(SEED, "X") == []


@pytest.mark.asyncio
async def test_lookups_send_the_server_token(use):
    fake = use(FakeLB(recordings=[rec(1, "Song", 5)]))
    await service.fetch_top_tracks(SEED, "X")
    assert fake.token == "server-token"


@pytest.mark.asyncio
async def test_token_falls_back_to_a_connected_admin(db, monkeypatch):
    monkeypatch.delenv("LISTENBRAINZ_TOKEN", raising=False)
    monkeypatch.setattr(service, "_token_cache", (0.0, None))
    await db.execute(
        """
        INSERT INTO "user" (username, email, password_hash, is_admin, listenbrainz_token)
        VALUES ('plain', 'p@example.com', 'x', FALSE, 'user-token'),
               ('boss', 'b@example.com', 'x', TRUE, 'admin-token'),
               ('broken', 'k@example.com', 'x', TRUE, 'bad-token')
        """
    )
    await db.execute("""UPDATE "user" SET listenbrainz_auth_error = 'rejected' WHERE username = 'broken'""")
    assert await service.metadata_token() == "admin-token"
