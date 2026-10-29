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
  `can_next_previous`, `reports_progress`, `supports_events`, `supported_mime_types`,
  `protocol_info` (UPnP: complete Sink protocolInfo entries),
  plus optional `queue_ownership` (`server`/`renderer`/`continuous_stream`),
  `queue_operations`, `can_stage_next`, `pairing`/`has_credentials` and
  `output` limits. Flags are true only when the operation works now
  ([ADR-0006](decisions/0006-renderer-capability-contract.md)).
- **`RendererDevice`** — `renderer_id`, `kind`, `native_id`, `name`, `ip`,
  `manufacturer`, `model_name`, `cast_type`, `discovered_by`, `capabilities`,
  `available`, group info.
- **`RendererStatus`** — normalised `state` (`PLAYING`/`PAUSED`/`STOPPED`/
  `BUFFERING`/`IDLE`/`UNKNOWN`), `position_seconds`, `duration_seconds`,
  `volume_percent`, `volume_muted`, `current_track_id` (Cast: from the
  item's customData), `current_media_url` (UPnP: the renderer's `TrackURI`),
  `ended`, `advanced_by_renderer` (the device moved on to an item queued on it
  by itself).
- **`PlaybackContext`** — `base_url`, `user_id`, `username`, `token_ttl_seconds`,
  the minted `stream_url` / `stream_mime_type`, and the `playback_plan` it was
  minted for (see [audio output planning](#audio-output-planning)).
- **`RendererBackend`** (Protocol) — the interface every backend implements;
  optional **`SupportsStatusEvents`** for callback-driven protocols,
  **`SupportsOutputConstraints`** (`output_constraints(renderer_id)`) for
  what audio the device accepts, and `SupportsNextTrackStaging` /
  `SupportsPairing` for the rest (no shipped backend pairs).

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
  map to `TRANSITIONING` and are ignored. A LOAD replaced by a newer one
  (rapid skips: `LOAD_CANCELLED`, or a timeout after the next LOAD went out)
  is `superseded`, not a failure, and a timed-out LOAD is only stopped while
  it is still the current one. A failure is only recorded if the track is
  still current. UPnP `play_track()` raises the same error when
  `SetAVTransportURI`/`Play` fails, so the same rollback applies.
- An end of track seen by `GET /api/player/state` polling moves the queue
  inline but loads the next track in a background task, so the request never
  waits on the device.
- Cast completion comes from `idleReason`, and only for the media Jamarr
  loaded: `FINISHED` ends the track (once); `ERROR` halts with
  `stopped_reason = renderer_error`; `CANCELLED`/`INTERRUPTED` (stopped on the
  device, another controller took over) halt with `renderer_stopped`. None of
  these advance, and Cast statuses set `completion_reported`, which turns off
  the orchestrator's position-vs-duration end heuristic. Jamarr's own stop is
  not reported as a device halt. For media Jamarr is not tracking (e.g. after
  a server restart), an `IDLE` with no `idleReason`, or a `FINISHED` not seen
  to follow `PLAYING`, leaves `completion_reported` off so the position
  heuristic decides.
- The UPnP poll loop handles two quirky end-of-track signatures seen on real
  renderers: a quick `PLAYING → PAUSED_PLAYBACK → STOPPED` sequence counts as
  track-finished (the `PAUSED` poll alone must not swallow the advance), and a
  watchdog force-advances renderers stuck reporting `PLAYING` at position 0 for
  longer than the track duration plus a margin.
- On renderers with next-track staging (below) the poll loop also advances when
  the renderer's `TrackURI` turns into the staged URI, without any `STOPPED`.
- While UPnP events are healthy (below) the loop takes transport state and
  `TrackURI` from events, wakes on each one, and polls only as a watchdog.

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
reconciled on the next poll. Whenever a staged record is dropped while the
device may still hold it (new load, unplayable next track, `SetNext` failure,
staging switched off), the monitor sends an empty `NextURI` on the next
`PLAYING` poll, even if staging was just disabled. If the renderer refuses
that, the dropped URI is still remembered, so a renderer that rolls into it
anyway is followed (or corrected) like any staged transition rather than
leaving the queue a track behind. Stop clears the device's `NextURI`. A seek within
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

## UPnP protocol negotiation

Code: `app/services/upnp/protocol_info.py` (parsing, alias families,
negotiation), `transport_errors.py` (fault classification and reasons),
`device.py` (`_media_for_track`, `_send_with_fallback`).

**What is kept.** Hydration stores a renderer's complete `GetProtocolInfo`
Sink list, verbatim and in device order, in `renderer.sink_protocol_info`
(`TEXT[]`): all four `protocol:network:contentFormat:additionalInfo` fields,
including MIME parameters (`audio/L16;rate=44100;channels=2`) and
`DLNA.ORG_PN/OP/FLAGS`. `supported_mime_types` stays as the bare-MIME view,
derived from it. If the device does not answer, the saved lists are kept. The
entries appear in renderer capabilities as `protocol_info` and, parsed, under
`protocol_negotiation` in `GET /api/player/upnp/diagnostics`.

**Choosing a label.** The stream's MIME type is matched against the advertised
`http-get` entries within its *alias family*: `audio/flac`/`audio/x-flac`;
`audio/mp4`/`audio/x-m4a`/`audio/m4a`; `audio/wav`/`audio/x-wav`/
`audio/wave`/`audio/vnd.wave`; `audio/mpeg`/`audio/mp3`/`audio/x-mp3`/…;
`audio/ogg`/`application/ogg`; `audio/aiff`/`audio/x-aiff`. The stream's own
name wins if advertised, else the first advertised alias. A label never
converts audio, so families only hold names for the *same bytes*:
`audio/aac` (ADTS) is not an alias of `audio/mp4` (MP4 container), and
`audio/L16` (headerless big-endian PCM) is not an alias of `audio/wav`. With
no matching entry (or only `http-get:*:*:*`, or no list at all) the stream's
own MIME is sent, as before; renderers saved before full entries were kept
fall back to their `supported_mime_types`.

**DIDL and HTTP agree.** When the label differs from the stream's MIME, the
stream URL gets `&mime=<label>`, and `/api/stream` serves that label as
`Content-Type` — but only if it is an alias of what it is actually sending;
otherwise the parameter is ignored. The stream proxy passes it through
untouched. The extra parameter does not disturb `TrackURI` matching, which
also matches on the stream token. The `<res>` URL is XML-escaped in DIDL.

**Load stages.** `SetAVTransportURI` and `SetNextAVTransportURI` describe the
stream in up to four ways, in order:

| stage | metadata |
|---|---|
| `default` | full DIDL, `res@protocolInfo="http-get:*:<mime>:*"` (the long-standing wildcard 4th field) |
| `advertised` | full DIDL with the renderer's own matching entry verbatim (prefers one without `DLNA.ORG_PN` or MIME parameters); skipped when it equals the default or none matched |
| `minimal` | title, creator, class and `res` only — no art, album, duration or size |
| `empty` | no metadata; the renderer sniffs the stream |

Only faults another description could fix move to the next stage: UPnP 402,
501, 600, 704, 714, a SOAP fault without a code, or a bare HTTP 500. Anything
else (e.g. 716 resource not found, 701/705 input or lock problems, no answer)
fails at once. Each attempt is logged. The stage that worked is remembered per
renderer and action, in memory, and tried first next time; `default` is the
implicit starting point.

**Errors.** A failed `SetAVTransportURI` or `Play` raises `RendererLoadError`
with a reason (`unsupported_format`, `stream_unreachable`,
`input_unavailable`, `renderer_busy`, `metadata_rejected`,
`action_unsupported`, `drm`, `unreachable`, `load_failed`) and a readable
detail naming the renderer, the MIME type (and whether the renderer advertises
it), the stream host for fetch failures, and the UPnP code, e.g. `Amp rejected
the stream's MIME type (audio/flac; not in the formats it advertises)
[SetAVTransportURI: UPnP 714 Illegal MIME-type]`. The orchestrator turns that
into `load_failed` with the detail for the UI. The last error per renderer is
in the diagnostics. `SetNextAVTransportURI` re-raises the device's own error
so staging's fault/transient classification is unchanged.

## UPnP events and watchdog polling

`app/services/upnp/events.py` subscribes (GENA) to a renderer's
**AVTransport** and **RenderingControl** services while Jamarr plays to it, so
`LastChange` events deliver transport state, `CurrentTrackURI` /
`AVTransportURI`, track duration, volume and mute as they change. Parsing and
`LastChange` expansion are async_upnp_client's (`UpnpEventHandler`,
`DmrDevice`); Jamarr owns the subscriptions so it can track each service.

**Callback server.** One `AiohttpNotifyServer` per process, bound to the
address UPnP already uses (`renderer.upnp_source_ip` / the default-route
address) on `renderer.upnp_event_port` (env `UPNP_EVENT_PORT`, default
**8113**; `0` = any free port). Host networking exposes it on the LAN; a
firewall must let renderers reach it. If it cannot bind, renderers simply stay
on polling (`server_error` in diagnostics). `renderer.upnp_events: false` (env
`UPNP_EVENTS=false`) turns eventing off entirely.

**Lifetime.** The playback monitor *acquires* the renderer when it starts and
*releases* it when it ends; subscriptions linger 120 s after release so pause,
skip and resume do not churn them. Stop (`stop_playback`), switching a client
to another renderer while nothing plays on the old one, and shutdown
unsubscribe at once.

**Health, per service.** A subscription counts as healthy once the SUBSCRIBE
was accepted **and** the device's initial NOTIFY arrived (proof it can reach
the callback), until it expires. It is renewed 60 s before expiry (or at half
its lifetime). A failed renewal (offline, refused, no initial event within
10 s) drops it and retries with backoff (5 s → 120 s), giving up after 6
failures in a row. Discovery re-hydrating the renderer into a new `DmrDevice`
(new BOOTID, LOCATION, refresh) or a change of Jamarr's own LAN address
re-subscribes from scratch; events for a superseded device are ignored.

