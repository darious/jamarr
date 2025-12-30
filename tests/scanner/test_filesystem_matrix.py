import os
import pytest
from pathlib import Path
from unittest.mock import patch

from app.scanner.scan_manager import ScanManager

pytestmark = pytest.mark.slow


def _write_wav(path: Path):
    import wave
    import struct

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wf:
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


def _tags(title, artist_mbid, rg_mbid):
    return {
        "title": title,
        "artist": "Artist",
        "album": "Album",
        "album_artist": "Artist",
        "artist_mbid": artist_mbid,
        "release_group_mbid": rg_mbid,
    }


@pytest.mark.asyncio
async def test_filesystem_only_matrix_force_and_delete(tmp_path, monkeypatch, db):
    """
    Matrix over force=True/False and deletion handling:
    - initial scan indexes files
    - delete one file, rerun force=False -> removed from DB
    - force=True reindexes remaining and wipes stale rows.
    """
    music_root = tmp_path / "music"
    file_a = music_root / "Artist" / "Album" / "a.wav"
    file_b = music_root / "Artist" / "Album" / "b.wav"
    _write_wav(file_a)
    _write_wav(file_b)

    monkeypatch.setattr("app.scanner.core.get_music_path", lambda: str(music_root))
    monkeypatch.setattr("app.scanner.scan_manager.get_music_path", lambda: str(music_root))
    monkeypatch.setattr(
        "app.scanner.core.extract_tags",
        lambda p: _tags("A" if p.endswith("a.wav") else "B", "artist-1", "rg-1" if p.endswith("a.wav") else "rg-2"),
    )

    async def _fake_artwork(*_a, **_k):
        return None

    monkeypatch.setattr("app.scanner.core.extract_and_save_artwork", _fake_artwork)

    await _truncate(db)

    # Initial scan
    monkeypatch.setattr(ScanManager, "_instance", None, raising=False)
    mgr = ScanManager.get_instance()
    task = await mgr.start_scan(path=str(music_root), force=False)
    await task
    assert await db.fetchval("SELECT COUNT(*) FROM track") == 2

    # Delete one file, rerun without force -> should delete missing track
    file_a.unlink()
    task = await mgr.start_scan(path=str(music_root), force=False)
    await task
    paths = await db.fetch("SELECT path FROM track ORDER BY path")
    assert [r["path"] for r in paths] == [os.path.relpath(file_b, music_root)]

    # Force scan should wipe and reindex remaining file (no stale rows)
    task = await mgr.start_scan(path=str(music_root), force=True)
    await task
    paths = await db.fetch("SELECT path FROM track ORDER BY path")
    assert [r["path"] for r in paths] == [os.path.relpath(file_b, music_root)]


@pytest.mark.asyncio
async def test_partial_path_metadata_filter(tmp_path, monkeypatch, db):
    """
    Path-scoped metadata update should restrict artists to the folder.
    """
    music_root = tmp_path / "music"
    a1 = music_root / "A1" / "Album" / "t.wav"
    a2 = music_root / "A2" / "Album" / "t.wav"
    _write_wav(a1)
    _write_wav(a2)

    monkeypatch.setattr("app.scanner.core.get_music_path", lambda: str(music_root))
    monkeypatch.setattr("app.scanner.scan_manager.get_music_path", lambda: str(music_root))
    monkeypatch.setattr(
        "app.scanner.core.extract_tags",
        lambda p: _tags("T", "mbid-a1" if "A1" in p else "mbid-a2", "rg-1"),
    )

    async def _fake_artwork(*_a, **_k):
        return None

    monkeypatch.setattr("app.scanner.core.extract_and_save_artwork", _fake_artwork)

    await _truncate(db)
    monkeypatch.setattr(ScanManager, "_instance", None, raising=False)
    mgr = ScanManager.get_instance()
    await (await mgr.start_scan(path=str(music_root), force=False))

    seen = []

    async def stub_update_metadata(self, artists, options, local_release_group_ids_map=None):
        seen.extend([a["mbid"] for a in artists])

    from app.scanner.services import coordinator as coordinator_module

    with patch.object(coordinator_module.MetadataCoordinator, "update_metadata", stub_update_metadata):
        # Metadata update scoped to A1 folder
        await (await mgr.start_metadata_update(path=str(music_root / "A1"), missing_only=False, fetch_metadata=True))
    assert set(seen) == {"mbid-a1"}
