import pytest
import json
from httpx import AsyncClient, ASGITransport
from app.main import app
import os
import subprocess
import wave
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import jwt

from app.api.stream import _calculate_normalization_gain_db
from app.audio_normalization import calculate_album_gain_db
from app.services.stream_profiles import (
    cleanup_stream_cache,
    next_lower_quality,
    normalize_quality,
    original_quality_label,
)


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
    claims = jwt.decode(token, options={"verify_signature": False})
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
    claims = jwt.decode(token, options={"verify_signature": False})
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
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["loudness_gain_mode"] == "album"
    assert claims["loudness_gain_db"] == pytest.approx(-0.8)


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
    claims = jwt.decode(token, options={"verify_signature": False})
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


@pytest.fixture
async def normalizable_track(db, tmp_path):
    """A real (short) FLAC plus a completed analysis row.

    The normalized path shells out to ffmpeg, so unlike the other fixtures
    here it needs decodable audio rather than a dummy byte blob.
    """
    path = tmp_path / "tone.flac"
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:a", "flac", str(path),
        ],
        check=True,
    )
    await db.execute(
        """
        INSERT INTO track (id, title, artist, album, path, duration_seconds,
                           codec, sample_rate_hz, bit_depth)
        VALUES (1201, 'Tone', 'Artist', 'Album', $1, 1, 'FLAC', 44100, 16)
        """,
        str(path),
    )
    await db.execute(
        """
        INSERT INTO track_audio_analysis (track_id, status, loudness_lufs, true_peak_db)
        VALUES (1201, 'complete', -24.0, -6.0)
        """
    )
    yield str(path)


@pytest.mark.asyncio
async def test_normalized_stream_applies_gain_and_advertises_it(
    auth_client: AsyncClient, db, normalizable_track
):
    response = await auth_client.get("/api/stream/1201")

    assert response.status_code == 200
    assert response.headers["x-jamarr-loudness-normalized"] == "1"
    assert response.headers["x-jamarr-loudness-gain-mode"] == "track"
    # -24 LUFS against a -16 target wants +8 dB, which the +6 dB max boost caps
    # and the -1 dBTP ceiling then clamps to +5 against the track's -6 dBTP peak.
    assert float(response.headers["x-jamarr-loudness-gain-db"]) == pytest.approx(5.0)
    assert response.headers["x-jamarr-stream-quality"] == "original"
    assert response.headers["content-type"] == "audio/flac"
    body = await response.aread()
    assert body.startswith(b"fLaC")


@pytest.mark.asyncio
async def test_normalized_stream_honours_requested_quality_profile(
    auth_client: AsyncClient, db, normalizable_track
):
    """Gain and transcode compose: the body must be the requested codec, not
    FLAC, or a normalized mobile stream would silently ship lossless bytes."""
    response = await auth_client.get("/api/stream/1201?quality=mp3_320")

    assert response.status_code == 200
    assert response.headers["x-jamarr-loudness-normalized"] == "1"
    assert response.headers["x-jamarr-stream-quality"] == "mp3_320"
    assert response.headers["content-type"] == "audio/mpeg"
    body = await response.aread()
    assert len(body) > 0
    assert not body.startswith(b"fLaC")


@pytest.mark.asyncio
async def test_normalization_can_be_disabled_per_request(
    auth_client: AsyncClient, db, normalizable_track
):
    response = await auth_client.get("/api/stream/1201?normalize=0")

    assert response.status_code == 200
    assert "x-jamarr-loudness-normalized" not in response.headers


@pytest.mark.asyncio
async def test_normalized_stream_is_seekable(
    auth_client: AsyncClient, db, normalizable_track, tmp_path, monkeypatch
):
    """Normalized responses must be range-serveable.

    Generating them per request made the response a bodiless stream: the
    browser could not seek, and every re-request re-encoded the whole track.
    """
    monkeypatch.setenv("JAMARR_STREAM_CACHE_DIR", str(tmp_path / "cache"))

    full = await auth_client.get("/api/stream/1201")
    assert full.status_code == 200
    assert full.headers["accept-ranges"] == "bytes"
    assert int(full.headers["content-length"]) > 0

    partial = await auth_client.get("/api/stream/1201", headers={"Range": "bytes=0-99"})
    assert partial.status_code == 206
    assert partial.headers["content-length"] == "100"
    assert partial.headers["x-jamarr-loudness-normalized"] == "1"


@pytest.mark.asyncio
async def test_normalized_stream_reuses_its_cache_entry(
    auth_client: AsyncClient, db, normalizable_track, tmp_path, monkeypatch
):
    """Same track, quality and gain mode must resolve to one cache file."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("JAMARR_STREAM_CACHE_DIR", str(cache_dir))

    first = await auth_client.get("/api/stream/1201")
    assert first.status_code == 200
    entries = sorted(p.name for p in cache_dir.glob("track-1201-*"))
    assert len(entries) == 1

    second = await auth_client.get("/api/stream/1201")
    assert second.status_code == 200
    assert sorted(p.name for p in cache_dir.glob("track-1201-*")) == entries


def test_quality_ladder_skips_rungs_that_would_not_shrink_the_source():
    """A CD-quality source must not "downgrade" onto FLAC 24/48.

    That rung resamples 44.1k up to 48k and pads 16-bit to 24, landing ~69%
    larger than the source -- the opposite of what a stall response needs.
    """
    cd_quality = {"sample_rate_hz": 44100, "bit_depth": 16}

    assert next_lower_quality("original", cd_quality) == "mp3_320"
    assert next_lower_quality("mp3_320", cd_quality) == "opus_128"


def test_quality_ladder_keeps_lossless_rungs_for_hi_res_sources():
    hi_res = {"sample_rate_hz": 96000, "bit_depth": 24}

    assert next_lower_quality("original", hi_res) == "flac_24_48"
    assert next_lower_quality("flac_24_48", hi_res) == "flac_16_48"


def test_quality_ladder_skips_equal_rate_lossless_rung():
    """24/48 source: FLAC 24/48 is a pointless re-encode, 16/48 is a real cut."""
    same_as_rung = {"sample_rate_hz": 48000, "bit_depth": 24}

    assert next_lower_quality("original", same_as_rung) == "flac_16_48"


def test_quality_ladder_is_unchanged_without_source_details():
    assert next_lower_quality("original") == "flac_24_48"
    assert next_lower_quality("original", {"sample_rate_hz": None, "bit_depth": None}) == "flac_24_48"