**Monitor integration** (`monitor.py`, `_DeviceReader`). Without healthy
AVTransport events nothing changes: position, transport and `TrackURI` are
polled every second. With them:

- transport state and `TrackURI` come from events, and an event wakes the
  loop immediately (a remote pause, or a staged transition recognised from the
  `CurrentTrackURI` event without waiting for the next poll);
- `GetPositionInfo` is polled every `EVENT_POSITION_POLL_S` (5 s) and on every
  AVTransport event — position is never evented — and extrapolated in between
  while `PLAYING`;
- `GetTransportInfo` is polled every `EVENT_TRANSPORT_POLL_S` (15 s) as a
  watchdog. Polled values always win. A poll that disagrees with state evented
  more than 2 s earlier is a missed event; two in a row mark AVTransport
  **unreliable**: the monitor drops back to 1 s polling and the service is
  re-subscribed. After three such episodes eventing is given up for that
  renderer until it is reborn or Jamarr restarts;
- RenderingControl events write volume straight to `renderer_state.volume`
  (so a TV remote moves the app slider), replacing the periodic `GetVolume`;
  mute is reported as `muted` in `GET /api/player/state`.

Track identity drives reconciliation as before: staged transitions match on
`TrackURI` (exactly or by stream token), whether it came from an event or a
poll.

