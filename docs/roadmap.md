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
    - AirPlay backend
    - server-local audio backend (host soundcard as `local_audio:<id>`)
    - universal/logical renderers (one physical device exposing DLNA + Cast)
    - sync groups (grouped renderers with leader selection)

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
