"""Planned renderer outputs served by /api/stream (issue #316).

The plan rides in the stream token; the endpoint must serve exactly that
format with a matching Content-Type, and keep Range / Content-Length.
"""

import subprocess
import wave
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from httpx import AsyncClient

from app.services.audio_streaming import build_stream_url
from app.services.playback_plan import RendererConstraints


def _make_flac(path, *, rate=44100, channels=2, sample_fmt="s16", seconds=1):
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}:sample_rate={rate}",
            "-ac", str(channels), "-sample_fmt", sample_fmt, "-c:a", "flac", str(path),
        ],
        check=True,
    )


async def _insert_track(db, track_id, path, *, rate, depth, channels, analysed=False):
    await db.execute(
        """
        INSERT INTO track (id, title, artist, album, path, duration_seconds,
                           codec, sample_rate_hz, bit_depth, channels)
        VALUES ($1, 'Tone', 'Artist', 'Album', $2, 1, 'FLAC', $3, $4, $5)
        """,
        track_id, str(path), rate, depth, channels,
    )
    if analysed:
        await db.execute(
            """
            INSERT INTO track_audio_analysis (track_id, status, loudness_lufs, true_peak_db)
            VALUES ($1, 'complete', -24.0, -6.0)
            """,
            track_id,
        )


def _claims(url):
    token = parse_qs(urlparse(url).query)["token"][0]
    return jwt.decode(token, options={"verify_signature": False})


@pytest.fixture
def stream_cache(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    monkeypatch.setenv("JAMARR_STREAM_CACHE_DIR", str(cache))
    return cache


@pytest.mark.asyncio
async def test_wav_output_headers_range_and_length(client: AsyncClient, db, tmp_path, stream_cache):
    path = tmp_path / "tone.flac"
    _make_flac(path)
    await _insert_track(db, 1301, path, rate=44100, depth=16, channels=2, analysed=True)

    stream = await build_stream_url(
        db,
        track_id=1301,
        renderer_kind="upnp",
        constraints=RendererConstraints(supported_mime_types=frozenset({"audio/x-wav", "audio/mpeg"})),
    )

    assert stream.plan is not None and stream.plan.output.format == "wav"
    assert stream.mime_type == "audio/wav"
    claims = _claims(stream.url)
    assert claims["out"] == "wav" and claims["out_mime"] == "audio/wav"

    full = await client.get(stream.url)
    assert full.status_code == 200, full.text
    assert full.headers["content-type"] == stream.mime_type
    assert full.headers["x-jamarr-output-format"] == "wav"
    assert full.headers["x-jamarr-loudness-normalized"] == "1"
    assert full.headers["accept-ranges"] == "bytes"
    body = await full.aread()
    assert int(full.headers["content-length"]) == len(body)
    assert body[:4] == b"RIFF" and body[8:12] == b"WAVE"
    assert len(list(stream_cache.glob("track-1301-*.wav"))) == 1

    head = await client.head(stream.url)
    assert head.status_code == 200
    assert head.headers["content-length"] == str(len(body))
    assert head.headers["content-type"] == "audio/wav"

    partial = await client.get(stream.url, headers={"Range": "bytes=100-199"})
    assert partial.status_code == 206
    assert partial.headers["content-length"] == "100"
    assert partial.headers["content-range"] == f"bytes 100-199/{len(body)}"
    assert await partial.aread() == body[100:200]

    # Same plan, same cache entry: no second transcode file.
    again = await client.get(stream.url)
    assert again.status_code == 200
    assert len(list(stream_cache.glob("track-1301-*"))) == 1


@pytest.mark.asyncio
async def test_resample_downmix_and_depth_follow_constraints(client: AsyncClient, db, tmp_path, stream_cache):
    path = tmp_path / "hires.flac"
    _make_flac(path, rate=96000, channels=6, sample_fmt="s32")
    await _insert_track(db, 1302, path, rate=96000, depth=24, channels=6)

    stream = await build_stream_url(
        db,
        track_id=1302,
        renderer_kind="cast",
        constraints=RendererConstraints(
            supported_mime_types=frozenset({"audio/wav"}),
            max_sample_rate_hz=48000,
            max_channels=2,
        ),
    )
    plan = stream.plan
    assert plan.output.sample_rate_hz == 48000 and plan.output.channels == 2
    assert set(plan.operations) == {"resample", "downmix"}

    response = await client.get(stream.url)
    assert response.status_code == 200, response.text
    out = tmp_path / "out.wav"
    out.write_bytes(await response.aread())
    with wave.open(str(out)) as w:
        assert w.getframerate() == 48000
        assert w.getnchannels() == 2
        assert w.getsampwidth() == 3  # 24-bit kept: only rate and channels had to change


@pytest.mark.asyncio
async def test_compatible_original_is_served_as_planned(client: AsyncClient, db, tmp_path, stream_cache):
    path = tmp_path / "plain.flac"
    _make_flac(path)
    await _insert_track(db, 1303, path, rate=44100, depth=16, channels=2)

    stream = await build_stream_url(
        db,
        track_id=1303,
        renderer_kind="upnp",
        constraints=RendererConstraints(supported_mime_types=frozenset({"audio/x-flac"})),
    )
    assert stream.plan.action == "original"
    assert stream.mime_type == "audio/flac"

    response = await client.get(stream.url)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/flac"
    assert response.headers["x-jamarr-output-format"] == "original"
    assert await response.aread() == path.read_bytes()
    assert not stream_cache.exists() or not list(stream_cache.glob("track-1303-*"))


@pytest.mark.asyncio
async def test_l16_output_carries_rate_and_channels(client: AsyncClient, db, tmp_path, stream_cache):
    path = tmp_path / "l16.flac"
    _make_flac(path, rate=48000)
    await _insert_track(db, 1304, path, rate=48000, depth=16, channels=2)

    stream = await build_stream_url(
        db,
        track_id=1304,
        renderer_kind="upnp",
        constraints=RendererConstraints(supported_mime_types=frozenset({"audio/L16"})),
    )
    assert stream.mime_type == "audio/L16;rate=48000;channels=2"

    response = await client.get(stream.url)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].replace(" ", "").lower() == "audio/l16;rate=48000;channels=2"
    body = await response.aread()
    # Raw big-endian PCM: 1 s * 48000 frames * 2 channels * 2 bytes.
    assert len(body) == 48000 * 2 * 2
    assert int(response.headers["content-length"]) == len(body)


