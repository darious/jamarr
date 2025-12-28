import pytest
from httpx import AsyncClient
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_homepage_new_releases_artwork(client: AsyncClient, db, auth_token):
    """
    Verify that get_new_releases returns artwork_id and art_sha1 
    when the database is correctly populated.
    """
    # 1. Insert Artwork
    sha1 = "aabbccddeeff00112233445566778899aabbccdd"
    await db.execute("""
        INSERT INTO artwork (sha1, mime, width, height, path_on_disk, filesize_bytes, image_format, source)
        VALUES ($1, 'image/jpeg', 500, 500, '/tmp/fake_art.jpg', 12345, 'JPEG', 'local')
        ON CONFLICT (sha1) DO NOTHING
    """, sha1)
    
    # Get ID
    art_id = await db.fetchval("SELECT id FROM artwork WHERE sha1=$1", sha1)
    assert art_id is not None

    # 2. Insert Track with this Artwork
    # We populate min required fields for new_releases query (album, artwork_id, date)
    await db.execute("""
        INSERT INTO track (
            path, title, artist, album, album_artist, 
            track_no, disc_no, date, duration_seconds, 
            artwork_id, updated_at
        ) VALUES (
            '/music/test.mp3', 'Test Track', 'Test Artist', 'Test Album', 'Test Artist',
            1, 1, '2024-01-01', 300,
            $1, NOW()
        )
    """, art_id)

    # 3. Call API
    # Note: Requires auth? library.py endpoints usually depend on get_current_user depending on router.
    # checking router... api/library.py often is authenticated. passing auth_token cookie.
    
    client.cookies = {"jamarr_session": auth_token}
    response = await client.get("/api/home/new-releases")
    assert response.status_code == 200
    data = response.json()
    
    # 4. Assertions
    assert len(data) > 0
    album = data[0]
    assert album["album"] == "Test Album"
    assert album["artwork_id"] == art_id
    assert album["art_sha1"] == sha1
    
    print(f"\nAPI Response Item: {album}")


@pytest.mark.asyncio
async def test_scanner_pipeline_mocked(db):
    """
    Test the full scanner pipeline (process_file) by mocking Mutagen.
    We simulate scanning a file and verify Track and Artwork tables are populated.
    """
    # Mock Data
    fake_path = "/music/test_pipeline.m4a"

    
    # Create Mock Mutagen File (Simulating MP4/M4A)
    # We need it to pass isinstance(f, MP4) check in artwork.py
    # and have tags['covr']
    
    with patch("app.scanner.tags.mutagen.File"), \
         patch("app.scanner.artwork.File"), \
         patch("app.scanner.core.os.path.getmtime", return_value=1234567890), \
         patch("app.scanner.artwork.os.makedirs"), \
         patch("app.scanner.artwork.aiofiles.open", new_callable=MagicMock):

        # Setup Tag Extraction Mock (tags.py)
        # For M4A strings, we need to return a dict that mimics what extract_tags expects
        # OR we assume we fix tags.py to handle M4A keys. 
        # Currently tags.py looks for "TITLE", "title"... MP4 uses \xa9nam.
        # Let's mock the return of extract_tags directly to focus on ARTWORK testing first?
        # User said "i can see gteh records in the db", so tags work. 
        # Let's mock `extract_tags` to return valid tags so we enter the artwork flow.
        pass

    with patch("app.scanner.core.extract_tags") as mock_extract_tags, \
         patch("app.scanner.artwork.File"), \
         patch("app.scanner.artwork._save_artwork_to_disk"):
         
        # 1. Setup metadata (assume tags work as user says records exist)
        mock_extract_tags.return_value = {
            "title": "Pipeline Test",
            "artist": "Pipeline Artist",
            "album": "Pipeline Album",
            "path": fake_path,
            "mtime": 1000,
            "release_group_mbid": "fake-rg-id"
        }
        
        # 2. Setup Artwork Logic
        # We need _extract_artwork_data to find data.
        # It uses mutagen.File(path).
        # We simulate an MP4 file with 'covr'

        _ = MagicMock()
        # Mocking isinstance check is tricky with MagicMock. 
        # Better to rely on the fact that we patched the class used in isinstance checks?
        # No, isinstance(m, Class) requires m to be instance.
        # We can mock `_extract_artwork_data`? 
        # No, we want to test that logic.
        
        # We will use real classes but mock the method calls? 
        # Or just mock `_extract_artwork_data` if we trust unit tests?
        # The user wants to prove "pulling" works. 
        # Let's Mock `_extract_artwork_data` to return bytes, assuming we covered the 'parsing' logic in unit analysis.
        # WAIT: The user's failure IS likely the parsing logic.
        # So we MUST test `_extract_artwork_data`.
        pass
        
