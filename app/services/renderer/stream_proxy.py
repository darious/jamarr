"""
Renderer-facing HTTP proxy that re-cases response headers.

uvicorn force-lowercases every response header name below the ASGI layer
(both its h11 and httptools implementations), and some UPnP renderers parse
header names case-sensitively. The server-room TCL Google TV (Platinum SDK
"Windows Media Player" DMR) needs `Content-Length`/`Content-Range` in
canonical casing to learn the stream size; without it, it plays audio but
reports no position/duration and misbehaves at end of track.

This proxy listens on a second port, forwards GET/HEAD requests for stream
and art URLs to the local API, and relays the response with header names
rewritten to canonical HTTP casing. UPnP renderers are pointed at this port;
browsers keep talking to uvicorn directly.
"""

import asyncio
import logging
import os

from app.config import load_config

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8112
ALLOWED_PATH_PREFIXES = ("/api/stream/", "/art/")
HEADER_READ_LIMIT = 32 * 1024
HEADER_READ_TIMEOUT_S = 30
PIPE_CHUNK_SIZE = 64 * 1024


def get_proxy_port() -> int:
    env_port = os.environ.get("RENDERER_PROXY_PORT")
    if env_port:
        return int(env_port)
    return int(load_config().get("renderer", {}).get("stream_proxy_port", DEFAULT_PORT))


def get_upstream_port() -> int:
    return int(os.environ.get("HOST_PORT") or 8111)


# DLNA's own header names are camelCase, not HTTP-canonical.
_DLNA_HEADER_NAMES = {
    b"contentfeatures.dlna.org": b"contentFeatures.dlna.org",
    b"transfermode.dlna.org": b"transferMode.dlna.org",
}

# Byte-range seekable (OP=01), streaming transfer, DLNA 1.5 (FLAGS). Without
# it DLNA renderers treat the stream as unseekable: a Sony Bravia then lists
# only Play,Stop as transport actions and refuses Seek.
DLNA_CONTENT_FEATURES = b"DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"


def canonicalize_header_name(name: bytes) -> bytes:
    dlna = _DLNA_HEADER_NAMES.get(name.lower())
    if dlna is not None:
        return dlna
    return b"-".join(part.capitalize() for part in name.split(b"-"))


def dlna_response_headers(request_headers: dict[bytes, bytes], response_head: bytes) -> list[bytes]:
    """DLNA headers a renderer asked for (getcontentFeatures / transferMode),
    for a successful response that supports byte ranges."""
    status_line, _, block = response_head.partition(b"\r\n")
    parts = status_line.split(b" ")
    if len(parts) < 2 or parts[1] not in (b"200", b"206"):
        return []
    present = {line.partition(b":")[0].strip().lower(): line.partition(b":")[2].strip().lower()
               for line in block.split(b"\r\n") if b":" in line}
    out = []
    if (
        request_headers.get(b"getcontentfeatures.dlna.org", b"").strip() == b"1"
        and b"contentfeatures.dlna.org" not in present
        and present.get(b"accept-ranges") == b"bytes"
    ):
        out.append(b"contentFeatures.dlna.org: " + DLNA_CONTENT_FEATURES)
    if request_headers.get(b"transfermode.dlna.org") and b"transfermode.dlna.org" not in present:
        out.append(b"transferMode.dlna.org: Streaming")
    return out


async def _read_head(reader: asyncio.StreamReader) -> bytes:
    return await asyncio.wait_for(
        reader.readuntil(b"\r\n\r\n"), timeout=HEADER_READ_TIMEOUT_S
    )


def _response_has_body(method: bytes, status_line: bytes) -> bool:
    """RFC 9110 §6.4.1: HEAD responses and 1xx/204/304 statuses have no body,
    whatever Content-Length says."""
    if method == b"HEAD":
        return False
    parts = status_line.split(b" ")
    status = parts[1] if len(parts) > 1 else b""
    return not (status.startswith(b"1") or status in (b"204", b"304"))


def _bad_request(status_line: bytes) -> bytes:
    return status_line + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"


