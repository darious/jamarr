# ADR-0003: Duration-aware stream-token TTL for Cast

- **Status:** Accepted
- **Date:** 2026-04 (Chromecast refactor, Phase 1)

## Context

Stream URLs carry a short-lived, track-bound JWT (default
`STREAM_TOKEN_TTL_SECONDS = 300`). That works for browser/UPnP playback because
the client re-requests a fresh URL per track. A **Chromecast receiver parses the
URL once and never re-authenticates** — a 10-minute track would outlive a 300 s
token mid-playback and stall.

## Decision

Move stream-token TTL selection into the orchestrator
(`app/services/renderer/token_policy.py`) and use a **duration-aware TTL for
`kind == "cast"`**:

```python
min(CAST_STREAM_TOKEN_TTL_SECONDS, max(1800, duration_seconds * 2))
```

`CAST_STREAM_TOKEN_TTL_SECONDS` defaults to `86400` (24 h) as the hard cap;
non-Cast playback keeps the 300 s default. Tokens remain **bound to `track_id`**
(`verify_stream_token` rejects mismatches), so a leaked Cast URL only plays one
track.

## Consequences

- Cast playback survives long tracks and pauses without re-auth.
- Scope stays narrow despite the longer life — one track, one device session.
- Cost: a leaked Cast URL is replayable for up to its TTL. True revocation would
  need a token nonce/version store (reissuing a stateless JWT does **not**
  invalidate old URLs) — deferred; see [Roadmap](../../roadmap.md).
- Rejected alternative: LAN-allowlist bypass for Cast — breaks the uniform auth
  model and fails for device-direct Cast where the device IP is unpredictable.