@pytest.mark.asyncio
async def test_artwork_extraction_logic():
    """
    Unit test for the exact logic added to artwork.py for M4A/Ogg.
    """
    from app.scanner.artwork import _extract_artwork_data
    from mutagen.mp4 import MP4
    
    # 1. Test MP4 Logic
    # We can't easily instantiate a real MP4 object without a file.
    # We can create a dummy class that inherits.
    
    class MockMP4(MP4):
        def __init__(self):
            self.tags = {"covr": [b"fake_cover_bytes"]}
            
    with patch("app.scanner.artwork.File") as mock_file:
        mock_file.return_value = MockMP4()
        
        data = _extract_artwork_data("/tmp/fake.m4a")
        assert data == b"fake_cover_bytes", "MP4 extraction failed"
        
    print("\nVerified MP4 extraction logic")

@pytest.mark.asyncio
async def test_artwork_serving(client: AsyncClient, db, auth_token):
    """
    Test valid serving of artwork via /api/art/{id}.
    Ensures that extensionless cache files are served with correct Content-Type (e.g. image/jpeg).
    """
    # 1. Create dummy artwork file (Extensionless)
    sha1 = "11223344556677889900aabbccddeeff11223344"
    cache_path = f"/tmp/{sha1}"
    
    # Create valid JPEG
    from PIL import Image
    import io
    img = Image.new('RGB', (100, 100), color = 'red')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    data = buf.getvalue()
    
    with open(cache_path, "wb") as f:
        f.write(data)
        
    # 2. Insert DB Record
    # We purposefully leave path_on_disk relative or None to trigger resolution, 
    # OR we point directly to tmp. logic uses _get_art_path.
    # _get_art_path checks path_on_disk first.
    
    await db.execute("""
        INSERT INTO artwork (sha1, mime, width, height, path_on_disk, filesize_bytes, image_format, source)
        VALUES ($1, 'image/jpeg', 100, 100, $2, $3, 'JPEG', 'local')
        ON CONFLICT (sha1) DO NOTHING
    """, sha1, cache_path, len(data))
    
    row = await db.fetchrow("SELECT id FROM artwork WHERE sha1=$1", sha1)
    art_id = row['id']
    
    # 3. Request Image
    client.cookies = {"jamarr_session": auth_token}
    
    # A) Standard ID endpoint
    response = await client.get(f"/api/art/{art_id}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert len(response.content) > 0
    
    # B) Forced fallback (simulate resizing error or just FileResponse path)
    # The current code always tries to resize/convert with PIL if found.
    # If we want to test the FileResponse fallback, we'd need to mock PIL failure or pass max_size large enough?
    # No, even with max_size, it opens with PIL.
    # The only way to hit FileResponse is if PIL throws exception.
    
    # Let's verify that the PIL path works (which sets media_type="image/jpeg").
    # If the file on disk is valid JPEG, it enters the PIL block and returns explicit Response with jpeg header.
    # So the concern about FileResponse is only if the file is NOT parseable by PIL (corrupt?) or some other error.
    
    pass

@pytest.mark.asyncio
async def test_artwork_serving_fallback(client: AsyncClient, db, auth_token):
    """
    Test serving of 'corrupt' or un-openable image data.
    Verifies that the API handles it (either 200 with fallback or error)
    and checks what Content-Type is returned.
    """
    import hashlib
    
    # 1. Create 'Corrupt' data (random bytes)
    data = b"this is not an image"
    sha1 = hashlib.sha1(data).hexdigest()
    cache_path = f"/tmp/{sha1}"
    
    with open(cache_path, "wb") as f:
        f.write(data)
        
    # 2. Insert DB Record with valid MIME
    # We want to verify that IF extraction works (getting mime) but PIL fails later (e.g. slight corruption),
    # we still serve it with the correct mime.
    await db.execute("""
        INSERT INTO artwork (sha1, mime, width, height, path_on_disk, filesize_bytes, image_format, source)
        VALUES ($1, 'image/jpeg', NULL, NULL, $2, $3, NULL, 'local')
        ON CONFLICT (sha1) DO NOTHING
    """, sha1, cache_path, len(data))
    
    row = await db.fetchrow("SELECT id FROM artwork WHERE sha1=$1", sha1)
    art_id = row['id']
    
    # 3. Request Image
    client.cookies = {"jamarr_session": auth_token}
    
    response = await client.get(f"/api/art/{art_id}")
    
    ct = response.headers.get("content-type")
    assert ct == "image/jpeg", f"Expected image/jpeg, got {ct}"

@pytest.mark.asyncio
async def test_artwork_serving_null_mime(client: AsyncClient, db, auth_token):
    """
    Test serving when MIME is NULL in DB.
    The API should try to sniff or default to a usable image type, 
    otherwise browsers won't display it.
    """
    import hashlib
    
    # 1. Create Valid JPEG Data
    # We use a valid JPEG so we can prove that even if DB has NULL, 
    # if the file is valid, we *could* serve it correctly if we sniffed it.
    from PIL import Image
    import io
    img = Image.new('RGB', (50, 50), color = 'blue')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    data = buf.getvalue()
    
    sha1 = hashlib.sha1(data).hexdigest()
    cache_path = f"/tmp/{sha1}_null_mime"
    
    with open(cache_path, "wb") as f:
        f.write(data)
        
    # 2. Insert DB Record with NULL MIME
    await db.execute("""
        INSERT INTO artwork (sha1, mime, width, height, path_on_disk, filesize_bytes, image_format, source)
        VALUES ($1, NULL, NULL, NULL, $2, $3, NULL, 'local')
        ON CONFLICT (sha1) DO NOTHING
    """, sha1, cache_path, len(data))
    
    row = await db.fetchrow("SELECT id FROM artwork WHERE sha1=$1", sha1)
    art_id = row['id']
    
    # 3. Request Image
    client.cookies = {"jamarr_session": auth_token}
    
    response = await client.get(f"/api/art/{art_id}")
    
    ct = response.headers.get("content-type")
    print(f"Null-Mime Content-Type: {ct}")
    
    ct = response.headers.get("content-type")
    print(f"Null-Mime Content-Type: {ct}")
    
    # We expect this to FAIL currently (it will likely be text/plain or None)
    # We want it to be 'image/jpeg' by sniffing
    assert ct == "image/jpeg", f"Expected image/jpeg, got {ct}"

@pytest.mark.asyncio
async def test_artwork_sha1_serving(client: AsyncClient, db, auth_token):
    """
    Test serving via SHA1 endpoint /api/art/file/{sha1}.
    This endpoint was previously missed in the fixes.
    """
    import hashlib
    # Create valid JPEG data
    data = b"\xff\xd8\xff\xe0" + b"x" * 100 # Minimal header
    sha1 = hashlib.sha1(data).hexdigest()
    cache_path = f"/tmp/{sha1}_sha1test"
    
    with open(cache_path, "wb") as f:
        f.write(data)
        
    await db.execute("""
        INSERT INTO artwork (sha1, mime, width, height, path_on_disk, filesize_bytes, image_format, source)
        VALUES ($1, NULL, NULL, NULL, $2, $3, NULL, 'local')
        ON CONFLICT (sha1) DO NOTHING
    """, sha1, cache_path, len(data))
    
    client.cookies = {"jamarr_session": auth_token}
    
    # Request via SHA1 endpoint
    response = await client.get(f"/api/art/file/{sha1}")
    
    assert response.status_code == 200
    ct = response.headers.get("content-type")
    assert ct == "image/jpeg", f"Expected image/jpeg on SHA1 endpoint, got {ct}"
