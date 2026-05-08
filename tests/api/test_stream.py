import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
import os
import wave
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from jose import jwt

from app.services.stream_profiles import (
    cleanup_stream_cache,
    next_lower_quality,
    normalize_quality,
    original_quality_label,
)

@pytest.fixture
async def stream_data(db):
    """
    Insert a track with a known path. 
    Notes: 
    - In the docker test environment, we don't have real audio files mounted in the test DB.
    - However, the API server needs to read a file from disk.
    - We will use a dummy file.
    """
    # Create a dummy file
    dummy_path = "/tmp/test_stream.mp3"
    with open(dummy_path, "wb") as f:
        # random bytes of 1000 length
        f.write(b"0" * 1000)

    # Insert track pointing to this file
    await db.execute("""
        INSERT INTO track (id, title, artist, album, path, duration_seconds)
        VALUES (999, 'Stream Song', 'Stream Artist', 'Stream Album', $1, 100)
    """, dummy_path)

    yield dummy_path
    
    # Cleanup
    if os.path.exists(dummy_path):
        os.remove(dummy_path)


@pytest.mark.asyncio
async def test_stream_full_content(auth_client: AsyncClient, db, stream_data):
    # Test getting the full file
    response = await auth_client.get("/api/stream/999")
    assert response.status_code == 200
    assert response.headers["content-type"] in ["audio/mpeg", "audio/mp3", "application/octet-stream"]
    assert response.headers["content-length"] == "1000"
    content = await response.aread()
    assert len(content) == 1000


@pytest.mark.asyncio
async def test_stream_range_request(auth_client: AsyncClient, db, stream_data):
    # Test Range request: bytes=0-499 (First 500 bytes)
    headers = {"Range": "bytes=0-499"}
    response = await auth_client.get("/api/stream/999", headers=headers)
    
    assert response.status_code == 206 # Partial Content
    assert response.headers["content-length"] == "500"
    assert "bytes 0-499/1000" in response.headers["content-range"]
    content = await response.aread()
    assert len(content) == 500

    # Test Range request: bytes=500- (Last 500 bytes)
    headers = {"Range": "bytes=500-"}
    response = await auth_client.get("/api/stream/999", headers=headers)
    assert response.status_code == 206
    assert response.headers["content-length"] == "500"
    assert "bytes 500-999/1000" in response.headers["content-range"]

@pytest.mark.asyncio
async def test_stream_head_request(auth_client: AsyncClient, db, stream_data):
    # Test HEAD request (metadata only)
    response = await auth_client.head("/api/stream/999")
    assert response.status_code == 200
    assert response.headers["content-length"] == "1000"
    assert response.headers["accept-ranges"] == "bytes"

@pytest.mark.asyncio
async def test_stream_not_found(auth_client: AsyncClient, db):
    response = await auth_client.get("/api/stream/999999")
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_stream_invalid_range(auth_client: AsyncClient, db, stream_data):
    # Range outside of file
    headers = {"Range": "bytes=2000-3000"}
    response = await auth_client.get("/api/stream/999", headers=headers)
    # Standard behavior for satisfiable range is 416, but some frameworks default to sending full file or 200.
    # We expect 416 Range Not Satisfiable
    assert response.status_code == 416


@pytest.mark.asyncio
async def test_stream_url_token_access(client: AsyncClient, auth_client: AsyncClient, db, stream_data):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as unauth_client:
        unauth_response = await unauth_client.get("/api/stream-url/999")
        assert unauth_response.status_code == 401

    response = await auth_client.get("/api/stream-url/999")
    assert response.status_code == 200
    data = response.json()
    assert data["url"].startswith("/api/stream/999?token=")

    token_response = await client.get(data["url"])
    assert token_response.status_code == 200


@pytest.mark.asyncio
async def test_stream_url_cast_token_uses_renderer_policy(auth_client: AsyncClient, db, stream_data):
    response = await auth_client.get("/api/stream-url/999?renderer_kind=cast")

    assert response.status_code == 200
    token = parse_qs(urlparse(response.json()["url"]).query)["token"][0]
    claims = jwt.get_unverified_claims(token)
    issued_at = datetime.fromtimestamp(claims["iat"], tz=timezone.utc)
    expires_at = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
    assert (expires_at - issued_at).total_seconds() == 1800


