# ADR-0006: Optional renderer capabilities (queue ownership, staging, pairing, output)

- **Status:** Accepted
- **Date:** 2026-10-28 (#316, "Common contracts")

## Context

[ADR-0002](0002-renderer-orchestration.md) gave every backend one
`RendererBackend` contract and a flat `RendererCapabilities` bag of booleans.
#316 adds devices whose behaviour does not fit that bag:

- **Who owns the queue differs.** UPnP AVTransport and server Cast play
  whatever Jamarr loads next (server-owned). OpenHome Playlist and Cast receiver
  queues hold the playlist on the device (renderer-owned; OpenHome evaluated in
  [ADR-0011](0011-openhome-linn.md)). A continuous PCM
  stream carries many tracks in one HTTP response, so the device never sees a
  track change.
- **Next-track staging** (UPnP `SetNextAVTransportURI`) works on some renderers
  and is switched off at runtime on others
  (`app/services/upnp/staging.py`).
- **Pairing**: AirPlay receivers may demand a PIN pairing or password, and the
  resulting credentials must persist ([ADR-0007](0007-airplay-raop.md)).
- **Output limits**: rate, bit depth, channels and codecs, which the audio
  planner needs; MIME strings alone do not carry them.

Two existing flags were also untrue: UPnP `supports_events` came from
discovery and was always true although no GENA subscription existed, and
`can_enqueue` meant nothing on any backend.

## Decision

Extend `app/services/renderer/contracts.py`, additively and with defaults that
describe a plain server-queue renderer:

| Field | Values | Default |
|---|---|---|
| `queue_ownership` | `server`, `renderer`, `continuous_stream` | `server` |
| `queue_operations` | subset of `read insert delete move clear play_item shuffle repeat` (renderer-owned only) | empty |
| `can_stage_next` | next track can be handed to the device ahead of time | `false` |
| `pairing` | `none`, `optional`, `required` | `none` |
| `has_credentials` | `null` when no pairing applies, else whether Jamarr holds them | `null` |
| `output` | `{codecs, max_sample_rate_hz, max_bit_depth, max_channels, source}` | all unknown |

`output.source` says how a limit is known: `advertised`, `protocol`,
`documented` or `measured`. An empty or null limit means **unknown**, not
unlimited.

Optional behaviour lives in `runtime_checkable` Protocols that backends
implement only when the operation works:

- `SupportsNextTrackStaging`: `next_track_staging_allowed`, `clear_next_track`.
- `SupportsPairing`: `begin_pairing`, `finish_pairing`, `set_password`,
  `forget_credentials`.
- `SupportsStatusEvents`: existing; now runtime-checkable.

`backend_supports(backend)` lists the optional contracts a backend implements.
No shipped backend owns its queue or pairs: the renderer-owned queue and
`SupportsPairing` are contract only, for a future OpenHome or AirPlay backend
([ADR-0011](0011-openhome-linn.md), [ADR-0007](0007-airplay-raop.md)). The
queue-editing Protocol itself is left to that backend.

A flag is true only when the operation works through Jamarr *now*:

- **UPnP** `can_stage_next` uses the same `staging_allowed()` policy as the
  monitor, which checks config override, runtime faults and the device advert.
  `supports_events` is true only when the manager reports a healthy
  subscription (`UpnpEventManager.supports_events`, or the verdict persisted
  from an earlier run).
- **Cast** reports a server-owned queue and Google's documented output limits
  (FLAC up to 96 kHz/24-bit), with `source: documented`.
- The **local** browser renderer uses the same capability shape.

`can_enqueue` keeps its old meaning (append to a device-side queue) and stays
false everywhere. Staging is the separate `can_stage_next` flag.

## Consequences

- `/api/renderers` gains keys inside `capabilities`. The clients ignore unknown
  keys: Android's `Json { ignoreUnknownKeys = true }` with a `Renderer` DTO that
  does not model capabilities, the web UI and the TUI (which read plain
  dicts). No client change is needed to keep working.
- The web player hides pause, seek and mute where `can_pause`, `can_seek` or
  `can_mute` is false. Android and the TUI do not use the flags yet.
- Backends that implement a Protocol must keep its flag in step. Tests in
  `tests/unit/test_renderer_contracts.py` pin the UPnP and Cast flags.
- `renderer_row_to_api` in `persistence.py` (unused) still builds the old flat
  dict.
