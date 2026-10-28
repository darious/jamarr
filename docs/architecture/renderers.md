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
  `volume_percent`, `current_track_id`, `current_media_url` (UPnP: the
  renderer's `TrackURI`), `ended`.
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
  track-end (`ended=True`), and advances the queue exactly once.
- Cast `play_track()` waits (bounded, `load_timeout`, default 15 s) for the
  receiver's LOAD reply. A `LOAD_FAILED`/`INVALID_REQUEST`-style reply, a lost
  connection or a timeout raises `RendererLoadError`: player state drops to
  stopped, `stopped_reason` becomes `load_failed`, and `/api/player/play` /
  `/api/player/index` answer 502. Statuses arriving while the LOAD is pending
  map to `TRANSITIONING` and are ignored.
- Cast completion comes from `idleReason`, and only for the media Jamarr
  loaded: `FINISHED` ends the track (once); `ERROR` halts with
  `stopped_reason = renderer_error`; `CANCELLED`/`INTERRUPTED` (stopped on the
  device, another controller took over) halt with `renderer_stopped`. None of
  these advance, and Cast statuses set `completion_reported`, which turns off
  the orchestrator's position-vs-duration end heuristic. Jamarr's own stop is
  not reported as a device halt.
- The UPnP poll loop handles two quirky end-of-track signatures seen on real
  renderers: a quick `PLAYING → PAUSED_PLAYBACK → STOPPED` sequence counts as
  track-finished (the `PAUSED` poll alone must not swallow the advance), and a
  watchdog force-advances renderers stuck reporting `PLAYING` at position 0 for
  longer than the track duration plus a margin.
- On renderers with next-track staging (below) the poll loop also advances when
  the renderer's `TrackURI` turns into the staged URI, without any `STOPPED`.

## UPnP next-track staging

`SetNextAVTransportURI` hands a renderer the track after the current one, so
it can fetch and buffer it and move on by itself. Whether the result is truly
gapless depends on the renderer; this has not been measured on hardware yet.
Code: `app/services/upnp/staging.py` (state, policy), `monitor.py`
(`_sync_staged_next`, `_reconcile_staged_transition`), `device.py`
(`set_next_track`, which shares DIDL/MIME building with `play_track`).

**When.** Each `PLAYING` poll, once the current track has played past
`STAGE_AFTER_S` (10 s, so a flaky start settles first), the monitor makes the
staged item match `queue[current_index + 1]`: stage it, re-stage it if the
queue changed, or send an empty `NextURI` when there is no next item. The URL
is built like a normal load (`build_stream_url`, so loudness-normalization
claims ride in the token) and goes via the stream proxy. Its token TTL covers
the rest of the current track plus twice the staged track's duration (floor
1800 s, cap 24 h, `staged_stream_token_ttl_seconds`); the monitor re-stages
before expiry, e.g. after a long pause. Nothing is staged when the renderer
reports no `TrackURI`, since the transition could then not be followed.

**Transitions.** Every poll reads `TrackURI` from `GetPositionInfo`. When it
matches the staged URI (exactly, or by its unique stream token) while
`PLAYING`, `TRANSITIONING` or `PAUSED_PLAYBACK`, the monitor consumes the
staged record and moves `current_index` on with a conditional `UPDATE … WHERE
current_index = <old>` — so the queue and history advance exactly once and the
already-started track is not reloaded. History then logs the new track at the
usual threshold. If the renderer started a staged track that a queue edit has
since dropped, the monitor loads the real next track (or stops at the end of
the queue).

**Consistency.** Loading any track (`play_track`: play, skip, jump, new queue,
start retry, STOPPED fallback) forgets the staged record, and the monitor
re-stages once the new track is playing. Reorder, delete and append are
reconciled on the next poll. Stop clears the device's `NextURI`. A seek within
the current track leaves the staged next as it is. There is no server-side
shuffle or repeat to account for.

**Fallback.** The STOPPED-based path above stays in charge whenever nothing is
staged. A `STOPPED` at track end while something is staged gets
`STAGED_STOP_GRACE_S` (3 s) to turn into the staged track, after which the
next track is loaded as usual.

**Provisional support.** Discovery's `supports_gapless` (the action and state
variable exist) is only a starting point. Staging is switched off for a
renderer, in memory until restart and with a warning in the log, when
`SetNextAVTransportURI` returns a SOAP fault or other non-transient error,
fails transiently 3 times in a row, or when the renderer twice accepts a
staged URI but stops at track end instead of playing it. Rejection of the
empty "clear" URI is ignored. `GET /api/player/upnp/diagnostics` lists
switched-off renderers under `gapless_disabled` and what is staged under
`gapless_staged`.

**Override.** `config.yaml`:

```yaml
renderer:
  upnp_gapless:
    enabled: true             # false = never stage, on any renderer
    disabled_udns: [uuid:…]   # never stage on these
    forced_udns: [uuid:…]     # stage even when not advertised
```

UDNs match case-insensitively, with or without `uuid:`. `disabled_udns` (and
`enabled: false`) wins over everything; runtime faults still switch off a
`forced_udns` renderer. No vendor-specific rules are built in.

## UPnP discovery

`app/services/upnp/discovery.py` keeps one record per description URL and
feeds it from three sources:

