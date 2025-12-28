import itertools
import os
from typing import Dict, Iterable

import pytest
from app.scanner.scan_manager import ScanManager
from app.scanner.services import coordinator as coordinator_module
from app.db import get_db

pytestmark = pytest.mark.slow


def _write_wav(path: os.PathLike):
    """Write a tiny valid WAV file to disk for hashing/mtime checks."""
    import wave
    import struct

    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        frames = (struct.pack("<h", 0) for _ in range(100))
        wf.writeframes(b"".join(frames))


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


def _all_option_combos() -> Iterable[Dict[str, bool]]:
    """
    Enumerate every combination of metadata toggles + missing_only + force_rescan.
    Total combos: 2^9 = 512.
    """
    flags = [
        "fetch_metadata",
        "fetch_bio",
        "fetch_artwork",
        "fetch_spotify_artwork",
        "refresh_top_tracks",
        "refresh_singles",
        "fetch_similar_artists",
        "missing_only",
        "force",
    ]
    for combo in itertools.product([False, True], repeat=len(flags)):
        yield dict(zip(flags, combo))


def _seed_files(tmp_path) -> Dict[str, Dict]:
    """
    Create two tiny WAV files and return deterministic tags keyed by filepath.
    """
    music_dir = tmp_path / "library"
    artist_dir = music_dir / "ArtistA" / "AlbumA"
    artist_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for idx in range(2):
        fp = artist_dir / f"track{idx + 1}.wav"
        _write_wav(fp)
        files[str(fp)] = {
            "title": f"Song {idx + 1}",
            "artist": "ArtistA",
            "album": "AlbumA",
            "album_artist": "ArtistA",
            "artist_mbid": f"artist-mbid-{idx + 1}",
            "release_group_mbid": f"rg-mbid-{idx + 1}",
            "track_no": idx + 1,
            "disc_no": 1,
        }
    return files


async def _seed_existing_metadata(db, tags: Dict[str, Dict]):
    """
    Pre-populate metadata so missing_only combos can exercise skip paths.
    """
    for tag in tags.values():
        mbid = tag["artist_mbid"]
        await db.execute(
            """
            INSERT INTO artist (mbid, name, bio, image_url, image_source)
            VALUES ($1, $2, 'existing-bio', 'http://existing/art.jpg', 'fanart')
            ON CONFLICT (mbid) DO NOTHING
            """,
            mbid,
            tag["artist"],
        )
        # existing top track / similar / singles flags
        await db.execute(
            """
            INSERT INTO top_track (artist_mbid, external_name, type)
            VALUES ($1, 'Existing Top', 'top')
            ON CONFLICT DO NOTHING
            """,
            mbid,
        )
        await db.execute(
            """
            INSERT INTO top_track (artist_mbid, external_name, type)
            VALUES ($1, 'Existing Single', 'single')
            ON CONFLICT DO NOTHING
            """,
            mbid,
        )
        await db.execute(
            """
            INSERT INTO similar_artist (artist_mbid, similar_artist_name, similar_artist_mbid, rank)
            VALUES ($1, 'Existing Similar', 'similar-0', 1)
            ON CONFLICT DO NOTHING
            """,
            mbid,
        )


def _build_fake_metadata_updater():
    """
    Return a stub for MetadataCoordinator.update_metadata that writes to the DB
    based on the requested options, respecting missing_only semantics.
    """

    async def _stub_update_metadata(self, artists, options, local_release_group_ids_map=None):
        async for db in get_db():
            for artist in artists:
                mbid = artist["mbid"]
                # Respect missing_only: skip branches if data already present / flags set
                missing_only = options.get("missing_only", False)

                async with db.transaction():
                    if options.get("fetch_metadata") and not (missing_only and artist.get("name")):
                        await db.execute(
                            "UPDATE artist SET name = $1, updated_at = NOW() WHERE mbid=$2",
                            f"{artist.get('name')}-meta",
                            mbid,
                        )

                    if options.get("fetch_bio") and not (missing_only and artist.get("bio")):
                        await db.execute(
                            "UPDATE artist SET bio = $1, updated_at = NOW() WHERE mbid=$2",
                            "fetched-bio",
                            mbid,
                        )

                    # Artwork logic: fanart first, spotify fallback
                    if options.get("fetch_artwork") and not (missing_only and artist.get("image_url")):
                        await db.execute(
                            "UPDATE artist SET image_url=$1, image_source='fanart', updated_at = NOW() WHERE mbid=$2",
                            "http://fanart/thumb.jpg",
                            mbid,
                        )
                    elif (
                        options.get("fetch_spotify_artwork")
                        and not artist.get("image_url")
                        and not (missing_only and artist.get("image_url"))
                    ):
                        await db.execute(
                            "UPDATE artist SET image_url=$1, image_source='spotify', updated_at = NOW() WHERE mbid=$2",
                            "http://spotify/thumb.jpg",
                            mbid,
                        )

                    if options.get("refresh_top_tracks") and not (missing_only and artist.get("has_top_tracks")):
                        await db.execute(
                            """
                            INSERT INTO top_track (artist_mbid, external_name, type)
                            VALUES ($1, 'Top Track', 'top')
                            ON CONFLICT DO NOTHING
                            """,
                            mbid,
                        )

                    if options.get("refresh_singles") and not (missing_only and artist.get("has_singles")):
                        await db.execute(
                            """
                            INSERT INTO top_track (artist_mbid, external_name, type)
                            VALUES ($1, 'Single Track', 'single')
                            ON CONFLICT DO NOTHING
                            """,
                            mbid,
                        )

                    if options.get("fetch_similar_artists") and not (missing_only and artist.get("has_similar")):
                        await db.execute(
                            """
                            INSERT INTO similar_artist (artist_mbid, similar_artist_name, similar_artist_mbid, rank)
                            VALUES ($1, 'Similar Artist', 'sim-1', 1)
                            ON CONFLICT DO NOTHING
                            """,
                            mbid,
                        )

        return {"updated": len(artists), "errors": 0}

    return _stub_update_metadata


