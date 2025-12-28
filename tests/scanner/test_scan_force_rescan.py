import os
from unittest.mock import AsyncMock

import pytest

from app.scanner.scan_manager import ScanManager
from app.scanner.services import artwork, lastfm, musicbrainz, wikidata, wikipedia
from app.scanner.services import coordinator as coordinator_module


@pytest.mark.asyncio
async def test_force_rescan_reprocesses_all_files(db, tmp_path, monkeypatch):
    """
    Verify incremental scan skips unchanged files while force_rescan=True reprocesses
    everything and refreshes tags, matching the v2 spec change-detection rules.
    """
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    track_path = music_dir / "Artist" / "Album" / "track.mp3"
    track_path.parent.mkdir(parents=True, exist_ok=True)
    track_path.write_bytes(b"first-pass-audio")

    # Dynamic tag data so we can verify when the scanner actually re-reads tags
    tag_state = {"title": "First Title"}

    def fake_extract_tags(path: str):
        return {
            "title": tag_state["title"],
            "artist": "Artist",
            "album": "Album",
            "album_artist": "Artist",
            "artist_mbid": "artist-mbid-1",
            "release_group_mbid": "rg-mbid-1",
        }

    monkeypatch.setattr("app.scanner.core.extract_tags", fake_extract_tags)
    monkeypatch.setattr("app.scanner.core.extract_and_save_artwork", AsyncMock(return_value=None))
    monkeypatch.setattr("app.scanner.core.upsert_artwork_record", AsyncMock(return_value=None))
    monkeypatch.setattr("app.scanner.core.get_music_path", lambda: str(music_dir))
    monkeypatch.setattr("app.scanner.scan_manager.get_music_path", lambda: str(music_dir))

    # Fresh ScanManager so it picks up the patched music path
    monkeypatch.setattr(ScanManager, "_instance", None, raising=False)
    manager = ScanManager.get_instance()

    rel_path = os.path.relpath(track_path, music_dir)

    # First scan indexes the file
    await manager.scanner.scan_filesystem(root_path=str(music_dir), force_rescan=False)
    title_1 = await db.fetchval("SELECT title FROM track WHERE path=$1", rel_path)
    assert title_1 == "First Title"

    # Second scan with no changes should skip the file entirely (title unchanged)
    tag_state["title"] = "Second Title"
    await manager.scanner.scan_filesystem(root_path=str(music_dir), force_rescan=False)
    title_2 = await db.fetchval("SELECT title FROM track WHERE path=$1", rel_path)
    assert title_2 == "First Title"

    # Force rescan should reprocess even without file changes and pick up new tags
    tag_state["title"] = "Third Title"
    await manager.scanner.scan_filesystem(root_path=str(music_dir), force_rescan=True)
    title_3 = await db.fetchval("SELECT title FROM track WHERE path=$1", rel_path)
    assert title_3 == "Third Title"


@pytest.mark.asyncio
async def test_missing_only_short_circuits_metadata(monkeypatch):
    """
    When missing_only=True and all enrichment data already exists, process_artist
    should short-circuit before calling any external providers.
    """
    coordinator = coordinator_module.MetadataCoordinator()
    artist = {
        "mbid": "artist-mbid-2",
        "name": "Existing Artist",
        "bio": "Existing bio",
        "image_url": "http://fanart/img.jpg",
        "image_source": "fanart",
        "spotify_url": "https://open.spotify.com/artist/sp-id",
        "has_top_tracks": True,
        "has_similar": True,
        "has_singles": True,
    }
    options = {
        "fetch_metadata": True,
        "fetch_artwork": True,
        "fetch_spotify_artwork": True,
        "fetch_bio": True,
        "refresh_top_tracks": True,
        "refresh_singles": True,
        "fetch_similar_artists": True,
        "missing_only": True,
    }

    blocker = AsyncMock(side_effect=AssertionError("Should not hit external services"))
    monkeypatch.setattr(musicbrainz, "fetch_core", blocker)
    monkeypatch.setattr(artwork, "fetch_fanart_artist_images", blocker)
    monkeypatch.setattr(lastfm, "fetch_top_tracks", blocker)
    monkeypatch.setattr(lastfm, "fetch_similar_artists", blocker)
    monkeypatch.setattr(lastfm, "fetch_artist_url", blocker)
    monkeypatch.setattr(musicbrainz, "fetch_release_groups", blocker)
    monkeypatch.setattr(wikidata, "fetch_wikipedia_title", blocker)
    monkeypatch.setattr(wikidata, "fetch_external_links", blocker)
    monkeypatch.setattr(wikipedia, "fetch_bio", blocker)
    monkeypatch.setattr(artwork, "resolve_spotify_id", blocker)
    monkeypatch.setattr(artwork, "fetch_spotify_artist_images", blocker)
    monkeypatch.setattr(coordinator_module, "download_and_save_artwork", blocker)

    result = await coordinator.process_artist(
        artist, options, local_release_group_ids=set(), fetch_only=True, client=None
    )
    assert result is True

    # Ensure none of the patched providers were awaited
    assert blocker.await_count == 0