- **Search bursts** — every 30 s (60 s while the listener runs) an M-SEARCH for
  both `urn:schemas-upnp-org:device:MediaRenderer:1` and
  `urn:schemas-upnp-org:service:AVTransport:1`, sent 3× 500 ms apart inside one
  bounded scan. Overlapping scans share the one in flight.
- **SSDP listener** — a persistent `ssdp:alive` / `ssdp:update` /
  `ssdp:byebye` listener. If port 1900 cannot be bound it logs a warning and
  discovery carries on with polling search only.
- **Manual add / subnet sweep** — unicast M-SEARCH to the host, then four
  guessed description URLs. Manual add also takes a full `http(s)://`
  description URL and returns the renderer actually registered. The sweep
  is an explicit admin action (`POST /api/scan/subnet`, the Renderers page's
  *Scan Subnet* button) — `GET /api/renderers?refresh=true` only searches and
  re-reads descriptions. It covers the interface's real subnet (clipped to a
  /22), 32 hosts at a time, short timeouts; cancel with `POST /api/scan/cancel`.

**Embedded devices.** Each description is fetched once and its device tree
walked; every node with its own AVTransport service is registered under its
own UDN, control URLs and `DmrDevice` (multi-zone amps, NAS/receiver roots).
Nodes without AVTransport are never registered. A description with none at
all is re-read on the cooldown steps (a booting TV can briefly serve a
root-only description), or every scan if it belongs to a saved renderer.
Earlier versions saved the *root* UDN of such trees; when exactly one embedded
endpoint replaces it, its settings, sessions, queue state and icon move to
the new UDN and the old row is deleted, otherwise it stays unavailable.
Registration is committed per endpoint only after its DB save, so a failure or
deadline never leaves a half-registered renderer.

**Hydration vs liveness.** Hydration (description + SCPDs, `GetProtocolInfo`,
icon, DB save) happens for a new LOCATION, a changed `BOOTID.UPNP.ORG` /
`CONFIGID.UPNP.ORG`, an explicit refresh, a device coming back after being
unreachable, or a failed control call (a sticky flag, honoured by the next
sighting or probe). Any other
sighting only bumps `last_seen`. Hydrations of the same URL are deduplicated,
run at most 4 at a time and each has a 20 s deadline. The per-location failure
cooldown and BOOTID-based un-suspension still gate retries.

**Availability.** A device goes unavailable only after an `ssdp:byebye` or
its `max-age` + 120 s grace has passed, *and* an HTTP probe of its description
fails — one lost multicast reply never removes it. Unavailable devices drop
out of `/api/renderers` and get `renderer.available = FALSE`, but their
metadata and settings are kept; a fresh alive brings them back.
`RendererOrchestrator._renderer_available()` asks the backend's
`is_available()` (this tracked state) before falling back to list
membership, so stale-session recovery acts on real departures.

**Interface.** `renderer.upnp_source_ip` (env `UPNP_SOURCE_IP`) pins the
address discovery binds to and that stream/art URLs (incl. the stream proxy)
use. Unset, the default-route address is used and re-checked each scan.

**Diagnostics.** `GET /api/player/upnp/diagnostics` (admin) returns the source
and stream address, listener status, search targets, per-target reply counts
of the last scan, description failures, cooldown/suspended locations,
per-device last-seen/BOOTID/availability and recent availability transitions.

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

UPnP next tracks staged ahead of time get their own TTL (see
[next-track staging](#upnp-next-track-staging)); other UPnP loads keep the
default.

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

## Android device-UPnP discovery

With "phone discovers renderers" on, the app runs its own jUPnP control point
(`android/.../upnp/`). `DiscoveryLifecycle` owns start/stop and searching:

- Searches go out in short bursts only: after startup (0/1/3/10 s), when the
  renderer picker opens, and after a network change. No background repeats;
  jUPnP's registry tracks devices from their NOTIFY/max-age.
- jUPnP's `RouterImpl` binds to the interfaces present at `enable()` and never
  re-scans (its `AndroidRouter` broadcast receiver is only wired into
  `AndroidUpnpServiceImpl`, which the app does not use). So a debounced
  `NetworkCallback` rebinds the router (disable + enable) when the IPv4 address
  set changed or a network was lost, drops the old network's devices from the
  registry, then searches again; a start that failed
  for lack of a network is retried the same way.
- Each device in a root's tree with its own AVTransport is a separate renderer
  under its own UDN, using only its own services, matched by service type
  (any version), not serviceId (`RendererEndpoints.kt`).

## Deployment notes

- Docker needs `network_mode: "host"` for both UPnP SSDP and Cast mDNS. Host
  networking also exposes the renderer stream proxy (default 8112) on the host.
- Cast playback does **not** transcode in v1; unsupported codecs/containers fail
  on the receiver (surfaced as `load_failed`). The Default Media Receiver covers
  common formats.
- Device-direct Cast requires Google Play Services — de-Googled Android can still
  use server-driven Cast.

## History

This subsystem replaced a design where `app/api/player.py` called the
`UPnPManager` singleton directly. The refactor was delivered in phases (baseline
characterization → unified backend contract → server Cast → device Cast → web
UI → hardening), each keeping local + UPnP playback working. The
backend/device-split and capability model take inspiration from Music Assistant's
provider architecture (reference only, not a dependency).
