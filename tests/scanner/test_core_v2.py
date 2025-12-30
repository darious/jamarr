import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.scanner.core import Scanner

# Mock DB
@pytest.fixture
def mock_db():
    db = AsyncMock()
    # Mock fetch/execute/fetchrow defaults
    db.fetch.return_value = []
    db.fetchval.return_value = 1
    db.fetchrow.return_value = None
    return db

@pytest.fixture
def scanner():
    return Scanner()

@pytest.mark.asyncio
async def test_compute_quick_hash_logic(scanner, tmp_path):
    # Create a dummy file
    f = tmp_path / "test.mp3"
    f.write_bytes(b"A" * 20000) # > 16KB
    
    stat = f.stat()
    h1 = scanner._compute_quick_hash(str(f), stat.st_mtime, stat.st_size)
    assert h1 is not None
    
    # Change mtime, hash should change (because mtime is feed into hash)
    # The Spec says "Hash(first 16KB + last 16KB + size + mtime)"
    # My implementation: hasher.update(str(mtime).encode())
    # So yes, hash changes if mtime changes.
    new_mtime = stat.st_mtime + 100
    h2 = scanner._compute_quick_hash(str(f), new_mtime, stat.st_size)
    assert h1 != h2

@pytest.mark.asyncio
async def test_process_file_no_change(scanner, mock_db):
    # Setup cache
    path = "/music/song.mp3"
    mtime = 1000.0
    size = 500
    expected_hash = b"mockhash"
    
    scanner._db_files_cache = {
        "song.mp3": (mtime, size, expected_hash)
    }
    
    # Mock compute_quick_hash to return same hash
    with patch.object(scanner, "_compute_quick_hash", return_value=expected_hash):
        # Mock os.stat
        stat_mock = MagicMock()
        stat_mock.st_mtime = mtime
        stat_mock.st_size = size
        
        with patch("os.stat", return_value=stat_mock):
            with patch("app.scanner.core.get_music_path", return_value="/music"):
                 await scanner._process_file(path, mock_db, set(), False)
                 
    # Should skip
    assert len(mock_db.method_calls) == 0
    assert scanner.stats["skipped"] == 1

@pytest.mark.asyncio
async def test_process_file_changed_mtime(scanner, mock_db):
    # Setup cache
    path = "/music/song.mp3"
    old_mtime = 1000.0
    size = 500
    old_hash = b"oldhash"
    
    scanner._db_files_cache = {
        "song.mp3": (old_mtime, size, old_hash)
    }
    
    new_hash = b"newhash"
    
    with patch.object(scanner, "_compute_quick_hash", return_value=new_hash):
        stat_mock = MagicMock()
        stat_mock.st_mtime = old_mtime + 10 # Changed
        stat_mock.st_size = size
        
        with patch("os.stat", return_value=stat_mock):
            with patch("app.scanner.core.get_music_path", return_value="/music"):
                with patch("app.scanner.core.extract_tags", return_value={"title": "Song", "artist": "A", "artist_mbid": "mbid1", "release_group_mbid": "rg1"}):
                    with patch("app.scanner.core.extract_and_save_artwork", return_value=None):
                         await scanner._process_file(path, mock_db, set(), False)
                         
    # Should update
    assert scanner.stats["updated"] == 1
    # Check DB was called
    assert any("INSERT INTO track" in str(call) for call in mock_db.fetchval.mock_calls)

@pytest.mark.asyncio
async def test_process_file_missing_mbid_skip(scanner, mock_db):
    path = "/music/unknown.mp3"
    
    with patch.object(scanner, "_compute_quick_hash", return_value=b"h"):
        stat_mock = MagicMock()
        stat_mock.st_mtime = 1000
        stat_mock.st_size = 100
        
        with patch("os.stat", return_value=stat_mock):
            with patch("app.scanner.core.get_music_path", return_value="/music"):
                # Missing IDs
                with patch("app.scanner.core.extract_tags", return_value={"title": "Unknown", "artist": "None"}):
                         await scanner._process_file(path, mock_db, set(), False)
                         
    # Should NOT update DB
    assert len(mock_db.fetchval.mock_calls) == 0
    # Should have logged warning (hard to test without capturing logs, assume covered by skip logic logic)

@pytest.mark.asyncio
async def test_process_track_artists_upsert_order(scanner, mock_db):
    track_id = 123
    artist_mbid = "artist-guid"
    tags = {
        "artist_mbid": artist_mbid,
        "artist": "Test Artist"
    }
    artist_mbids = set()

    await scanner._process_track_artists(mock_db, track_id, tags, artist_mbids)

    # Convert calls to string for easy searching
    calls = [str(c) for c in mock_db.execute.mock_calls]
    
    # 1. DELETE FROM track_artist
    assert any("DELETE FROM track_artist" in c for c in calls)
    
    # 2. INSERT INTO artist (The Fix)
    upsert_artist_index = next((i for i, c in enumerate(calls) if "INSERT INTO artist" in c), -1)
    assert upsert_artist_index != -1, "Artist upsert not found"
    
    # 3. INSERT INTO track_artist
    link_artist_index = next((i for i, c in enumerate(calls) if "INSERT INTO track_artist" in c), -1)
    assert link_artist_index != -1, "Track_artist link not found"
    
    # Assert Order: Upsert Artist MUST be before Link Artist
    assert upsert_artist_index < link_artist_index, "Artist MUST be upserted before linking track_artist"
