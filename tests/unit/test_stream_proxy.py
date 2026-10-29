"""Renderer stream proxy: header re-casing and request filtering."""

import asyncio

import pytest

from app.services.renderer import stream_proxy
from app.services.renderer.stream_proxy import (
    RendererStreamProxy,
    canonicalize_header_name,
)

BODY = b"FLACFAKEBODY" * 100


def test_canonicalize_header_name():
    assert canonicalize_header_name(b"content-length") == b"Content-Length"
    assert canonicalize_header_name(b"content-range") == b"Content-Range"
    assert canonicalize_header_name(b"accept-ranges") == b"Accept-Ranges"
    assert canonicalize_header_name(b"x-jamarr-stream-quality") == b"X-Jamarr-Stream-Quality"
    assert canonicalize_header_name(b"etag") == b"Etag"


async def _start_fake_upstream():
    """Upstream that answers like uvicorn: all-lowercase header names."""
    requests = []

    async def handle(reader, writer):
        head = await reader.readuntil(b"\r\n\r\n")
        requests.append(head)
        if b"\r\nRange:" in head or b"\r\nrange:" in head:
            body = BODY[:100]
            writer.write(
                b"HTTP/1.1 206 Partial Content\r\n"
                b"server: uvicorn\r\n"
                b"content-type: audio/flac\r\n"
                b"accept-ranges: bytes\r\n"
                + f"content-length: {len(body)}\r\n".encode()
                + f"content-range: bytes 0-{len(body) - 1}/{len(BODY)}\r\n".encode()
                + b"connection: close\r\n\r\n"
                + body
            )
        else:
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"server: uvicorn\r\n"
                b"content-type: audio/flac\r\n"
                b"accept-ranges: bytes\r\n"
                + f"content-length: {len(BODY)}\r\n".encode()
                + b"connection: close\r\n\r\n"
                + BODY
            )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port, requests