@pytest.mark.asyncio
async def test_stream_url_quality_claims(auth_client: AsyncClient, db, stream_data):
    await db.execute(
        """
        UPDATE track
        SET codec = 'FLAC', sample_rate_hz = 96000, bit_depth = 24
        WHERE id = 999
        """
    )

    response = await auth_client.get("/api/stream-url/999?quality=flac_16_48")

    assert response.status_code == 200
    data = response.json()
    assert data["stream_quality"] == "flac_16_48"
    assert data["stream_quality_label"] == "FLAC 16/48"
    assert data["stream_mime_type"] == "audio/flac"
    assert data["original_quality_label"] == "FLAC 24 bit 96 kHz"
    token = parse_qs(urlparse(data["url"]).query)["token"][0]
    claims = jwt.get_unverified_claims(token)
    assert claims["stream_quality"] == "flac_16_48"


@pytest.mark.asyncio
async def test_profile_stream_transcodes_to_cache(auth_client: AsyncClient, db, tmp_path, monkeypatch):
    source_path = tmp_path / "source.wav"
    with wave.open(str(source_path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(44100)
        f.writeframes(b"\x00\x00" * 4410)

    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("JAMARR_STREAM_CACHE_DIR", str(cache_dir))
    await db.execute(
        """
        INSERT INTO track (
            id, title, artist, album, path, duration_seconds,
            codec, sample_rate_hz, bit_depth
        )
        VALUES (1000, 'Profile Song', 'Stream Artist', 'Stream Album', $1, 0.1, 'WAV', 44100, 16)
        """,
        str(source_path),
    )

    url_response = await auth_client.get("/api/stream-url/1000?quality=flac_16_48")
    assert url_response.status_code == 200

    stream_response = await auth_client.get(url_response.json()["url"])

    assert stream_response.status_code == 200, stream_response.text
    assert stream_response.headers["content-type"].startswith("audio/flac")
    assert stream_response.headers["x-jamarr-stream-quality"] == "flac_16_48"
    assert stream_response.headers["accept-ranges"] == "bytes"
    assert list(cache_dir.glob("track-1000-*-flac_16_48.flac"))


def test_stream_quality_ladder_reaches_opus_floor():
    assert next_lower_quality("original") == "flac_24_48"
    assert next_lower_quality("flac_24_48") == "flac_16_48"
    assert next_lower_quality("flac_16_48") == "mp3_320"
    assert next_lower_quality("mp3_320") == "opus_128"
    assert next_lower_quality("opus_128") == "opus_128"
    assert normalize_quality("mobile") == "opus_128"
    assert normalize_quality("bad") == "original"


def test_original_quality_label_uses_codec_bit_depth_and_sample_rate():
    assert original_quality_label(
        {"path": "/music/song.flac", "codec": "FLAC", "bit_depth": 24, "sample_rate_hz": 96000}
    ) == "FLAC 24 bit 96 kHz"
    assert original_quality_label(
        {"path": "/music/song.mp3", "codec": "MPEG Audio", "sample_rate_hz": 44100}
    ) == "MP3 44.1 kHz"


@pytest.mark.asyncio
async def test_stream_cache_cleanup_removes_old_and_oversized_files(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    base_time = 1_000_000
    old_file = cache_dir / "track-1-old-flac_16_48.flac"
    keep_file = cache_dir / "track-2-keep-flac_16_48.flac"
    large_file = cache_dir / "track-3-large-mp3_320.mp3"
    old_file.write_bytes(b"old")
    keep_file.write_bytes(b"keep")
    large_file.write_bytes(b"x" * 16)

    os.utime(old_file, (base_time, base_time))
    os.utime(keep_file, (base_time + 100, base_time + 100))
    os.utime(large_file, (base_time + 200, base_time + 200))

    monkeypatch.setenv("JAMARR_STREAM_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("JAMARR_STREAM_CACHE_MAX_AGE_SECONDS", "150")
    monkeypatch.setenv("JAMARR_STREAM_CACHE_MAX_BYTES", "20")
    monkeypatch.setattr("app.services.stream_profiles.time.time", lambda: base_time + 200)

    await cleanup_stream_cache(force=True)

    assert not old_file.exists()
    assert keep_file.exists()
    assert large_file.exists()

    monkeypatch.setenv("JAMARR_STREAM_CACHE_MAX_AGE_SECONDS", "999999")
    monkeypatch.setenv("JAMARR_STREAM_CACHE_MAX_BYTES", "16")
    monkeypatch.setattr("app.services.stream_profiles.time.time", lambda: base_time + 300)

    await cleanup_stream_cache(force=True)

    assert not keep_file.exists()
    assert large_file.exists()
