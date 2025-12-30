import itertools
import pytest

from app.scanner.scan_manager import ScanManager
from app.scanner.services import coordinator as coordinator_module

pytestmark = pytest.mark.slow


def _metadata_flag_combos():
    flags = [
        "fetch_metadata",
        "fetch_bio",
        "fetch_artwork",
        "fetch_spotify_artwork",
        "refresh_top_tracks",
        "refresh_singles",
        "fetch_similar_artists",
        "missing_only",
    ]
    for combo in itertools.product([False, True], repeat=len(flags)):
        yield dict(zip(flags, combo))


@pytest.mark.asyncio
async def test_metadata_only_option_matrix(db, monkeypatch):
    """
    Exercise all metadata-only toggle combinations against real DB artists.
    Uses a stubbed coordinator to avoid network calls; asserts call count and option payload.
    """
    await db.execute("TRUNCATE TABLE artist RESTART IDENTITY CASCADE")
    await db.execute("INSERT INTO artist (mbid, name) VALUES ($1,$2)", "a1", "Artist One")
    await db.execute("INSERT INTO artist (mbid, name) VALUES ($1,$2)", "a2", "Artist Two")

    calls = []

    async def stub_update_metadata(self, artists, options, local_release_group_ids_map=None):
        calls.append(options.copy())
        return {"updated": len(artists), "errors": 0}

    monkeypatch.setattr(coordinator_module.MetadataCoordinator, "update_metadata", stub_update_metadata)
    monkeypatch.setattr(ScanManager, "_instance", None, raising=False)
    mgr = ScanManager.get_instance()

    for opts in _metadata_flag_combos():
        # Reset stub call per iteration
        calls.clear()
        task = await mgr.start_metadata_update(
            path=None,
            artist_filter=None,
            mbid_filter=None,
            missing_only=opts["missing_only"],
            fetch_metadata=opts["fetch_metadata"],
            fetch_bio=opts["fetch_bio"],
            fetch_artwork=opts["fetch_artwork"],
            fetch_spotify_artwork=opts["fetch_spotify_artwork"],
            refresh_top_tracks=opts["refresh_top_tracks"],
            refresh_singles=opts["refresh_singles"],
            fetch_similar_artists=opts["fetch_similar_artists"],
            fetch_links=False,
        )
        await task

        assert calls, f"No coordinator call for opts {opts}"
        observed = calls[0]
        for k, v in opts.items():
            assert observed.get(k) == v, f"Option {k} mismatch for {opts}"
