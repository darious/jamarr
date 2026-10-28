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


# Bounds for the token on a UPnP next-track staged ahead of time.
STAGED_TOKEN_MIN_TTL_SECONDS = 1800
STAGED_TOKEN_MAX_TTL_SECONDS = 86400


def staged_stream_token_ttl_seconds(
    lead_seconds: float | int | None,
    duration_seconds: float | int | None = None,
) -> int:
    """TTL for a stream token handed to a renderer before it is needed.

    A staged URI is first fetched when the current track ends (lead_seconds
    away, longer if the listener pauses) and then refetched by Range requests
    for the whole of its own playback, so it must outlive both. The monitor
    re-stages before expiry, so the cap only bounds a forgotten token.
    """
    lead = max(0.0, float(lead_seconds or 0))
    duration = max(0.0, float(duration_seconds or 0))
    ttl = int(lead + duration * 2)
    return min(STAGED_TOKEN_MAX_TTL_SECONDS, max(STAGED_TOKEN_MIN_TTL_SECONDS, ttl))