class _DummyAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_metadata_branches_fire_when_requested(monkeypatch):
    """
    With missing_only disabled and every toggle on, all enrichment branches should
    execute once and feed their outputs into the update payload.
    """
    coordinator = coordinator_module.MetadataCoordinator()
    artist = {
        "mbid": "artist-mbid-3",
        "name": "Fresh Artist",
    }
    options = {
        "fetch_metadata": True,
        "fetch_artwork": True,
        "fetch_spotify_artwork": True,
        "fetch_bio": True,
        "refresh_top_tracks": True,
        "refresh_singles": True,
        "fetch_similar_artists": True,
        "missing_only": False,
    }

    monkeypatch.setattr(coordinator_module, "get_client", lambda client=None: _DummyAsyncClient())

    mb_core = AsyncMock(return_value={"wikidata_url": "http://wikidata/Q1", "_spotify_candidates": ["cand1"]})
    fanart_mock = AsyncMock(return_value={})
    top_tracks_mock = AsyncMock(return_value=[{"name": "Top Track"}])
    similar_mock = AsyncMock(return_value=[{"mbid": "similar-1"}])
    artist_url_mock = AsyncMock(return_value="https://last.fm/artist/fresh")
    release_groups_mock = AsyncMock(return_value=[])
    wikidata_title_mock = AsyncMock(return_value="Fresh_Artist")
    external_links_mock = AsyncMock(return_value={})
    wiki_bio_mock = AsyncMock(return_value="Biography text")
    resolve_spotify_mock = AsyncMock(return_value=("sp-id", "https://open.spotify.com/artist/sp-id"))
    spotify_images_mock = AsyncMock(return_value="http://spotify/img.jpg")
    download_art_mock = AsyncMock(return_value={"sha1": "abc", "meta": {}})

    monkeypatch.setattr(musicbrainz, "fetch_core", mb_core)
    monkeypatch.setattr(artwork, "fetch_fanart_artist_images", fanart_mock)
    monkeypatch.setattr(lastfm, "fetch_top_tracks", top_tracks_mock)
    monkeypatch.setattr(lastfm, "fetch_similar_artists", similar_mock)
    monkeypatch.setattr(lastfm, "fetch_artist_url", artist_url_mock)
    monkeypatch.setattr(musicbrainz, "fetch_release_groups", release_groups_mock)
    monkeypatch.setattr(wikidata, "fetch_wikipedia_title", wikidata_title_mock)
    monkeypatch.setattr(wikidata, "fetch_external_links", external_links_mock)
    monkeypatch.setattr(wikipedia, "fetch_bio", wiki_bio_mock)
    monkeypatch.setattr(artwork, "resolve_spotify_id", resolve_spotify_mock)
    monkeypatch.setattr(artwork, "fetch_spotify_artist_images", spotify_images_mock)
    monkeypatch.setattr(coordinator_module, "download_and_save_artwork", download_art_mock)

    updates, art_res = await coordinator.process_artist(
        artist, options, local_release_group_ids=set(), fetch_only=True, client=None
    )

    # Every branch should have been hit exactly once
    assert mb_core.await_count == 1
    assert fanart_mock.await_count == 1
    assert top_tracks_mock.await_count == 1
    assert similar_mock.await_count == 1
    assert artist_url_mock.await_count == 1
    # Singles + albums + EP calls share the same mock
    assert release_groups_mock.await_count == 3
    assert wikidata_title_mock.await_count == 1
    assert external_links_mock.await_count == 1
    assert wiki_bio_mock.await_count == 1
    assert resolve_spotify_mock.await_count == 1
    assert spotify_images_mock.await_count == 1
    assert download_art_mock.await_count == 1

    # Payload aggregates outputs from each branch
    assert updates["top_tracks"] == [{"name": "Top Track"}]
    assert updates["similar_artists"] == [{"mbid": "similar-1"}]
    assert updates["singles"] == [] or updates.get("singles") is None  # empty list or None is acceptable
    assert updates["wikipedia_url"].endswith("Fresh_Artist")
    assert updates["bio"] == "Biography text"
    assert updates["image_url"] == "http://spotify/img.jpg"
    assert updates["image_source"] == "spotify"
    assert art_res["thumb"]["sha1"] == "abc"