@pytest.mark.asyncio
async def test_flac_block_constraint_reblocks_the_stream(client: AsyncClient, db, tmp_path, stream_cache):
    import mutagen.flac

    path = tmp_path / "bigblocks.flac"
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1:sample_rate=96000",
            "-c:a", "flac", "-frame_size", "8192", str(path),
        ],
        check=True,
    )
    assert mutagen.flac.FLAC(str(path)).info.max_blocksize == 8192
    await _insert_track(db, 1305, path, rate=96000, depth=16, channels=1)

    stream = await build_stream_url(
        db,
        track_id=1305,
        renderer_kind="cast",
        constraints=RendererConstraints(
            supported_mime_types=frozenset({"audio/flac"}), flac_max_block_size=4608
        ),
    )
    assert stream.plan.action == "decode"
    assert stream.mime_type == "audio/flac"

    response = await client.get(stream.url)
    assert response.status_code == 200, response.text
    out = tmp_path / "reblocked.flac"
    out.write_bytes(await response.aread())
    info = mutagen.flac.FLAC(str(out)).info
    assert info.max_blocksize <= 4608
    assert info.min_blocksize == info.max_blocksize
    assert info.sample_rate == 96000


@pytest.mark.asyncio
async def test_build_stream_url_without_constraints_is_unchanged(db, tmp_path):
    path = tmp_path / "legacy.flac"
    _make_flac(path)
    await _insert_track(db, 1306, path, rate=44100, depth=16, channels=2)

    stream = await build_stream_url(db, track_id=1306)
    assert stream.plan is None
    assert "out" not in _claims(stream.url)