@pytest.mark.asyncio
async def test_full_scan_option_matrix_exercises_all_paths(tmp_path, monkeypatch):
    """
    End-to-end-ish: run start_full for every combination of metadata flags + force/missing_only
    using real files and the real DB, while stubbing networked metadata providers.
    Verifies DB state matches the requested options each time.
    """
    tags = _seed_files(tmp_path)
    music_root = str(tmp_path / "library")

    # Patch music path and file/tag helpers
    monkeypatch.setattr("app.scanner.core.get_music_path", lambda: music_root)
    monkeypatch.setattr("app.scanner.scan_manager.get_music_path", lambda: music_root)
    async def _fake_artwork(*_args, **_kw):
        return None  # skip artwork to avoid FK noise

    monkeypatch.setattr("app.scanner.core.extract_and_save_artwork", _fake_artwork)

    def fake_extract_tags(path: str):
        return tags[path]

    monkeypatch.setattr("app.scanner.core.extract_tags", fake_extract_tags)

    # Stub metadata coordinator
    monkeypatch.setattr(coordinator_module.MetadataCoordinator, "update_metadata", _build_fake_metadata_updater())

    # Loop through every combination
    async for db in get_db():
        for options in _all_option_combos():
            await _truncate(db)

            # Seed existing metadata only when missing_only flag is set to verify skip logic
            if options["missing_only"]:
                await _seed_existing_metadata(db, tags)

            # Fresh manager per run
            monkeypatch.setattr(ScanManager, "_instance", None, raising=False)
            mgr = ScanManager.get_instance()

            task = await mgr.start_full(
                path=music_root,
                force=options["force"],
                artist_filter=None,
                mbid_filter=None,
                missing_only=options["missing_only"],
                fetch_metadata=options["fetch_metadata"],
                fetch_bio=options["fetch_bio"],
                fetch_artwork=options["fetch_artwork"],
                fetch_spotify_artwork=options["fetch_spotify_artwork"],
                refresh_top_tracks=options["refresh_top_tracks"],
                refresh_singles=options["refresh_singles"],
                fetch_similar_artists=options["fetch_similar_artists"],
                fetch_links=False,
            )
            await task

            # --- Filesystem assertions ---
            rows = await db.fetch("SELECT path, mtime, size_bytes, quick_hash, artwork_id FROM track ORDER BY path")
            assert len(rows) == len(tags)
            for row in rows:
                assert row["quick_hash"], "quick_hash should be persisted"
                assert row["mtime"] and row["size_bytes"] > 0
                # Artwork is skipped in this stubbed path
                assert row["artwork_id"] is None

            # Artists inserted
            artists = await db.fetch("SELECT mbid, bio, image_url, image_source FROM artist ORDER BY mbid")
            assert len(artists) == len(tags)

            # --- Metadata assertions per option combo ---
            for artist in artists:
                mbid = artist["mbid"]

                if options["fetch_bio"] and not options["missing_only"]:
                    assert artist["bio"] == "fetched-bio"
                elif options["missing_only"]:
                    # should preserve existing bio if pre-seeded
                    assert artist["bio"] in ("existing-bio", "fetched-bio")

                if options["fetch_artwork"] and not (options["missing_only"] and artist["image_source"] == "fanart"):
                    assert artist["image_source"] == "fanart"
                elif options["fetch_spotify_artwork"] and not artist["image_url"]:
                    assert artist["image_source"] in ("spotify", "fanart", None)

                top_tracks = await db.fetchval("SELECT COUNT(*) FROM top_track WHERE artist_mbid=$1 AND type='top'", mbid)
                singles = await db.fetchval("SELECT COUNT(*) FROM top_track WHERE artist_mbid=$1 AND type='single'", mbid)
                similars = await db.fetchval("SELECT COUNT(*) FROM similar_artist WHERE artist_mbid=$1", mbid)

                if options["refresh_top_tracks"]:
                    assert top_tracks >= 1
                elif options["missing_only"]:
                    # seeded with one top track
                    assert top_tracks >= 1

                if options["refresh_singles"]:
                    assert singles >= 1
                elif options["missing_only"]:
                    assert singles >= 1

                if options["fetch_similar_artists"]:
                    assert similars >= 1
                elif options["missing_only"]:
                    assert similars >= 1

        break  # exit the get_db generator loop


