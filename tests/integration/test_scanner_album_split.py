import pytest
from unittest.mock import patch, MagicMock
from app.scanner.core import Scanner
from datetime import date

@pytest.mark.asyncio
async def test_album_split_logic(db):
    scanner = Scanner()
    
    # Mock tags for Release 1
    tags_1 = {
        "title": "Track 1",
        "artist": "The Tester",
        "artist_mbid": "artist-1",
        "album": "Test Album",
        "release_mbid": "release-1",
        "release_group_mbid": "rg-1",
        "release_date": date(2023, 1, 1),
        "release_type": "album",
        "release_type_raw": "Album",
        "discnumber": 1,
        "tracknumber": 1,
        "duration": 100
    }
    
    # Mock tags for Release 2 (Same RG, Different Release)
    tags_2 = {
        "title": "Track 1 (Live)",
        "artist": "The Tester",
        "artist_mbid": "artist-1",
        "album": "Test Album",
        "release_mbid": "release-2",
        "release_group_mbid": "rg-1",
        "release_date": date(2023, 1, 2),
        "release_type": "album",
        "release_type_raw": "Album",
        "discnumber": 1,
        "tracknumber": 1,
        "duration": 100
    }

    # Helper to calculate hash (normally done by scanner)
    
    with patch("app.scanner.core.extract_tags") as mock_extract, \
         patch("app.scanner.core.Scanner._compute_quick_hash") as mock_hash, \
         patch("app.scanner.core.get_music_path") as mock_path, \
         patch("app.scanner.core.os.stat") as mock_stat:
        
        mock_hash.return_value = b'hash1'
        mock_path.return_value = "/tmp"
        
        # Mock stat object
        mock_stat_obj = MagicMock()
        mock_stat_obj.st_mtime = 1000.0
        mock_stat_obj.st_size = 1024
        mock_stat.return_value = mock_stat_obj
        
        # Process File 1
        mock_extract.return_value = tags_1
        await scanner._process_file("/tmp/1.flac", db, set(), False)
        
        # Process File 2
        mock_extract.return_value = tags_2
        await scanner._process_file("/tmp/2.flac", db, set(), False)

    # Verify DB: Should have 2 albums
    albums = await db.fetch("SELECT mbid, release_group_mbid FROM album")
    assert len(albums) == 2, f"Expected 2 albums, found {len(albums)}"
    
    # Verify IDs
    mbids = sorted([a["mbid"] for a in albums])
    assert mbids == ["release-1", "release-2"]
    
    # Verify RG IDs
    rg_ids = [a["release_group_mbid"] for a in albums]
    assert all(d == "rg-1" for d in rg_ids)

    # Verify Tracks linked correctly
    tracks = await db.fetch("SELECT release_mbid, release_group_mbid FROM track")
    assert len(tracks) == 2
    
    t1 = next(t for t in tracks if t["release_mbid"] == "release-1")
    t2 = next(t for t in tracks if t["release_mbid"] == "release-2")
    
    assert t1["release_group_mbid"] == "rg-1"
    assert t2["release_group_mbid"] == "rg-1"

@pytest.mark.asyncio
async def test_album_metadata_update_propagates(db):
    # Verify that updating metadata for an RG updates BOTH albums
    
    # Insert 2 albums sharing RG
    await db.execute("""
        INSERT INTO album (mbid, release_group_mbid, title)
        VALUES 
            ('r1', 'rg1', 'A'),
            ('r2', 'rg1', 'A')
    """)
    
    # Simulate Coordinator update
    # Coordinator calls: UPDATE album SET description = $1 ... WHERE release_group_mbid = $2
    description = "Updated Description"
    rg_id = "rg1"
    
    await db.execute(
        "UPDATE album SET description = $1 WHERE release_group_mbid = $2",
        description, rg_id
    )
    
    # Verify
    rows = await db.fetch("SELECT description FROM album WHERE release_group_mbid = $1", rg_id)
    assert len(rows) == 2
    assert rows[0]["description"] == description
    assert rows[1]["description"] == description
