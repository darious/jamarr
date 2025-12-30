import os
from typing import List

import pytest
from unittest.mock import AsyncMock

from app.scanner.scan_manager import ScanManager
from app.scanner.services import coordinator as coordinator_module


def _write_wav(path: os.PathLike):
    import wave
    import struct

    path = str(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(b"".join(struct.pack("<h", 0) for _ in range(200)))


async def _truncate(db):
    await db.execute(
        """
        TRUNCATE TABLE 
            session,
            client_session,
            renderer_state,
            playback_history,
            track,
            artist,
            album,
            missing_album,
            artwork,
            renderer,
            top_track,
            similar_artist,
            artist_genre,
            external_link,
            image_map,
            track_artist,
            artist_album
        RESTART IDENTITY CASCADE;
        """
    )


@pytest.mark.asyncio
async def test_filesystem_only_skips_missing_mbids(tmp_path, monkeypatch, db):
    music_root = tmp_path / "music"
    file_path = music_root / "Artist" / "Album" / "song.wav"
    _write_wav(file_path)

    monkeypatch.setattr("app.scanner.core.get_music_path", lambda: str(music_root))
    monkeypatch.setattr("app.scanner.scan_manager.get_music_path", lambda: str(music_root))
    monkeypatch.setattr("app.scanner.core.extract_tags", lambda _p: {"title": "No IDs"})
    monkeypatch.setattr("app.scanner.core.extract_and_save_artwork", AsyncMock(return_value=None))

    await _truncate(db)
    monkeypatch.setattr(ScanManager, "_instance", None, raising=False)
    mgr = ScanManager.get_instance()
    task = await mgr.start_scan(path=str(music_root), force=False)
    await task

    assert await db.fetchval("SELECT COUNT(*) FROM track") == 0


@pytest.mark.asyncio
async def test_force_rescan_wipes_existing_records(tmp_path, monkeypatch, db):
    music_root = tmp_path / "music"
    file_path = music_root / "Artist" / "Album" / "song.wav"
    _write_wav(file_path)
    rel_path = os.path.relpath(file_path, music_root)

    monkeypatch.setattr("app.scanner.core.get_music_path", lambda: str(music_root))
    monkeypatch.setattr("app.scanner.scan_manager.get_music_path", lambda: str(music_root))
    monkeypatch.setattr(
        "app.scanner.core.extract_tags",
        lambda _p: {
            "title": "Scanned Title",
            "artist": "Artist",
            "album": "Album",
            "album_artist": "Artist",
            "artist_mbid": "artist-1",
            "release_group_mbid": "rg-1",
        },
    )
    monkeypatch.setattr("app.scanner.core.extract_and_save_artwork", AsyncMock(return_value=None))

    await _truncate(db)
    # Seed stale rows
    await db.execute("INSERT INTO artist (mbid, name) VALUES ($1, $2)", "stale-mbid", "Stale Artist")
    await db.execute(
        "INSERT INTO track (path, title, artist, album, artist_mbid, release_group_mbid) VALUES ($1,$2,$3,$4,$5,$6)",
        "stale/old.wav",
        "Old",
        "Old A",
        "Old Al",
        "stale-mbid",
        "rg-stale",
    )

    monkeypatch.setattr(ScanManager, "_instance", None, raising=False)
    mgr = ScanManager.get_instance()
    task = await mgr.start_scan(path=str(music_root), force=True)
    await task

    paths = await db.fetch("SELECT path FROM track ORDER BY path")
    assert [r["path"] for r in paths] == [rel_path]
    # Stale track should be removed even if artist remains
    assert await db.fetchval("SELECT COUNT(*) FROM track WHERE path='stale/old.wav'") == 0


@pytest.mark.asyncio
async def test_prune_removes_orphans(tmp_path, monkeypatch, db):
    music_root = tmp_path / "music"
    monkeypatch.setattr("app.scanner.scan_manager.get_music_path", lambda: str(music_root))

    await _truncate(db)
    await db.execute("INSERT INTO artist (mbid, name) VALUES ($1, $2)", "orphan-mbid", "Orphan Artist")
    await db.execute("INSERT INTO album (mbid, title) VALUES ($1,$2)", "orphan-alb", "Orphan Album")

    monkeypatch.setattr(ScanManager, "_instance", None, raising=False)
    mgr = ScanManager.get_instance()
    task = await mgr.start_prune()
    await task

    assert await db.fetchval("SELECT COUNT(*) FROM artist") == 0
    assert await db.fetchval("SELECT COUNT(*) FROM album") == 0


@pytest.mark.asyncio
async def test_quick_hash_backfill(tmp_path, monkeypatch, db):
    music_root = tmp_path / "music"
    file_path = music_root / "Artist" / "Album" / "song.wav"
    _write_wav(file_path)
    rel_path = os.path.relpath(file_path, music_root)
    stat = file_path.stat()

    monkeypatch.setattr("app.scanner.core.get_music_path", lambda: str(music_root))
    monkeypatch.setattr("app.scanner.scan_manager.get_music_path", lambda: str(music_root))
    monkeypatch.setattr(
        "app.scanner.core.extract_tags",
        lambda _p: {
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "album_artist": "Artist",
            "artist_mbid": "artist-1",
            "release_group_mbid": "rg-1",
        },
    )
    monkeypatch.setattr("app.scanner.core.extract_and_save_artwork", AsyncMock(return_value=None))

    await _truncate(db)
    await db.execute(
        """
        INSERT INTO track (path, title, artist, album, artist_mbid, release_group_mbid, mtime, size_bytes, quick_hash)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,NULL)
        """,
        rel_path,
        "Old Title",
        "Artist",
        "Album",
        "artist-1",
        "rg-1",
        stat.st_mtime,
        stat.st_size,
    )

    monkeypatch.setattr(ScanManager, "_instance", None, raising=False)
    mgr = ScanManager.get_instance()
    task = await mgr.start_scan(path=str(music_root), force=False)
    await task

    row = await db.fetchrow("SELECT quick_hash, title FROM track WHERE path=$1", rel_path)
    assert row["quick_hash"] is not None
    assert row["title"] == "Song"


@pytest.mark.asyncio
async def test_missing_only_branch_selectivity(monkeypatch):
    """
    Ensure missing_only fetches only branches that are absent:
    - Bio missing -> bio fetched
    - Top tracks/singles/similar present -> their branches skipped
    - Artwork present and non-spotify -> spotify fallback skipped
    """
    coordinator = coordinator_module.MetadataCoordinator()
    artist = {
        "mbid": "artist-branch",
        "name": "Branchy",
        "bio": None,
        "image_url": "http://fanart/thumb.jpg",
        "image_source": "fanart",
        "has_top_tracks": True,
        "has_singles": True,
        "has_similar": True,
        "wikidata_url": "http://wikidata/Q123",
    }
    options = {
        "fetch_metadata": False,
        "fetch_artwork": True,
        "fetch_spotify_artwork": True,
        "fetch_bio": True,
        "refresh_top_tracks": True,
        "refresh_singles": True,
        "fetch_similar_artists": True,
        "missing_only": True,
    }

    calls = {"bio": 0, "top": 0, "singles": 0, "similar": 0, "spotify": 0}

    class _DummyClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw): return type("R", (), {"status_code": 200, "json": lambda self: {}})()

    monkeypatch.setattr(coordinator_module, "get_client", lambda client=None: _DummyClient())
    monkeypatch.setattr(
        coordinator_module.musicbrainz,
        "fetch_core",
        AsyncMock(
            return_value={
                "wikidata_url": "http://wikidata/Q123",
                "wikipedia_url": "https://en.wikipedia.org/wiki/Branchy",
            }
        ),
    )
    monkeypatch.setattr(
        coordinator_module.artwork,
        "fetch_fanart_artist_images",
        AsyncMock(side_effect=lambda *a, **k: calls.update(art=1)),
    )
    monkeypatch.setattr(
        coordinator_module.lastfm,
        "fetch_top_tracks",
        AsyncMock(side_effect=lambda *a, **k: calls.update(top=calls["top"] + 1)),
    )
    monkeypatch.setattr(
        coordinator_module.musicbrainz,
        "fetch_release_groups",
        AsyncMock(side_effect=lambda *a, **k: calls.update(singles=calls["singles"] + 1)),
    )
    monkeypatch.setattr(
        coordinator_module.lastfm,
        "fetch_similar_artists",
        AsyncMock(side_effect=lambda *a, **k: calls.update(similar=calls["similar"] + 1)),
    )
    monkeypatch.setattr(
        coordinator_module.wikipedia,
        "fetch_bio",
        AsyncMock(side_effect=lambda *a, **k: calls.update(bio=calls["bio"] + 1) or "fetched-bio"),
    )
    monkeypatch.setattr(
        coordinator_module.wikidata,
        "fetch_wikipedia_title",
        AsyncMock(return_value="Branchy"),
    )
    monkeypatch.setattr(
        coordinator_module.artwork,
        "resolve_spotify_id",
        AsyncMock(side_effect=lambda *a, **k: calls.update(spotify=calls["spotify"] + 1) or ("sp", "url")),
    )
    monkeypatch.setattr(
        coordinator_module.artwork,
        "fetch_spotify_artist_images",
        AsyncMock(return_value=None),
    )

    updates, _ = await coordinator.process_artist(
        artist, options, local_release_group_ids=set(), fetch_only=True, client=None
    )

    assert updates["bio"] == "fetched-bio"
    assert calls["bio"] == 1
    assert calls["top"] == 0
    assert calls["singles"] == 0
    assert calls["similar"] == 0
    # Artwork present from fanart -> spotify fallback should not run
    assert calls["spotify"] == 0