async def _pipe_body(
    upstream_reader: asyncio.StreamReader,
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
) -> None:
    """Relay the upstream body to the renderer until upstream EOF, with
    backpressure. Also watch the renderer's side of the socket: a renderer
    that hangs up mid-stream must release the upstream connection at once,
    not when the upstream next sends something we fail to write."""
    client_gone = asyncio.ensure_future(client_reader.read())
    try:
        while True:
            chunk_read = asyncio.ensure_future(upstream_reader.read(PIPE_CHUNK_SIZE))
            done, _ = await asyncio.wait(
                {chunk_read, client_gone}, return_when=asyncio.FIRST_COMPLETED
            )
            if chunk_read not in done:
                chunk_read.cancel()
                return  # the renderer went away
            chunk = chunk_read.result()
            if not chunk:
                return
            client_writer.write(chunk)
            await client_writer.drain()
    finally:
        client_gone.cancel()


async def _handle_client(
    client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
):
    upstream_writer = None
    try:
        try:
            head = await _read_head(client_reader)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
            return

        request_line, _, header_block = head.partition(b"\r\n")
        parts = request_line.split(b" ")
        if len(parts) != 3:
            client_writer.write(_bad_request(b"HTTP/1.1 400 Bad Request"))
            return
        method, target, _version = parts
        if method not in (b"GET", b"HEAD"):
            client_writer.write(_bad_request(b"HTTP/1.1 405 Method Not Allowed"))
            return
        path = target.split(b"?")[0].decode("latin-1", errors="replace")
        if not path.startswith(ALLOWED_PATH_PREFIXES):
            client_writer.write(_bad_request(b"HTTP/1.1 404 Not Found"))
            return

        upstream_port = get_upstream_port()
        upstream_reader, upstream_writer = await asyncio.open_connection(
            "127.0.0.1", upstream_port
        )

        # Forward the request with hop-by-hop headers replaced; Connection: close
        # makes the upstream body end at EOF so we can pipe it verbatim.
        out_headers = [b"connection: close"]
        request_headers: dict[bytes, bytes] = {}
        for line in header_block.split(b"\r\n"):
            if not line:
                continue
            name = line.split(b":", 1)[0].strip().lower()
            request_headers[name] = line.partition(b":")[2]
            if name in (b"connection", b"keep-alive", b"proxy-connection"):
                continue
            out_headers.append(line)
        upstream_writer.write(
            method + b" " + target + b" HTTP/1.1\r\n"
            + b"\r\n".join(out_headers)
            + b"\r\n\r\n"
        )
        await upstream_writer.drain()

        try:
            response_head = await _read_head(upstream_reader)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
            client_writer.write(_bad_request(b"HTTP/1.1 502 Bad Gateway"))
            return

        status_line, _, response_headers = response_head.partition(b"\r\n")
        recased = [status_line]
        for line in response_headers.split(b"\r\n"):
            if not line:
                continue
            name, sep, value = line.partition(b":")
            if not sep:
                continue
            if name.strip().lower() in (b"connection", b"keep-alive"):
                continue
            recased.append(canonicalize_header_name(name.strip()) + b": " + value.strip())
        recased.extend(dlna_response_headers(request_headers, response_head))
        recased.append(b"Connection: close")
        client_writer.write(b"\r\n".join(recased) + b"\r\n\r\n")
        await client_writer.drain()

        if not _response_has_body(method, status_line):
            # HEAD (and 1xx/204/304) carry no body: the renderer's probe is
            # complete once the headers are out. Do not wait for the upstream
            # to hang up, and forward nothing it might wrongly send.
            return

        await _pipe_body(upstream_reader, client_reader, client_writer)
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    except Exception as e:
        logger.warning(f"Renderer stream proxy error: {e}")
    finally:
        for writer in (upstream_writer, client_writer):
            if writer is not None:
                try:
                    writer.close()
                except Exception:
                    pass


class RendererStreamProxy:
    def __init__(self, port: int | None = None):
        self.port = port if port is not None else get_proxy_port()
        self._server: asyncio.Server | None = None

    async def start(self):
        try:
            self._server = await asyncio.start_server(
                _handle_client, "0.0.0.0", self.port, limit=HEADER_READ_LIMIT
            )
        except OSError as e:
            logger.error(
                f"Renderer stream proxy failed to bind port {self.port}: {e}. "
                "UPnP renderers that need canonical header casing will misbehave."
            )
            self._server = None
            return
        logger.info(f"Renderer stream proxy listening on :{self.port}")

    async def stop(self):
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    @property
    def is_running(self) -> bool:
        return self._server is not None


_proxy: RendererStreamProxy | None = None


def get_stream_proxy() -> RendererStreamProxy:
    global _proxy
    if _proxy is None:
        _proxy = RendererStreamProxy()
    return _proxy
