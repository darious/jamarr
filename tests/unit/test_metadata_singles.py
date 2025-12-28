import pytest
from unittest.mock import patch

@pytest.mark.asyncio
async def test_fetch_artist_metadata_singles_no_local_filter():
    """
    Regression Test: Ensure 'singles' are NOT filtered by local_release_group_ids.
    They should be returned purely based on what APIs return (Discovery Mode for singles).
    """
    from app.scanner import metadata as md

    # Mock fetch_artist_release_groups to return some dummy singles
    mock_singles = [
        {"mbid": "s1", "title": "Single One", "date": "2021-01-01"},
        {"mbid": "s2", "title": "Single Two", "date": "2022-02-02"}
    ]

    async def fake_fetch_releases(mbid, rtype, client):
        if rtype == "single":
            return mock_singles
        return []

    # Patch the internal helper
    with patch.object(md, "fetch_artist_release_groups", side_effect=fake_fetch_releases):
        
        # Test Case 1: No local files (empty set)
        result = await md.fetch_artist_metadata(
            mbid="mbid-123",
            artist_name="Test Artist",
            local_release_group_ids=set(), # Empty
            fetch_singles=True,
            fetch_metadata=False,
            fetch_bio=False,
            fetch_artwork=False,
            fetch_links=False,
            fetch_top_tracks=False,
            fetch_similar_artists=False
        )

        assert len(result["singles"]) == 2
        assert result["singles"] == mock_singles
        
        # Test Case 2: Local files present (should still return all singles, not just local ones)
        # (Though current logic simply returns ALL fetched singles, so this just confirms it doesn't break)
        result_with_local = await md.fetch_artist_metadata(
            mbid="mbid-123",
            artist_name="Test Artist",
            local_release_group_ids={"s1"}, # Only s1 is local
            fetch_singles=True,
            fetch_metadata=False,
            fetch_bio=False,
            fetch_artwork=False,
            fetch_links=False,
            fetch_top_tracks=False,
            fetch_similar_artists=False
        )

        # Should still return BOTH s1 and s2 because we removed the filter
        assert len(result_with_local["singles"]) == 2
        assert result_with_local["singles"] == mock_singles
