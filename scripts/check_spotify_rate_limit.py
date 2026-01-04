#!/usr/bin/env python
"""
Check Spotify API rate limit status using Spotify credentials from environment variables.
"""
from __future__ import annotations

import sys
import time
from datetime import timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_spotify_credentials  # type: ignore # noqa: E402


def load_credentials() -> tuple[str, str]:
    return get_spotify_credentials()


def fetch_access_token(client_id: str, client_secret: str) -> str:
    resp = httpx.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("Spotify token response missing access_token")
    return token


def check_rate_limit(token: str, artist_id: str = "43ZHCT0cAZBISjO8DG9PnE") -> None:
    """
    Hit a representative endpoint that is known to enforce rate limits.
    Default artist is Elvis Presley (stable, public profile).
    """
    resp = httpx.get(
        f"https://api.spotify.com/v1/artists/{artist_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )

    headers = resp.headers
    remaining = headers.get("X-RateLimit-Remaining")
    limit = headers.get("X-RateLimit-Limit")
    reset_at = headers.get("X-RateLimit-Reset")
    retry_after = headers.get("Retry-After")

    if resp.status_code == 429:
        retry_seconds = int(retry_after) if retry_after and retry_after.isdigit() else None
        if retry_seconds is not None:
            duration = str(timedelta(seconds=retry_seconds))
            print(f"Rate limited: retry after {retry_seconds} seconds ({duration}).")
        else:
            print("Rate limited: retry-after header missing.")
        return

    resp.raise_for_status()

    # If Spotify doesn't include rate headers on success, treat it as not limited.
    if remaining is None and limit is None and reset_at is None and retry_after is None:
        print("Not rate limited (no rate-limit headers returned). Headers found:", list(headers.keys()))
        return

    message = []
    if limit:
        message.append(f"Limit: {limit}")
    if remaining:
        message.append(f"Remaining: {remaining}")
    if reset_at:
        try:
            reset_ts = int(reset_at)
            in_seconds = max(0, reset_ts - int(time.time()))
            message.append(f"Resets in: {in_seconds}s ({str(timedelta(seconds=in_seconds))}) at {reset_ts}")
        except ValueError:
            message.append(f"Reset at: {reset_at}")
    print(" | ".join(message))


def main() -> int:
    try:
        client_id, client_secret = load_credentials()
        token = fetch_access_token(client_id, client_secret)
        check_rate_limit(token)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
