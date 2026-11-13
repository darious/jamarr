"""Hiding a FLAC's TRACKNUMBER tag from renderers that show it as the title.

Naim firmware 3.13 does (see app/media/flac_tags.py). The tag is renamed in
the bytes served, one byte, so size, offsets and Range behaviour stay put.
"""

import struct

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.routing import Route

import app.config as app_config
from app.media.flac_tags import PatchedFileResponse, track_number_patches
from tests.unit.test_upnp_protocol_negotiation import META, ScriptedDmr, _control

AUDIO = bytes(range(256)) * 8


def _block(block_type: int, body: bytes, last: bool = False) -> bytes:
    return bytes([block_type | (0x80 if last else 0)]) + len(body).to_bytes(3, "big") + body


def _comments(*entries: bytes) -> bytes:
    vendor = b"reference libFLAC 1.4.3"
    out = struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", len(entries))
    for entry in entries:
        out += struct.pack("<I", len(entry)) + entry
    return out


def _flac(*entries: bytes, picture: bytes = b"\x00" * 300) -> bytes:
    return (
        b"fLaC"
        + _block(0, b"\x11" * 34)  # STREAMINFO (contents not parsed)
        + _block(6, picture)  # PICTURE before the comments: must be skipped
        + _block(4, _comments(*entries), last=True)
        + AUDIO
    )


TAGS = (b"TITLE=The Visitor", b"TRACKNUMBER=7", b"TRACKTOTAL=10", b"DISCNUMBER=1")


def _renamed(data: bytes) -> bytes:
    return data.replace(b"TRACKNUMBER=7", b"XRACKNUMBER=7")


@pytest.fixture
def flac_file(tmp_path):
    path = tmp_path / "track.flac"
    path.write_bytes(_flac(*TAGS))
    return path


# --- finding the tag -----------------------------------------------------------


def test_patch_renames_only_the_tracknumber_key(flac_file):
    data = flac_file.read_bytes()
    patches = track_number_patches(flac_file)
    assert patches == {data.index(b"TRACKNUMBER="): b"X"}


def test_lowercase_key_keeps_its_case(tmp_path):
    path = tmp_path / "lower.flac"
    path.write_bytes(_flac(b"title=x", b"tracknumber=3"))
    data = path.read_bytes()
    assert track_number_patches(path) == {data.index(b"tracknumber="): b"x"}


@pytest.mark.parametrize(
    "content",
    [
        b"ID3\x04" + b"\x00" * 100,  # not FLAC
        _flac(b"TITLE=No number", b"TRACKTOTAL=10"),  # no TRACKNUMBER
        _flac(*TAGS)[:60],  # truncated inside the comment block
        b"fLaC" + _block(0, b"\x11" * 34, last=True) + AUDIO,  # no comment block
    ],
)
def test_nothing_to_patch(tmp_path, content):
    path = tmp_path / "x.flac"
    path.write_bytes(content)
    assert track_number_patches(path) == {}


def test_missing_file_is_nothing_to_patch(tmp_path):
    assert track_number_patches(tmp_path / "gone.flac") == {}


# --- serving it ------------------------------------------------------------------


def _client(path, chunk_size=None):
    async def endpoint(request):
        response = PatchedFileResponse(
            path, patches=track_number_patches(path), media_type="audio/flac"
        )
        if chunk_size:
            response.chunk_size = chunk_size
        return response

    app = Starlette(routes=[Route("/f", endpoint, methods=["GET", "HEAD"])])
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.parametrize("chunk_size", [None, 5])  # 5: the patch lands mid-stream
async def test_full_body_is_the_file_with_one_byte_renamed(flac_file, chunk_size):
    original = flac_file.read_bytes()
    async with _client(flac_file, chunk_size) as client:
        response = await client.get("/f")
    assert response.status_code == 200
    assert response.content == _renamed(original)
    assert response.headers["content-length"] == str(len(original))


