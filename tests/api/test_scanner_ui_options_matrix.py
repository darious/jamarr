import itertools
from types import SimpleNamespace
from typing import Dict, List

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch

METADATA_FLAGS = [
    "doMetadata",
    "doBio",
    "doArtwork",
    "doSpotifyArtwork",
    "doTopTracks",
    "doSingles",
    "doSimilarArtists",
]


def build_ui_tasks(state: Dict[str, bool]) -> List[Dict]:
    """
    Mirror the Svelte buildTasks() logic so we can exhaustively exercise the
    scanner API with the same combinations the UI can emit.
    """
    tasks: List[Dict] = []
    wants_metadata = any(state[f] for f in METADATA_FLAGS)
    path_value = state.get("path")
    artist_filter = state.get("artist_filter")
    mbid_filter = state.get("mbid_filter")

    if state["runFilesystem"] and wants_metadata:
        tasks.append(
            {
                "type": "full",
                "force": state["forceRescan"],
                "path": path_value,
                "artist_filter": artist_filter,
                "mbid_filter": mbid_filter,
                "missing_only": state["missingOnly"],
                "fetch_metadata": state["doMetadata"],
                "fetch_bio": state["doBio"],
                "fetch_artwork": state["doArtwork"],
                "fetch_spotify_artwork": state["doSpotifyArtwork"],
                # UI default for full scan links: opts.fetchMetadata !== false
                "fetch_links": state["doMetadata"],
                "refresh_top_tracks": state["doTopTracks"],
                "refresh_singles": state["doSingles"],
                "fetch_similar_artists": state["doSimilarArtists"],
            }
        )
    else:
        if state["runFilesystem"]:
            tasks.append(
                {
                    "type": "filesystem",
                    "force": state["forceRescan"],
                    "path": path_value,
                }
            )

        if wants_metadata:
            # Note: UI omits fetch_links for metadata-only runs
            tasks.append(
                {
                    "type": "metadata",
                    "path": path_value,
                    "artist_filter": artist_filter,
                    "mbid_filter": mbid_filter,
                    "missing_only": state["missingOnly"],
                    "fetch_metadata": state["doMetadata"],
                    "fetch_bio": state["doBio"],
                    "fetch_artwork": state["doArtwork"],
                    "fetch_spotify_artwork": state["doSpotifyArtwork"],
                    "refresh_top_tracks": state["doTopTracks"],
                    "refresh_singles": state["doSingles"],
                    "fetch_similar_artists": state["doSimilarArtists"],
                }
            )

    if state["doMissingAlbums"]:
        tasks.append(
            {
                "type": "missing_albums",
                "artist_filter": artist_filter,
                "mbid_filter": mbid_filter,
            }
        )

    return tasks


def strip_none(d: Dict) -> Dict:
    """Drop None values to mirror JSON.stringify behaviour on undefined props."""
    return {k: v for k, v in d.items() if v is not None}


@pytest.mark.asyncio
async def test_scanner_ui_option_matrix_exhaustive(client: AsyncClient, db):
    """
    Exercise every combination of UI toggles to ensure the API routes the request
    to the correct ScanManager method with the exact payload we expect.
    """
    # Patch ScanManager to a lightweight stub so we can assert calls without running scans
    with patch("app.api.scan.ScanManager") as MockSM:
        manager = SimpleNamespace(
            start_scan=AsyncMock(),
            start_metadata_update=AsyncMock(),
            start_full=AsyncMock(),
            start_prune=AsyncMock(),
            start_missing_albums_scan=AsyncMock(),
            stop_scan=AsyncMock(),
            get_music_path=MagicMock(return_value="/app/music"),
        )
        MockSM.get_instance.return_value = manager

        flag_names = [
            "runFilesystem",
            "forceRescan",
            "missingOnly",
            "doMetadata",
            "doBio",
            "doArtwork",
            "doSpotifyArtwork",
            "doTopTracks",
            "doSingles",
            "doSimilarArtists",
            "doMissingAlbums",
        ]

        # All combinations of 11 boolean flags = 2048 cases
        for combo in itertools.product([False, True], repeat=len(flag_names)):
            state = dict(zip(flag_names, combo))
            # Add static filters/path so we can assert propagation
            state["artist_filter"] = "Test Artist"
            state["mbid_filter"] = "test-mbid-123"
            state["path"] = "/app/music"

            tasks = build_ui_tasks(state)

            # Reset mocks for this combination
            manager.start_scan.reset_mock()
            manager.start_metadata_update.reset_mock()
            manager.start_full.reset_mock()
            manager.start_missing_albums_scan.reset_mock()

            # UI would not call the API if no tasks were queued
            if not tasks:
                continue

            for task in tasks:
                payload = strip_none(task)
                resp = await client.post("/api/library/scan", json=payload)
                assert resp.status_code == 200, f"Failed combo {state} -> {payload}"

            expected_full = sum(1 for t in tasks if t["type"] == "full")
            expected_fs = sum(1 for t in tasks if t["type"] == "filesystem")
            expected_meta = sum(1 for t in tasks if t["type"] == "metadata")
            expected_missing = sum(1 for t in tasks if t["type"] == "missing_albums")

            assert manager.start_full.await_count == expected_full, f"full mismatch for {state}"
            assert manager.start_scan.await_count == expected_fs, f"filesystem mismatch for {state}"
            assert manager.start_metadata_update.await_count == expected_meta, f"metadata mismatch for {state}"
            assert (
                manager.start_missing_albums_scan.await_count == expected_missing
            ), f"missing-albums mismatch for {state}"

            # Validate the argument payload mirrors the UI for each call type
            if expected_full:
                kwargs = manager.start_full.await_args.kwargs
                expected = {
                    k: v for k, v in [t for t in tasks if t["type"] == "full"][0].items() if k != "type"
                }
                for key, val in expected.items():
                    assert kwargs.get(key) == val, f"full args mismatch for {state}: {key}"

            if expected_fs:
                kwargs = manager.start_scan.await_args.kwargs
                expected = {
                    k: v for k, v in [t for t in tasks if t["type"] == "filesystem"][0].items() if k != "type"
                }
                for key, val in expected.items():
                    assert kwargs.get(key) == val, f"filesystem args mismatch for {state}: {key}"

            if expected_meta:
                kwargs = manager.start_metadata_update.await_args.kwargs
                expected = {
                    k: v for k, v in [t for t in tasks if t["type"] == "metadata"][0].items() if k != "type"
                }
                for key, val in expected.items():
                    assert kwargs.get(key) == val, f"metadata args mismatch for {state}: {key}"

            if expected_missing:
                kwargs = manager.start_missing_albums_scan.await_args.kwargs
                expected = {k: v for k, v in [t for t in tasks if t["type"] == "missing_albums"][0].items() if k != "type"}
                for key, val in expected.items():
                    assert kwargs.get(key) == val, f"missing-albums args mismatch for {state}: {key}"
