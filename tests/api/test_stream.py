import pytest
import json
from httpx import AsyncClient, ASGITransport
from app.main import app
import os
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from jose import jwt
from app.api.stream import _calculate_normalization_gain_db
from app.audio_normalization import calculate_album_gain_db


def test_calculate_normalization_gain_attenuates_loud_track():
    gain = _calculate_normalization_gain_db(-6.0, -0.2)
    assert gain == pytest.approx(-10.0)


def test_calculate_normalization_gain_caps_quiet_track_boost():
    gain = _calculate_normalization_gain_db(-30.0, -12.0)
    assert gain == pytest.approx(6.0)


def test_calculate_normalization_gain_respects_true_peak_ceiling():
    gain = _calculate_normalization_gain_db(-20.0, 2.7)
    assert gain == pytest.approx(-3.7)


def test_calculate_album_gain_respects_hottest_album_true_peak():
    gain = calculate_album_gain_db(1.49, -0.2)
    assert gain == pytest.approx(-0.8)


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
async def test_stream_url_uses_album_gain_for_album_sequence(auth_client: AsyncClient, db):
    await db.execute(
        """
        INSERT INTO track (id, title, artist, album, album_artist, track_no, disc_no, path, duration_seconds)
        VALUES
            (1001, 'One', 'Album Artist', 'Album', 'Album Artist', 1, 1, '/tmp/one.flac', 100),
            (1002, 'Two', 'Album Artist', 'Album', 'Album Artist', 2, 1, '/tmp/two.flac', 100)
        """
    )
    await db.execute(
        """
        INSERT INTO track_audio_analysis (
            track_id, status, loudness_lufs, true_peak_db, replaygain_album_gain_db
        )
        VALUES
            (1001, 'complete', -19.4, -3.1, 1.49),
            (1002, 'complete', -18.9, -2.8, 1.49)
        """
    )
    queue = [
        {
            "id": 1001,
            "title": "One",
            "artist": "Album Artist",
            "album": "Album",
            "album_artist": "Album Artist",
            "track_no": 1,
            "disc_no": 1,
            "duration_seconds": 100,
        },
        {
            "id": 1002,
            "title": "Two",
            "artist": "Album Artist",
            "album": "Album",
            "album_artist": "Album Artist",
            "track_no": 2,
            "disc_no": 1,
            "duration_seconds": 100,
        },
    ]
    await db.execute(
        """
        INSERT INTO client_session (client_id, active_renderer_udn, active_renderer_id)
        VALUES ('album-client', 'local:album-client', 'local:album-client')
        """
    )
    await db.execute(
        """
        INSERT INTO renderer_state (renderer_udn, queue, current_index, is_playing)
        VALUES ('local:album-client', $1, 0, true)
        """,
        json.dumps(queue),
    )

    response = await auth_client.get(
        "/api/stream-url/1001",
        headers={"X-Jamarr-Client-Id": "album-client"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["loudness_gain_mode"] == "album"
    assert data["loudness_gain_db"] == pytest.approx(1.49)
    token = parse_qs(urlparse(data["url"]).query)["token"][0]
    claims = jwt.get_unverified_claims(token)
    assert claims["loudness_gain_mode"] == "album"
    assert claims["loudness_gain_db"] == pytest.approx(1.49)


@pytest.mark.asyncio
async def test_stream_url_clamps_album_gain_by_album_sequence_true_peak(auth_client: AsyncClient, db):
    await db.execute(
        """
        INSERT INTO track (id, title, artist, album, album_artist, track_no, disc_no, path, duration_seconds)
        VALUES
            (1011, 'One', 'Album Artist', 'Hot Album', 'Album Artist', 1, 1, '/tmp/one.flac', 100),
            (1012, 'Two', 'Album Artist', 'Hot Album', 'Album Artist', 2, 1, '/tmp/two.flac', 100)
        """
    )
    await db.execute(
        """
        INSERT INTO track_audio_analysis (
            track_id, status, loudness_lufs, true_peak_db, replaygain_album_gain_db
        )
        VALUES
            (1011, 'complete', -19.4, -3.1, 1.49),
            (1012, 'complete', -18.9, -0.2, 1.49)
        """
    )
    queue = [
        {
            "id": 1011,
            "title": "One",
            "artist": "Album Artist",
            "album": "Hot Album",
            "album_artist": "Album Artist",
            "track_no": 1,
            "disc_no": 1,
            "duration_seconds": 100,
        },
        {
            "id": 1012,
            "title": "Two",
            "artist": "Album Artist",
            "album": "Hot Album",
            "album_artist": "Album Artist",
            "track_no": 2,
            "disc_no": 1,
            "duration_seconds": 100,
        },
    ]
    await db.execute(
        """
        INSERT INTO client_session (client_id, active_renderer_udn, active_renderer_id)
        VALUES ('hot-album-client', 'local:hot-album-client', 'local:hot-album-client')
        """
    )
    await db.execute(
        """
        INSERT INTO renderer_state (renderer_udn, queue, current_index, is_playing)
        VALUES ('local:hot-album-client', $1, 0, true)
        """,
        json.dumps(queue),
    )

    response = await auth_client.get(
        "/api/stream-url/1011",
        headers={"X-Jamarr-Client-Id": "hot-album-client"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["loudness_gain_mode"] == "album"
    assert data["loudness_gain_db"] == pytest.approx(-0.8)
    token = parse_qs(urlparse(data["url"]).query)["token"][0]
    claims = jwt.get_unverified_claims(token)
    assert claims["loudness_gain_mode"] == "album"
    assert claims["loudness_gain_db"] == pytest.approx(-0.8)
