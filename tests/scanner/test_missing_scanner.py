import pytest

from unittest.mock import patch
from app.scanner.missing_scanner import MissingAlbumsScanner
from app.db import get_pool

@pytest.mark.asyncio
async def test_missing_albums_scanner_primary_filter():
    """
    Verify that scanner selects only primary artists by default.
    """
    scanner = MissingAlbumsScanner()
    
    # Mock MusicBrainz fetch
    with patch("app.scanner.services.musicbrainz.fetch_release_groups") as mock_mb:
        mock_mb.return_value = [] # Return empty to avoid downstream logic in this test
        
        # We need to spy on the DB query to ensure strict join is used
        # Since we use real DB in tests (usually), we can insert data and check results?
        # A simpler way is to inspect the executed query logic if we could, 
        # but integration testing with data is better.
        
        async with get_pool().acquire() as conn:
            # Setup: 1 Primary Artist, 1 Non-Primary Artist
            await conn.execute("INSERT INTO artist (mbid, name) VALUES ('art1', 'Primary Art')")
            await conn.execute("INSERT INTO artist (mbid, name) VALUES ('art2', 'Secondary Art')")
            
            await conn.execute("INSERT INTO album (mbid, title) VALUES ('alb1', 'Album 1')")
            
            # Link art1 as Primary
            await conn.execute("INSERT INTO artist_album (artist_mbid, album_mbid, type) VALUES ('art1', 'alb1', 'primary')")
            # Link art2 as something else
            await conn.execute("INSERT INTO artist_album (artist_mbid, album_mbid, type) VALUES ('art2', 'alb1', 'remixer')")
            
            # Run scan without filters
            await scanner.scan()
            
            # Mock MB should be called only for art1
            # But wait, scanner loops over results.
            # We can check calls.
            
            called_mbids = [c[0][0] for c in mock_mb.call_args_list]
            assert "art1" in called_mbids
            assert "art2" not in called_mbids

@pytest.mark.asyncio
async def test_missing_albums_logic():
    """
    Verify diff logic and DB updates.
    """
    scanner = MissingAlbumsScanner()
    
    async with get_pool().acquire() as conn:
        # Setup Artist
        await conn.execute("INSERT INTO artist (mbid, name) VALUES ('mb_art_1', 'Test Artist')")
        # Setup Local Album (RG1)
        await conn.execute("INSERT INTO album (mbid, title, release_group_mbid) VALUES ('rel1', 'Local Album', 'rg1')")
        await conn.execute("INSERT INTO artist_album (artist_mbid, album_mbid, type) VALUES ('mb_art_1', 'rel1', 'primary')")
        
        # Existing missing album (should be cleared if not re-added, but here we expect it to be re-added if still missing)
        # Actually logic is: delete all for artist, then insert fresh.
        await conn.execute("""
            INSERT INTO missing_album (artist_mbid, release_group_mbid, title, primary_type) 
            VALUES ('mb_art_1', 'rg_old', 'Old Missing', 'Album')
        """)
    
    # Mock MusicBrainz: Returns RG1 (Present), RG2 (New Missing)
    with patch("app.scanner.services.musicbrainz.fetch_release_groups") as mock_mb:
        mock_mb.return_value = [
            {"mbid": "rg1", "title": "Local Album", "date": "2020-01-01"},
            {"mbid": "rg2", "title": "New Missing Album", "date": "2022-01-01", "musicbrainz_url": "http://mb.org/rg2"}
        ]
        
        await scanner.scan(mbid_filter="mb_art_1")
        
        async with get_pool().acquire() as conn:
            rows = await conn.fetch("SELECT release_group_mbid, title FROM missing_album WHERE artist_mbid = 'mb_art_1'")
            rgs = {r["release_group_mbid"]: r["title"] for r in rows}
            
            # rg_old should be gone (not in MB response)
            assert "rg_old" not in rgs
            # rg1 should be ignored (local)
            assert "rg1" not in rgs
            # rg2 should be present
            assert "rg2" in rgs
            assert rgs["rg2"] == "New Missing Album"

