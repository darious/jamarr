# Roadmap

Deliberately deferred work — things designed-for but not built, and known
trade-offs we've chosen to live with for now. This is intent, not a commitment.

## Renderers / Cast

- **Stream-token revocation** — Cast tokens use a long, duration-aware TTL
  ([ADR-0003](architecture/decisions/0003-cast-stream-token-policy.md)). True
  revocation needs a token nonce/version store; reissuing a stateless JWT does
  not invalidate old URLs. Deferred.
- **Transcoding for Cast** — v1 does not transcode; unsupported codecs fail on
  the receiver. A transcode path would widen format support.
- **Future backend shapes** — the renderer contract is designed to allow, but
  does not yet implement:
    - server-local audio backend (host soundcard as `local_audio:<id>`)
    - universal/logical renderers (one physical device exposing DLNA + Cast)
    - sync groups (grouped renderers with leader selection)

## Playback improvements (#316)

Where each item of #316 stands. "Unverified" means it is implemented and
tested with fakes only, with no hardware measurement.

| Item | Outcome |
|---|---|
| Android UPnP: stop on failed `SetAVTransportURI` | Done (PR #347) |
| Cast LOAD rejection/timeouts surfaced to player state | Done (PR #347) |
| Cast advances only on `FINISHED` | Done (PR #347) |
| UPnP `SetNextAVTransportURI` staging + `TrackURI` reconciliation, provisional support, per-renderer override | Done (PR #347). Real-hardware gapless playback is unverified. |
| Full `GetProtocolInfo` entries + metadata negotiation/retries | Done. Complete Sink entries kept, MIME alias families, bounded fault-specific load retries. Unverified on hardware. |
| UPnP GENA events with watchdog polling | Done (server and Android). Capabilities report `supports_events` only through a healthy subscription ([ADR-0006](architecture/decisions/0006-renderer-capability-contract.md)). Unverified on hardware. |
| Renderer-aware audio output planning | Done (`app/services/playback_plan.py`, per-device `renderer.audio_constraints`). Device limits are exposed as `capabilities.output`. Unverified on hardware. |
| Cast session/queue restore, receiver-driven volume, server receiver queues/preload | Done. Receiver queue/preload is opt-in (`renderer.cast_queue`); transition silence unmeasured. |
| Continuous PCM/audio stream mode | Evaluated: opt-in only, and only if measured Cast queue transitions still gap ([ADR-0010](architecture/decisions/0010-continuous-stream-mode.md)) |
| Native OpenHome/Linn backend | Evaluated, not built: no OpenHome device available to test against; design recorded ([ADR-0011](architecture/decisions/0011-openhome-linn.md)) |
| AirPlay/RAOP | Evaluated on two real receivers, not built: pyatv 0.18 could not stream to one, needs `srptools<2`, and overrides receiver volume ([ADR-0007](architecture/decisions/0007-airplay-raop.md)) |
| Fire TV | Not built: no Fling; a server-side Matter Casting client is not viable today ([ADR-0008](architecture/decisions/0008-fire-tv-matter-casting.md)) |
| DLNA Media Server / UPnP-OpenHome bridge facade | Designed, not built: queue ownership + arbitration model, Media Server first ([ADR-0009](architecture/decisions/0009-dlna-server-and-bridge-roles.md)) |
| Android Cast without Play Services | Recorded as a separate feature. The server keeps `pychromecast`. |
| Common contracts (queue ownership/editing, staging, pairing, output constraints) | Done ([ADR-0006](architecture/decisions/0006-renderer-capability-contract.md)). The web hides pause/seek/mute a renderer lacks. |
| Hardware validation | Partly done. Checked on a Naim Uniti Atom, a Sony XR-65X90J and a Sonos Play:3 without audio: protocolInfo negotiation (all three get the original FLAC), GENA subscribe/renew/unsubscribe, volume read-back (the TV events a wrong volume; fixed by reading it back). **Open:** gapless silence, transitions/history, Cast advance and resume, conversion and seeking on real devices. |

## Android / Android Auto

- Voice/text search in Android Auto (`onSearch`) — intentional v1 omission;
  browse covers the use case.
- "Shuffle artist" / shuffle-all entry points in Auto.
- The optional `/api/android` browse adapter — existing endpoints map to the
  browse tree without it; revisit only if a real awkwardness justifies it.
- ViewModel test coverage for Cast vs UPnP dispatch via injected fake
  controllers; Cast controller tests around MediaRouter/RemoteMediaClient.

## Web responsiveness

The mobile-first pass is shell → player/queue → shared components → home/discovery
→ detail pages → dense pages → QA sweep (see [Web Client](clients/web.md)). Track
remaining route-level work against the acceptance bar there.

## API surface

- Consistent pagination on library browse endpoints (`/api/albums`, `/api/tracks`
  are currently unpaginated) — flagged for Android Auto scale.
- Review whether artwork routes should stay unauthenticated long-term (currently
  required for Cast/UPnP receivers — see
  [ADR-0004](architecture/decisions/0004-cast-dual-control-path.md)).