async def _proxy_request(proxy_port: int, raw_request: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    writer.write(raw_request)
    await writer.drain()
    response = await asyncio.wait_for(reader.read(), timeout=5)
    writer.close()
    return response


@pytest.fixture
async def proxy_setup(monkeypatch):
    upstream, upstream_port, requests = await _start_fake_upstream()
    monkeypatch.setattr(stream_proxy, "get_upstream_port", lambda: upstream_port)
    proxy = RendererStreamProxy(port=0)
    await proxy.start()
    proxy_port = proxy._server.sockets[0].getsockname()[1]
    yield proxy_port, requests
    await proxy.stop()
    upstream.close()
    await upstream.wait_closed()


async def test_proxy_recases_response_headers(proxy_setup):
    proxy_port, _ = proxy_setup
    response = await _proxy_request(
        proxy_port, b"GET /api/stream/1?token=abc HTTP/1.1\r\nHost: x\r\n\r\n"
    )
    head, _, body = response.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 200 OK")
    assert b"\r\nContent-Length: " in head
    assert b"\r\nContent-Type: audio/flac" in head
    assert b"\r\nAccept-Ranges: bytes" in head
    assert b"\r\ncontent-length" not in head
    assert body == BODY


async def test_proxy_recases_content_range_on_206(proxy_setup):
    proxy_port, _ = proxy_setup
    response = await _proxy_request(
        proxy_port,
        b"GET /api/stream/1?token=abc HTTP/1.1\r\nHost: x\r\nRange: bytes=0-99\r\n\r\n",
    )
    head, _, body = response.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 206")
    assert b"\r\nContent-Range: bytes 0-99/" in head
    assert body == BODY[:100]


async def test_proxy_forwards_range_header_upstream(proxy_setup):
    proxy_port, requests = proxy_setup
    await _proxy_request(
        proxy_port,
        b"GET /art/file/abc?max_size=600 HTTP/1.1\r\nHost: x\r\nRange: bytes=0-99\r\n\r\n",
    )
    assert b"Range: bytes=0-99" in requests[-1]


async def test_proxy_rejects_unknown_paths(proxy_setup):
    proxy_port, requests = proxy_setup
    response = await _proxy_request(
        proxy_port, b"GET /api/auth/login HTTP/1.1\r\nHost: x\r\n\r\n"
    )
    assert response.startswith(b"HTTP/1.1 404")
    assert requests == []


async def test_proxy_rejects_non_get(proxy_setup):
    proxy_port, requests = proxy_setup
    response = await _proxy_request(
        proxy_port, b"POST /api/stream/1 HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\n\r\n"
    )
    assert response.startswith(b"HTTP/1.1 405")
    assert requests == []


def test_dlna_header_names_keep_their_camel_case():
    from app.services.renderer.stream_proxy import canonicalize_header_name

    assert canonicalize_header_name(b"contentfeatures.dlna.org") == b"contentFeatures.dlna.org"
    assert canonicalize_header_name(b"transfermode.dlna.org") == b"transferMode.dlna.org"
    assert canonicalize_header_name(b"content-length") == b"Content-Length"


def test_dlna_headers_answer_what_the_renderer_asked_for():
    """A Sony Bravia asks getcontentFeatures.dlna.org: 1 and treats a stream
    without the reply as unseekable (it then refuses Seek)."""
    from app.services.renderer.stream_proxy import DLNA_CONTENT_FEATURES, dlna_response_headers

    asked = {b"getcontentfeatures.dlna.org": b" 1", b"transfermode.dlna.org": b" Streaming"}
    ok = b"HTTP/1.1 200 OK\r\naccept-ranges: bytes\r\ncontent-length: 10"
    assert dlna_response_headers(asked, ok) == [
        b"contentFeatures.dlna.org: " + DLNA_CONTENT_FEATURES,
        b"transferMode.dlna.org: Streaming",
    ]
    partial = b"HTTP/1.1 206 Partial Content\r\naccept-ranges: bytes"
    assert len(dlna_response_headers(asked, partial)) == 2
    # Nothing unasked, nothing on errors, no seek claim without byte ranges.
    assert dlna_response_headers({}, ok) == []
    assert dlna_response_headers(asked, b"HTTP/1.1 401 Unauthorized\r\naccept-ranges: bytes") == []
    no_ranges = dlna_response_headers(asked, b"HTTP/1.1 200 OK\r\ncontent-length: 10")
    assert no_ranges == [b"transferMode.dlna.org: Streaming"]


# ---------------------------------------------------------------- HEAD (#319)


async def _start_stalling_upstream(send_body_on_head: bool = False):
    """Upstream that sends headers and then keeps the connection open until
    the proxy hangs up (or 10 s). Records when the proxy closed its side."""
    events: dict = {"closed_after": None, "requests": []}

    async def handle(reader, writer):
        head = await reader.readuntil(b"\r\n\r\n")
        events["requests"].append(head)
        is_head = head.startswith(b"HEAD ")
        ranged = b"\r\nRange:" in head or b"\r\nrange:" in head
        status = b"206 Partial Content" if ranged else b"200 OK"
        writer.write(
            b"HTTP/1.1 " + status + b"\r\n"
            b"server: uvicorn\r\n"
            b"content-type: audio/flac\r\n"
            b"accept-ranges: bytes\r\n"
            + (f"content-range: bytes 0-99/{len(BODY)}\r\n".encode() if ranged else b"")
            + f"content-length: {100 if ranged else len(BODY)}\r\n".encode()
            + b"\r\n"
        )
        if not is_head:
            writer.write(BODY[:100] if ranged else BODY)
        elif send_body_on_head:
            writer.write(b"THIS BODY MUST NOT BE FORWARDED")
        await writer.drain()
        t0 = asyncio.get_running_loop().time()
        try:
            # No close: wait for the peer to go away (EOF) instead.
            await asyncio.wait_for(reader.read(), timeout=10)
        except TimeoutError:
            pass
        events["closed_after"] = asyncio.get_running_loop().time() - t0
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1], events