@pytest.mark.asyncio
async def test_missing_only_after_full_scan(tmp_path, monkeypatch):
    """
    Run a full scan to populate everything, then rerun with missing_only=True and
    all enrichment flags to ensure only missing data is refilled while existing
    data is skipped.
    """
    tags = _seed_files(tmp_path)
    music_root = str(tmp_path / "library")

    monkeypatch.setattr("app.scanner.core.get_music_path", lambda: music_root)
    monkeypatch.setattr("app.scanner.scan_manager.get_music_path", lambda: music_root)

    async def _fake_artwork(*_args, **_kw):
        return None

    monkeypatch.setattr("app.scanner.core.extract_and_save_artwork", _fake_artwork)
    monkeypatch.setattr("app.scanner.core.extract_tags", lambda p: tags[p])
    monkeypatch.setattr(coordinator_module.MetadataCoordinator, "update_metadata", _build_fake_metadata_updater())

    async for db in get_db():
        await _truncate(db)

        # 1) Baseline full scan with everything on
        monkeypatch.setattr(ScanManager, "_instance", None, raising=False)
        mgr = ScanManager.get_instance()
        task = await mgr.start_full(
            path=music_root,
            force=True,
            missing_only=False,
            fetch_metadata=True,
            fetch_bio=True,
            fetch_artwork=True,
            fetch_spotify_artwork=True,
            refresh_top_tracks=True,
            refresh_singles=True,
            fetch_similar_artists=True,
            fetch_links=False,
        )
        await task

        # Sanity: data is present
        artist_rows = await db.fetch("SELECT mbid, bio, image_url, image_source FROM artist ORDER BY mbid")
        assert len(artist_rows) == len(tags)
        for a in artist_rows:
            assert a["bio"]
            assert a["image_url"]

        # 2) Drop some data for artist 1 to simulate missing fields
        mbid_missing = list(tags.values())[0]["artist_mbid"]
        await db.execute("UPDATE artist SET bio=NULL, image_url=NULL, image_source=NULL WHERE mbid=$1", mbid_missing)
        await db.execute("DELETE FROM top_track WHERE artist_mbid=$1", mbid_missing)
        await db.execute("DELETE FROM similar_artist WHERE artist_mbid=$1", mbid_missing)

        # Keep artist 2 intact to verify missing_only skips it
        mbid_intact = list(tags.values())[1]["artist_mbid"]
        intact_before = await db.fetchrow(
            "SELECT bio, image_url, image_source FROM artist WHERE mbid=$1", mbid_intact
        )

        # 3) Run missing_only metadata refresh with all flags
        monkeypatch.setattr(ScanManager, "_instance", None, raising=False)
        mgr = ScanManager.get_instance()
        task = await mgr.start_full(
            path=music_root,
            force=False,
            missing_only=True,
            fetch_metadata=True,
            fetch_bio=True,
            fetch_artwork=True,
            fetch_spotify_artwork=True,
            refresh_top_tracks=True,
            refresh_singles=True,
            fetch_similar_artists=True,
            fetch_links=False,
        )
        await task

        # Artist with missing data should be refilled
        a_missing = await db.fetchrow(
            "SELECT bio, image_url, image_source FROM artist WHERE mbid=$1", mbid_missing
        )
        assert a_missing["bio"] == "fetched-bio"
        assert a_missing["image_url"] in ("http://fanart/thumb.jpg", "http://spotify/thumb.jpg")

        tt_missing = await db.fetchval(
            "SELECT COUNT(*) FROM top_track WHERE artist_mbid=$1 AND type='top'", mbid_missing
        )
        assert tt_missing >= 1
        sim_missing = await db.fetchval(
            "SELECT COUNT(*) FROM similar_artist WHERE artist_mbid=$1", mbid_missing
        )
        assert sim_missing >= 1

        # Artist with intact data should remain unchanged
        intact_after = await db.fetchrow(
            "SELECT bio, image_url, image_source FROM artist WHERE mbid=$1", mbid_intact
        )
        assert intact_after == intact_before

        break  # exit get_db generator