async def test_ranges_are_patched_by_absolute_offset(flac_file):
    original = flac_file.read_bytes()
    expected = _renamed(original)
    offset = original.index(b"TRACKNUMBER=")
    async with _client(flac_file, chunk_size=3) as client:
        across = await client.get("/f", headers={"Range": f"bytes={offset - 2}-{offset + 4}"})
        after = await client.get("/f", headers={"Range": f"bytes={offset + 1}-"})
        multi = await client.get("/f", headers={"Range": f"bytes=0-3,{offset}-{offset}"})
    assert across.status_code == 206
    assert across.content == expected[offset - 2 : offset + 5]
    assert after.content == original[offset + 1 :]  # untouched past the byte
    assert multi.status_code == 206
    assert b"fLaC" in multi.content and b"\r\n\r\nX\r\n" in multi.content


async def test_head_and_etag(flac_file):
    async with _client(flac_file) as client:
        head = await client.head("/f")
    assert head.status_code == 200
    assert head.headers["content-length"] == str(flac_file.stat().st_size)
    assert head.headers["etag"].endswith('-tn"')  # not the untouched file's tag


async def test_pathsend_is_not_used_for_patched_bodies(flac_file):
    """pathsend would hand the raw file to the server, skipping the patch."""
    response = PatchedFileResponse(
        flac_file, patches=track_number_patches(flac_file), media_type="audio/flac"
    )
    sent = []

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "headers": [],
        "asgi": {"spec_version": "2.4"},
        "extensions": {"http.response.pathsend": {}},
    }
    await response(scope, receive, send)
    assert all(m["type"] != "http.response.pathsend" for m in sent)
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert body == _renamed(flac_file.read_bytes())


# --- config and the UPnP stream URL --------------------------------------------------


def test_config_lists_udns_with_or_without_prefixes(monkeypatch):
    monkeypatch.setattr(
        app_config,
        "_config",
        {"renderer": {"upnp_hide_track_number": ["uuid:AAA-1", "upnp:bbb-2", "ccc-3"]}},
    )
    for udn in ("uuid:aaa-1", "aaa-1", "upnp:uuid:bbb-2", "uuid:bbb-2", "uuid:ccc-3"):
        assert app_config.upnp_hide_track_number(udn), udn
    assert not app_config.upnp_hide_track_number("uuid:other")


def test_config_absent_or_malformed_is_off(monkeypatch):
    monkeypatch.setattr(app_config, "_config", {"renderer": {}})
    assert not app_config.upnp_hide_track_number("uuid:aaa")
    monkeypatch.setattr(app_config, "_config", {"renderer": {"upnp_hide_track_number": "uuid:aaa"}})
    assert not app_config.upnp_hide_track_number("uuid:aaa")


async def test_listed_renderer_gets_the_flag_on_load_and_staging(monkeypatch):
    udn = "uuid:naim-atom"
    monkeypatch.setattr(app_config, "_config", {"renderer": {"upnp_hide_track_number": [udn]}})
    dmr = ScriptedDmr()
    control = _control(udn, dmr, sink=("http-get:*:audio/flac:*",))

    await control.play_track(7, "/m/7.flac", dict(META))
    staged = await control.set_next_track(udn, 8, dict(META))

    assert dmr.set_calls[0]["media_url"].endswith("&hide_tracknumber=1")
    assert dmr.next_calls[0]["media_url"].endswith("&hide_tracknumber=1")
    assert staged.endswith("&hide_tracknumber=1")
    # The DIDL names the same URL the renderer will fetch.
    assert "hide_tracknumber=1</res>" in dmr.set_calls[0]["meta_data"]


async def test_other_renderers_keep_the_plain_url(monkeypatch):
    monkeypatch.setattr(
        app_config, "_config", {"renderer": {"upnp_hide_track_number": ["uuid:naim-atom"]}}
    )
    dmr = ScriptedDmr()
    control = _control("uuid:other", dmr, sink=("http-get:*:audio/flac:*",))
    await control.play_track(7, "/m/7.flac", dict(META))
    assert "hide_tracknumber" not in dmr.set_calls[0]["media_url"]