**`supports_events`.** Only a working subscription proves support: discovery
saves `false`, the event manager sets it `true` once AVTransport events have
actually arrived, and `false` when the device refuses SUBSCRIBE, never sends
its initial event, or is given up on. The verdict is kept in
`renderer.renderer_metadata.upnp_events` so later hydrations do not overwrite
it.

**Diagnostics.** `GET /api/player/upnp/diagnostics` → `events`: callback
server (address, port, error) and, per renderer, the verdict, event-derived
state and for each service: subscribed, SID, expiry/renewal timers, renewals,
event count, last event age, failures, last error, unreliability.

Tests: `tests/unit/test_upnp_events.py` (in-memory `FakeGena` /
`FakeNotifyServer` in `tests/helpers/upnp_fakes.py`).

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
per-device last-seen/BOOTID/availability and recent availability transitions,
plus event-subscription health (see [UPnP events](#upnp-events-and-watchdog-polling)).

## Audio output planning

Before a track is loaded (or staged) on a renderer, the orchestrator plans
which bytes to send: `app/services/playback_plan.py`. MIME alone does not say
whether a device can play a file (an `audio/mp4` may be AAC or ALAC; a FLAC may
be 192 kHz), so the plan works from the track's actual properties.

**Inputs**

- *Source* (`AudioProperties`): codec + container (from the scanner's
  `track.codec`, refined by a header probe for `.m4a` — AAC vs ALAC — and, only
  when a block-size constraint applies, FLAC STREAMINFO block sizes), sample
  rate, bit depth, channels.
- *Normalization*: the loudness gain from the stream claims. Gain changes the
  samples, so it rules out the original bytes.
- *Renderer constraints* (`RendererConstraints`): supported MIME types (alias
  aware: `audio/x-flac`, `audio/x-wav`, `audio/L16;rate=…`), supported codecs,
  max sample rate, max bit depth, max channels, FLAC block-size limit,
  `prefer_wav`, `allow_lossy`, an explicit `quality`. UPnP derives them from
  the sink protocolInfo (`protocol_info` entries when discovery records them,
  else `supported_mime_types`); Cast starts from the Default Media Receiver's
  formats (FLAC/MP3/AAC/Vorbis/Opus/WAV — no ALAC); `renderer.audio_constraints`
  in config.yaml overrides either per device. Nothing advertised = no
  constraints = the original bytes, as before planning existed.

**Order of preference**

1. **Original bytes** when container, codec, rate/depth/channel limits and any
   block-size constraint are all satisfied and no gain applies.
2. **Lossless remux** — same codec bytes, new container (Ogg FLAC → native FLAC
   when the renderer takes FLAC but not Ogg).
3. **Lossless decode** to FLAC, WAV or L16 (WAV first with `prefer_wav`).
   Resample (to the highest rate under the ceiling in the source's 44.1k/48k
   family), downmix or reduce depth **only** when a constraint requires it; the
   source depth is otherwise preserved. L16 is 16-bit big-endian PCM at an
   advertised rate.
4. **Lossy** (MP3 320, then Opus 128) only when the renderer accepts no
   lossless output, or when a lossy `quality` is explicitly configured.
   `allow_lossy: false` sends the original instead.

**Output** (`PlaybackPlan`): `action` (`original`/`remux`/`decode`/`lossy`),
the `OutputSpec` (format, MIME, rate, depth, channels, FLAC block size),
the operations applied, a human-readable reason and the resulting quality
label. The output spec rides in the stream token (`out`, `out_mime`,
`out_rate`, …), so `/api/stream` serves exactly what was planned and the
**HTTP Content-Type equals the MIME in DIDL-Lite / the Cast LOAD**. Transcoded
outputs go through the same cached transcode path as quality profiles (one
file per track × plan × gain), so Range requests, `Content-Length` and the
[stream proxy](#renderer-stream-proxy) behave exactly as for originals. DIDL
drops the original `res@size` when the bytes are transcoded. Tokens without
plan claims (browser/Android playback via `/api/stream-url`) are unchanged.

The plan for the current track appears as `output_plan` in
`GET /api/player/state` (the web player bar shows *source → output* with the
reason as a tooltip when the bytes are converted), and each renderer in
`GET /api/renderers` carries its resolved `output_constraints`.

**Device quirks are opt-in.** Some Cast receivers are reported to mis-handle
FLAC with large or variable block sizes (STREAMINFO > 4608, e.g. ffmpeg's 8192
blocks at 88.2/96 kHz) and some devices top out below the source sample rate.
Neither is imposed by default; set them per device once tested:

```yaml
renderer:
  audio_constraints:
    # key: renderer id (upnp:/cast: prefix optional),
    # UPnP UDN (uuid: prefix optional) or Cast UUID
    "cast:0b8f2c4e-…":
      flac_max_block_size: 4608   # re-encode FLAC with fixed blocks <= this
      max_sample_rate_hz: 96000
    "uuid:5f9ec1b3-…":
      max_bit_depth: 16
      max_channels: 2
      prefer_wav: true            # decode to WAV rather than FLAC
      allow_lossy: false
      # quality: mp3_320          # explicit lossy choice
      # supported_mime_types: [audio/wav, "audio/L16;rate=44100;channels=2"]
      # supported_codecs: [flac, pcm, mp3]
```

Hardware validation (rate/depth limits, block-size behaviour, seeking on WAV/L16
outputs) is still outstanding: these are mechanisms, not measured device facts.

## OpenHome / Linn

Not supported. A native backend (renderer-owned queue, device-side
shuffle/repeat/standby/source) was evaluated and not built: no OpenHome device
was available to test it. The design is in
[ADR-0011](decisions/0011-openhome-linn.md). Devices that also speak
AVTransport play through the UPnP backend.

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

Connection handling: every upstream request is sent with `Connection: close`,
so a `GET` body is piped verbatim until upstream EOF, with backpressure. A
`HEAD` (and any 1xx/204/304) is finished as soon as the re-cased headers are
out: the proxy does not wait for the upstream to hang up and forwards no body
even if one is wrongly sent, so a renderer's metadata probe never stalls on a
lingering upstream connection. While piping, the proxy also watches the
renderer's side of the socket; a renderer that drops mid-stream releases the
upstream connection at once. Tests: `tests/unit/test_stream_proxy.py`.

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

## AirPlay

Not supported. pyatv was evaluated on two real receivers and no backend
ships: it could not stream to one at all, needs `srptools<2`, and overrides
the receiver's volume on every stream start. Results and what a backend would
need: [ADR-0007](decisions/0007-airplay-raop.md).

## Cast media identity

Every item either Jamarr controller puts on a receiver carries its identity in
the media's `customData`:

| key | value |
|---|---|
| `jamarrTrackId` | Jamarr track id |
| `jamarrSource` | `server` or `android` (which controller queued it) |
| `jamarrContentPath` | the stream URL without its query (token) |
| `jamarrServer` | Android only: the server's `scheme://host:port` |
| `jamarrMime`, `jamarrDurationSeconds`, `jamarrArtUrl` | Android only: the original track's MIME, duration and art |

An id is only believed while `jamarrContentPath` matches the media's
`contentId` (pychromecast keeps the previous `customData` when new media
arrives without any). Media without these keys belongs to another app.

**Server restart.** `CastRendererBackend` forgets its loads on restart. When a
status shows `PLAYING`/`PAUSED` media stamped `jamarrSource = server`, it
re-adopts it as its own load (FINISHED-only, exactly once, as before) instead
of treating it as foreign, and reports `current_track_id`. The next
`GET /api/player/state` re-registers the status listeners. If the receiver is
one track further on than the stored queue (it played a queued item while the
server was down), `current_index` moves to it without a reload. Media that
finished while the server was down is not adopted; the position heuristic
decides as before.

**Receiver-driven volume.** Alongside the media listener the backend registers
a receiver (platform) status listener (`Chromecast.register_status_listener`
→ `new_cast_status`). Volume and mute changed on the device, by its remote or
by another controller update `renderer_state.volume` (and `muted` in
`/api/player/state`, in memory only) without polling or touching progress.
Clients without receiver listeners (plain or older pychromecast objects) keep
the media listener only.

## Cast receiver queue (preload)

Off by default. With `renderer.cast_queue` switched on for a device, the server
keeps the receiver's queue one item ahead, like UPnP staging:

```yaml
renderer:
  cast_queue:
    enabled: false          # true = every Cast device
    enabled_uuids: [ … ]    # or just these
    disabled_uuids: [ … ]   # never these (wins)
    preload_seconds: 20     # the item's preloadTime
```

- **Staging.** Once the current track has played 10 s, the orchestrator
  (`_maybe_stage_next`) sends `QUEUE_INSERT` (pychromecast 14 has no queue API;
  the raw message goes through `media_controller.send_message`) with the next
  queue track, its `customData` and a `preloadTime`. The token TTL is the
  staged one (`staged_stream_token_ttl_seconds`). A queue edit re-stages
  (`QUEUE_REMOVE` of the old item, when its `itemId` was in the reply). A
  refused insert is not retried for 60 s; the per-track path stays in charge.
  Any `LOAD` (play, skip, new queue) and Stop drop the staged item.
- **Transitions.** When a media status names the staged item, the backend
  makes it the followed load and reports `advanced_by_renderer` with its
  `current_track_id`. The orchestrator moves `current_index` with a
  conditional `UPDATE … WHERE current_index = <old>`, so it happens once and
  nothing is reloaded. If the item is no longer next (queue edited), the real
  next track is loaded instead (or playback stops at the end).
- **Completion.** A `FINISHED` for the current item while something is staged
  does not end the track: the receiver plays the item itself. If it has not
  within 5 s (`STAGED_FINISH_GRACE_S`, re-checked by a timer since no status may
  follow), the track ends the per-track way. `ERROR` on the queued item halts
  as usual.

**Evaluation.** What receiver queues give: the receiver knows the next item
early, can fetch and buffer it `preloadTime` seconds before the end, and moves
on without the controller — no `LOAD` round trip, no app re-launch and no
status wait between tracks, and the queue keeps going if the server is briefly
unavailable. What they don't prove: gapless playback. Whether the Default
Media Receiver actually preloads audio, and how much silence remains at a
transition, has **not been measured** (no hardware test yet); it varies with
receiver firmware and the codec. Per-track `LOAD` therefore stays the default,
and queue mode is an opt-in to evaluate on real devices. A continuous-stream
mode is a separate evaluation (see the ADRs).

## Android device-direct Cast sessions

`CastDeviceController` (Android) uses receiver queues (`MediaQueueData`) and
stamps every item as above. Pure logic lives in `CastQueueReconciler.kt`
(JVM-tested), SDK conversion in `CastMediaItems.kt`.

- **Passive attach vs explicit launch.** A session found at start-up or
  resumed (process restart, reconnect) is attached passively: the receiver's
  queue (`MediaQueue` item ids + items, fetched in batches as needed) is
  rebuilt into `QueuedTrack`s and, when it is this app's Jamarr queue, adopted
  — the app switches to that device and reports the queue to the server.
  Items lacking metadata are looked up by id (`GET /api/tracks?ids=`). Picking
  a device in the UI is an explicit launch; its media is still inspected, not
  replaced, until the user plays something.
- **Before replacing media.** Play/next/previous/jump first look at the
  receiver: if it already holds exactly that queue, they `queueJumpToItem`
  instead of reloading. Another app's media, or the server's own Cast queue, is
  reported ("Another app is playing on this device") and only replaced by an
  explicit play.
- **Other controllers.** Queue or current-item changes made elsewhere (another
  phone) are adopted from receiver status. While a load of ours is in flight
  (up to 15 s), statuses that still describe the old queue are ignored.
- **Leave vs Stop.** Switching to another output leaves the session
  (`endCurrentSession(false)`): the receiver keeps playing and can be resumed.
  Only the user's Stop stops the receiver's media.
- Route-volume updates, the optimistic-volume grace window and
  `IDLE_REASON_FINISHED` end-of-queue handling are unchanged.

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
- The active renderer's AVTransport and RenderingControl are subscribed with
  jUPnP `SubscriptionCallback`s (jUPnP renews them). `UpnpEventTracker` keeps
  per-service health with the server's rules: healthy once established *and*
  the initial event arrived; lost, failed or unreliable (two watchdog polls in
  a row contradicting events older than 2 s) means 1 s polling and a
  re-subscribe with backoff (5 s → 120 s). While healthy the poll loop polls
  every 5 s, extrapolates position in between and polls at once on a transport
  or TrackURI event; RenderingControl events carry remote volume changes into
  the app. A re-announced device (new service objects) is re-subscribed;
  switching renderer, stop and discovery shutdown unsubscribe.

## Deployment notes

- Docker needs `network_mode: "host"` for both UPnP SSDP and Cast mDNS. Host
  networking also exposes the renderer stream proxy (default 8112) and the
  UPnP event callback server (default 8113) on the host.
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
