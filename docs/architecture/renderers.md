# Renderers & Playback

Jamarr plays audio to three kinds of target — the local client (`<audio>` /
mobile player), UPnP/DLNA renderers, and Chromecast devices — behind **one**
playback model and **one** control API. Protocol details are isolated inside
pluggable backends.

!!! info "Code"
    `app/services/renderer/` (orchestrator, registry, contracts, persistence,
    backends) and `app/services/player/` (monitor, queue, state). Player HTTP
    routes live in `app/api/player.py` and call the orchestrator only — they do
    not import `UPnPManager`, `pychromecast`, or any protocol library.

## Layering

```
Web / TUI / Android
        │
        ▼
   Player API  (app/api/player.py)
        │
        ▼
RendererOrchestrator      ── canonical renderer identity, queue state,
        │                    stream/artwork URL + token policy, auto-advance,
        │                    progress/history/scrobble, one API response shape
        ▼
   RendererRegistry        ── routes a renderer_id to its backend
        ├── upnp:<udn>   → UpnpRendererBackend
        ├── cast:<uuid>  → CastRendererBackend
        └── local:<id>   → local client playback state (state-only)
```

- **Orchestrator** (`orchestrator.py`, `RendererOrchestrator`) owns everything
  protocol-neutral: queue, current index, progress, auto-advance, history/Last.fm,
  stream-token policy, and the normalised player state persisted to the DB.
- **Backends** (`upnp_backend.py`, `cast_backend.py`) translate
  play/pause/resume/stop/seek/volume/status into protocol calls and emit a
  normalised `RendererStatus`. They hide native IDs, status strings, connection
  lifecycle, and libraries.
- **Registry** (`registry.py`, `RendererRegistry`) holds backend instances keyed
  by `kind`, parses renderer IDs, and merges discovery across backends.

## Canonical renderer identity

Every renderer has a backend-agnostic ID:

```
renderer_id = "{kind}:{native_id}"
```

| kind | example | native_id |
|---|---|---|
| `upnp` | `upnp:uuid:abcd-…` | UPnP UDN |
| `cast` | `cast:8f1c…` | Cast device UUID |
| `local` | `local:web-client-id` | per-client ID |

Helpers `make_renderer_id` / `split_renderer_id` (in `contracts`) format and
parse these. The legacy `udn` field is still accepted on input and persisted for
backwards compatibility, but new code passes `renderer_id` + `kind`. See
[ADR-0002](decisions/0002-renderer-orchestration.md).

## Contracts

`contracts.py` defines protocol-neutral dataclasses that everything above the
backend speaks in:

- **`RendererCapabilities`** — `can_play/pause/stop/seek/set_volume/mute`,
  `can_next_previous`, `reports_progress`, `supports_events`, `supported_mime_types`, …
- **`RendererDevice`** — `renderer_id`, `kind`, `native_id`, `name`, `ip`,
  `manufacturer`, `model_name`, `cast_type`, `discovered_by`, `capabilities`,
  `available`, group info.
- **`RendererStatus`** — normalised `state` (`PLAYING`/`PAUSED`/`STOPPED`/
  `BUFFERING`/`IDLE`/`UNKNOWN`), `position_seconds`, `duration_seconds`,
  `volume_percent`, `current_track_id`, `ended`.
- **`PlaybackContext`** — `base_url`, `user_id`, `username`, `token_ttl_seconds`.
- **`RendererBackend`** (Protocol) — the interface every backend implements;
  optional **`SupportsStatusEvents`** for callback-driven protocols.

The orchestrator does not care whether a `RendererStatus` came from polling
(UPnP) or media-controller callbacks (Cast).

## Status & auto-advance

- UPnP backend runs a **poll loop** (`app/services/player/monitor.py`) and emits
  `RendererStatus`.
- Cast backend subscribes to `pychromecast` media-controller **callbacks**;
  callbacks are dispatched back onto the asyncio loop before mutating state.
- The orchestrator normalises status, updates progress/volume, detects
  track-end (`ended=True`, or Cast `IDLE` after `PLAYING`), and advances the
  queue exactly once. A short grace period after `play_track()` suppresses the
  transient `IDLE` during Cast load so it doesn't false-advance.
- The UPnP poll loop handles two quirky end-of-track signatures seen on real
  renderers: a quick `PLAYING → PAUSED_PLAYBACK → STOPPED` sequence counts as
  track-finished (the `PAUSED` poll alone must not swallow the advance), and a
  watchdog force-advances renderers stuck reporting `PLAYING` at position 0 for
  longer than the track duration plus a margin.

## Renderer stream proxy

UPnP renderers fetch stream and artwork URLs through a small in-process HTTP
proxy (`app/services/renderer/stream_proxy.py`, default port **8112**, config
`renderer.stream_proxy_port` / env `RENDERER_PROXY_PORT`) instead of hitting
uvicorn directly.

**Why:** uvicorn lowercases every response header name below the ASGI layer,
and some renderers parse header names case-sensitively — e.g. the Platinum-SDK
"Windows Media Player" DMR found in TCL Google TVs needs `Content-Length` /
`Content-Range` in canonical casing to determine stream size. Without it the
device plays audio but reports no position/duration and emits erratic
end-of-track states, breaking auto-advance.

The proxy forwards `GET`/`HEAD` for `/api/stream/` and `/art/` to the API on
loopback and relays the response with header names re-cased to canonical form.
All auth (stream tokens), range handling, and quality logic stay in the normal
endpoints. Browsers and other clients keep using the API port. If the proxy
port fails to bind, renderer URLs fall back to the API port (pre-proxy
behaviour).

## Stream-token policy

Cast receivers parse the stream URL once and never re-auth, so the default 300 s
token is too short for a long track. The orchestrator (`token_policy.py`) issues
a longer, duration-aware TTL for `kind == "cast"`:

```python
min(CAST_STREAM_TOKEN_TTL_SECONDS, max(1800, duration_seconds * 2))   # default cap 86400
```

Tokens stay bound to `track_id`, so scope is narrow even with a long TTL. Full
rationale and the trade-offs: [ADR-0003](decisions/0003-cast-stream-token-policy.md).

## Two Cast control paths

| Path | Discovers | Controls | Where the server is | Use case |
|---|---|---|---|---|
| **Server-driven** | server (mDNS) | server (`pychromecast`) | same LAN as Cast devices | home server / NAS / Pi |
| **Device-direct** | Android (Cast SDK) | Android | anywhere, incl. public | VPS / remote server |

Both paths: the Cast device fetches the stream URL from the server over HTTP and
plays via the Default Media Receiver (no custom receiver app). Device-direct Cast
pins the server's active renderer to `local:<clientId>` and reports
queue/progress/index through the normal local-client path, so history and
scrobbling behave like Android device-UPnP. See
[ADR-0004](decisions/0004-cast-dual-control-path.md) and the
[Android client](../clients/android.md).

## Deployment notes

- Docker needs `network_mode: "host"` for both UPnP SSDP and Cast mDNS. Host
  networking also exposes the renderer stream proxy (default 8112) on the host.
- Cast playback does **not** transcode in v1; unsupported codecs/containers fail
  on the receiver. The Default Media Receiver covers common formats.
- Device-direct Cast requires Google Play Services — de-Googled Android can still
  use server-driven Cast.

## History

This subsystem replaced a design where `app/api/player.py` called the
`UPnPManager` singleton directly. The refactor was delivered in phases (baseline
characterization → unified backend contract → server Cast → device Cast → web
UI → hardening), each keeping local + UPnP playback working. The
backend/device-split and capability model take inspiration from Music Assistant's
provider architecture (reference only, not a dependency).