@pytest.mark.asyncio
async def test_metadata_only_respects_filters(monkeypatch, db):
    await _truncate(db)
    await db.execute("INSERT INTO artist (mbid, name) VALUES ($1,$2)", "a1", "Match Artist")
    await db.execute("INSERT INTO artist (mbid, name) VALUES ($1,$2)", "a2", "Other Artist")

    seen_mbids: List[str] = []

    async def stub_update_metadata(self, artists, options, local_release_group_ids_map=None):
        seen_mbids.extend([a["mbid"] for a in artists])

    monkeypatch.setattr(coordinator_module.MetadataCoordinator, "update_metadata", stub_update_metadata)

    monkeypatch.setattr(ScanManager, "_instance", None, raising=False)
    mgr = ScanManager.get_instance()
    task = await mgr.start_metadata_update(
        path=None,
        artist_filter="Match",
        mbid_filter=None,
        missing_only=False,
        fetch_metadata=True,
    )
    await task

    assert set(seen_mbids) == {"a1"}


@pytest.mark.asyncio
async def test_artwork_fallback_to_spotify(monkeypatch):
    coordinator = coordinator_module.MetadataCoordinator()
    artist = {"mbid": "artist-x", "name": "X"}
    options = {"fetch_artwork": True, "fetch_spotify_artwork": True}

    class _DummyClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(coordinator_module, "get_client", lambda client=None: _DummyClient())
    monkeypatch.setattr(
        coordinator_module.artwork,
        "fetch_fanart_artist_images",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        coordinator_module.musicbrainz,
        "fetch_core",
        AsyncMock(return_value={"_spotify_candidates": ["cand"], "wikidata_url": None}),
    )
    monkeypatch.setattr(
        coordinator_module.artwork,
        "resolve_spotify_id",
        AsyncMock(return_value=("sp-id", "https://open.spotify.com/artist/sp-id")),
    )
    monkeypatch.setattr(
        coordinator_module.artwork,
        "fetch_spotify_artist_images",
        AsyncMock(return_value="http://spotify/thumb.jpg"),
    )
    monkeypatch.setattr(
        coordinator_module,
        "download_and_save_artwork",
        AsyncMock(return_value={"sha1": "abc", "meta": {}}),
    )

    updates, art_res = await coordinator.process_artist(
        artist, options, local_release_group_ids=set(), fetch_only=True, client=None
    )
    assert updates["image_url"] == "http://spotify/thumb.jpg"
    assert updates["image_source"] == "spotify"
    assert art_res["thumb"]["sha1"] == "abc"
