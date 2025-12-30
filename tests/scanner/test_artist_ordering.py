import pytest
from unittest.mock import AsyncMock

from app.scanner.scan_manager import ScanManager


@pytest.mark.asyncio
async def test_fetch_artists_sorted_primary_then_name():
    mgr = ScanManager()

    # Unsorted input
    rows = [
        {"mbid": "c", "name": None, "has_primary_album": False, "bio": None, "image_url": None, "image_source": None, "has_top_tracks": False, "has_singles": False, "has_similar": False},
        {"mbid": "b", "name": "Beta", "has_primary_album": False, "bio": None, "image_url": None, "image_source": None, "has_top_tracks": False, "has_singles": False, "has_similar": False},
        {"mbid": "a", "name": "Alpha", "has_primary_album": True, "bio": None, "image_url": None, "image_source": None, "has_top_tracks": False, "has_singles": False, "has_similar": False},
        {"mbid": "d", "name": "Delta", "has_primary_album": True, "bio": None, "image_url": None, "image_source": None, "has_top_tracks": False, "has_singles": False, "has_similar": False},
    ]

    db = AsyncMock()
    db.fetch = AsyncMock(return_value=rows)

    artists = await mgr._fetch_artists_for_update(db, None, None, None)
    order = [a["mbid"] for a in artists]

    # Primary (Alpha, Delta) first sorted by name, then non-primary (Beta, None name)
    assert order == ["a", "d", "b", "c"]
