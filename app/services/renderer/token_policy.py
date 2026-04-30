from __future__ import annotations

import os


def stream_token_ttl_seconds(
    renderer_kind: str | None,
    duration_seconds: float | int | None = None,
) -> int | None:
    if renderer_kind != "cast":
        return None

    max_ttl = int(os.getenv("CAST_STREAM_TOKEN_TTL_SECONDS", "86400"))
    if duration_seconds:
        return min(max_ttl, max(1800, int(float(duration_seconds) * 2)))
    return max_ttl
