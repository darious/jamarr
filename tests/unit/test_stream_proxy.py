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