@pytest.fixture(params=[False, True], ids=["clean-head", "head-with-body"])
async def stalling_proxy(request, monkeypatch):
    upstream, upstream_port, events = await _start_stalling_upstream(request.param)
    monkeypatch.setattr(stream_proxy, "get_upstream_port", lambda: upstream_port)
    proxy = RendererStreamProxy(port=0)
    await proxy.start()
    proxy_port = proxy._server.sockets[0].getsockname()[1]
    yield proxy_port, events
    await proxy.stop()
    upstream.close()
    await upstream.wait_closed()


async def test_head_completes_without_waiting_for_upstream_eof(stalling_proxy):
    proxy_port, events = stalling_proxy
    t0 = asyncio.get_running_loop().time()
    response = await _proxy_request(
        proxy_port,
        b"HEAD /api/stream/1?token=abc HTTP/1.1\r\nHost: x\r\n"
        b"getcontentFeatures.dlna.org: 1\r\ntransferMode.dlna.org: Streaming\r\n\r\n",
    )
    elapsed = asyncio.get_running_loop().time() - t0

    assert elapsed < 2, f"HEAD took {elapsed:.1f}s: waited for upstream EOF"
    head, sep, body = response.partition(b"\r\n\r\n")
    assert sep and body == b"", "a HEAD response carries no body"
    assert head.startswith(b"HTTP/1.1 200 OK")
    assert f"\r\nContent-Length: {len(BODY)}".encode() in head
    assert b"\r\nAccept-Ranges: bytes" in head
    assert b"\r\ncontentFeatures.dlna.org: DLNA.ORG_OP=01" in head
    assert b"\r\ntransferMode.dlna.org: Streaming" in head
    assert b"\r\nConnection: close" in head
    assert b"content-length" not in head

    # The upstream connection was released at once, not after its timeout.
    await asyncio.sleep(0.2)
    assert events["closed_after"] is not None and events["closed_after"] < 2


async def test_ranged_head_keeps_content_range(stalling_proxy):
    proxy_port, _ = stalling_proxy
    response = await asyncio.wait_for(
        _proxy_request(
            proxy_port, b"HEAD /api/stream/1 HTTP/1.1\r\nHost: x\r\nRange: bytes=0-99\r\n\r\n"
        ),
        timeout=3,
    )
    head, _, body = response.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 206")
    assert f"\r\nContent-Range: bytes 0-99/{len(BODY)}".encode() in head
    assert b"\r\nContent-Length: 100" in head
    assert body == b""


async def test_get_still_streams_from_a_stalling_upstream(stalling_proxy):
    """GET keeps piping until EOF: the body arrives even though the upstream
    only closes once the proxy does (here: after the 10 s cap, so read what
    is there rather than waiting for the connection to end)."""
    proxy_port, _ = stalling_proxy
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    writer.write(b"GET /api/stream/1 HTTP/1.1\r\nHost: x\r\nRange: bytes=0-99\r\n\r\n")
    await writer.drain()
    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=3)
    body = await asyncio.wait_for(reader.readexactly(100), timeout=3)
    writer.close()
    assert head.startswith(b"HTTP/1.1 206")
    assert body == BODY[:100]


async def test_client_going_away_mid_get_releases_the_upstream(stalling_proxy):
    proxy_port, events = stalling_proxy
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    writer.write(b"GET /api/stream/1 HTTP/1.1\r\nHost: x\r\n\r\n")
    await writer.drain()
    await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=3)
    writer.close()  # renderer drops the connection mid-stream

    for _ in range(50):
        if events["closed_after"] is not None:
            break
        await asyncio.sleep(0.1)
    assert events["closed_after"] is not None and events["closed_after"] < 3


def test_response_has_body_rules():
    has = stream_proxy._response_has_body
    assert has(b"GET", b"HTTP/1.1 200 OK")
    assert has(b"GET", b"HTTP/1.1 206 Partial Content")
    assert not has(b"HEAD", b"HTTP/1.1 200 OK")
    assert not has(b"GET", b"HTTP/1.1 304 Not Modified")
    assert not has(b"GET", b"HTTP/1.1 204 No Content")
    assert not has(b"GET", b"HTTP/1.1 100 Continue")
    assert has(b"GET", b"garbage")
