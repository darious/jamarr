import pytest
from unittest.mock import AsyncMock, patch
from app.scanner.services import musicbrainz

@pytest.mark.asyncio
async def test_fetch_artist_release_groups_filters_spotify():
    """
    Ensure releases with 'Spotify' in the title are filtered out.
    """
    mbid = "test-mbid"
    client = AsyncMock()

    # Mock response data
    mock_releases = {
        "release-groups": [
            {
                "id": "rg-1",
                "title": "Normal Single",
                "first-release-date": "2020-01-01",
                "artist-credit": [{"artist": {"id": mbid}}],
                "secondary-types": []
            },
            {
                "id": "rg-2",
                "title": "Spotify Singles",
                "first-release-date": "2021-01-01",
                "artist-credit": [{"artist": {"id": mbid}}],
                "secondary-types": []
            },
            {
                "id": "rg-3",
                "title": "Live at Spotify",
                "first-release-date": "2022-01-01",
                "artist-credit": [{"artist": {"id": mbid}}],
                "secondary-types": []
            },
            {
                "id": "rg-4",
                "title": "Another Good Song",
                "first-release-date": "2023-01-01",
                "artist-credit": [{"artist": {"id": mbid}}],
                "secondary-types": []
            }
        ]
    }

    from unittest.mock import MagicMock
    # Mock the client.get return value
    # Use MagicMock for the response object because its methods/attributes are synchronous
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_releases
    client.get.return_value = mock_resp

    # Patch the rate limiter to avoid sleeping
    # Access mb_limiter in musicbrainz module
    with patch("app.scanner.services.musicbrainz.mb_limiter.acquire", new_callable=AsyncMock):
        # We test "album" type just to trigger the "release-group" path which is generic
        # The filter is in the loop, so it currently applies to both paths (release and release-group endpoints)
        # assuming the variable names align. Code check:
        # In fetch_artist_release_groups:
        # ...
        # title = rg.get("title")
        # norm_title = title.lower().strip()
        # if "spotify" in norm_title: continue
        # ...
        
        results = await musicbrainz.fetch_release_groups(mbid, "album", client)

    titles = [r["title"] for r in results]
    
    # Assertions
    assert "Normal Single" in titles
    assert "Another Good Song" in titles
    assert "Spotify Singles" not in titles
    assert "Live at Spotify" not in titles
    assert len(results) == 2
