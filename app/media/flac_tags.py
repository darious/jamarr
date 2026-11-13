"""Hide a FLAC's TRACKNUMBER tag from a renderer without touching the file.

Naim streamers on firmware 3.13 put the TRACKNUMBER Vorbis comment of a
stream pushed with SetAVTransportURI into their now-playing title, ahead of
both the TITLE tag and the DIDL-Lite ``dc:title``. Renaming the comment's
key by one byte (``TRACKNUMBER=`` -> ``XRACKNUMBER=``) makes them fall back
to the real title. The key keeps its length, so the file size, every byte
offset and Range/seek behaviour are unchanged, and FLAC metadata blocks carry
no checksum. Opt-in per renderer: ``renderer.upnp_hide_track_number``.
"""

from __future__ import annotations

import os
import struct
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Mapping

from starlette.responses import FileResponse
from starlette.types import Receive, Scope, Send

_VORBIS_COMMENT = 4
_KEY = b"TRACKNUMBER="
_MAX_BLOCKS = 128  # a FLAC header has a handful; this only bounds a corrupt file


def track_number_patches(path: str | os.PathLike[str]) -> dict[int, bytes]:
    """{file offset: replacement byte} that renames each TRACKNUMBER key.

    Empty for anything that is not a FLAC with such a comment, or whose
    header cannot be parsed: the stream is then served untouched.
    """
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"fLaC":
                return {}
            for _ in range(_MAX_BLOCKS):
                header = f.read(4)
                if len(header) < 4:
                    return {}
                is_last = header[0] & 0x80
                block_type = header[0] & 0x7F
                length = int.from_bytes(header[1:4], "big")
                body_start = f.tell()
                if block_type == _VORBIS_COMMENT:
                    return _patches_in_comment_block(f.read(length), body_start)
                if is_last:
                    return {}
                f.seek(body_start + length)
    except (OSError, ValueError, struct.error):
        return {}
    return {}


def _patches_in_comment_block(block: bytes, block_start: int) -> dict[int, bytes]:
    patches: dict[int, bytes] = {}
    (vendor_len,) = struct.unpack_from("<I", block, 0)
    pos = 4 + vendor_len
    (count,) = struct.unpack_from("<I", block, pos)
    pos += 4
    for _ in range(count):
        (comment_len,) = struct.unpack_from("<I", block, pos)
        pos += 4
        if block[pos : pos + len(_KEY)].upper() == _KEY:
            # Keep the key's case style: Vorbis keys are case-insensitive.
            patches[block_start + pos] = b"x" if block[pos : pos + 1].islower() else b"X"
        pos += comment_len
        if pos > len(block):
            return {}
    return patches


class _PatchedFile:
    """An anyio file whose reads have single bytes replaced at fixed offsets."""

    def __init__(self, file: Any, patches: Mapping[int, bytes]) -> None:
        self._file = file
        self._patches = patches
        self._pos = 0

    async def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        self._pos = await self._file.seek(offset, whence)
        return self._pos

    async def read(self, size: int = -1) -> bytes:
        chunk = await self._file.read(size)
        start, end = self._pos, self._pos + len(chunk)
        self._pos = end
        hits = [o for o in self._patches if start <= o < end]
        if not hits:
            return chunk
        patched = bytearray(chunk)
        for offset in hits:
            patched[offset - start] = self._patches[offset][0]
        return bytes(patched)


class PatchedFileResponse(FileResponse):
    """FileResponse that serves ``patches`` over the file's bytes.

    Full, single-range and multi-range bodies all read through
    ``_open_file``; zero-copy ``pathsend`` would bypass it, so it is turned
    off. The ETag differs from the untouched file's, because the bytes do.
    """

    def __init__(self, path: str | os.PathLike[str], *, patches: Mapping[int, bytes], **kwargs: Any):
        self.patches = dict(patches)
        super().__init__(path, **kwargs)

    def set_stat_headers(self, stat_result: os.stat_result) -> None:
        super().set_stat_headers(stat_result)
        etag = self.headers.get("etag")
        if etag and etag.endswith('"'):
            self.headers["etag"] = etag[:-1] + '-tn"'

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        extensions = scope.get("extensions") or {}
        if "http.response.pathsend" in extensions:
            scope = {
                **scope,
                "extensions": {k: v for k, v in extensions.items() if k != "http.response.pathsend"},
            }
        await super().__call__(scope, receive, send)

    @asynccontextmanager
    async def _open_file(self) -> AsyncGenerator[Any]:
        async with super()._open_file() as file:
            yield _PatchedFile(file, self.patches)
