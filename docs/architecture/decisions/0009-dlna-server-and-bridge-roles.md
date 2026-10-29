# ADR-0009: DLNA server and renderer-bridge roles: arbitration first, then scope

- **Status:** Proposed (design; no implementation)
- **Date:** 2026-10-28 (#316, Priority 3)

## Context

Today Jamarr is only a UPnP **control point**: it discovers renderers and
drives them. #316 raises two more roles.

1. **Media Server (ContentDirectory + ConnectionManager).** Browse-only TVs and
   players could pull music from Jamarr: browse/search, artwork, permissions
   and resource serving.
2. **Renderer / bridge facade.** Jamarr would expose Jamarr-managed playback
   devices (Cast, AirPlay, local) as UPnP MediaRenderers or OpenHome devices,
   so third-party control points (BubbleUPnP, Linn Kazoo, …) could drive
   them.

A separate item is a standalone Android Cast path without Play Services.

The hard part of the bridge is not SOAP. Once Jamarr's own clients and a
third-party controller both drive one device, two questions need answers:
**who owns the queue**, and **whose command wins**.

## Decision

### Queue ownership for a facade

Use the [ADR-0006](0006-renderer-capability-contract.md) vocabulary:

- **AVTransport facade → server-owned queue.** A third-party controller sends
  `SetAVTransportURI` / `SetNextAVTransportURI` with *its own* URIs, often
  from another media server. The facade treats that as a **foreign session**.
  Jamarr's queue for the device is suspended, not overwritten. Jamarr plays
  the foreign URI through the device backend and reports transport state
  back. `SetNext` maps to the backend's `SupportsNextTrackStaging` where
  present, and to a one-slot server queue elsewhere. History/scrobbling apply
  only when the URI resolves to a Jamarr track.
- **OpenHome facade → renderer-owned queue.** Playlist `Insert` / `DeleteId` /
  `ReadList` / `SeekId` edit *the Jamarr queue for that device* directly. The
  queue becomes shared, so Jamarr clients and Kazoo see one playlist. The
  facade advertises `queue_ownership: renderer` to controllers while the
  underlying device stays server-driven.

### Control arbitration

- **One owner per device at a time**, recorded with the renderer state: the
  `jamarr` session or a `foreign:<controller-ip>` session.
- **Last writer wins for transport commands** (play, pause, stop, seek,
  volume). Both sides see the change through status events: GENA LastChange
  for UPnP controllers, the existing state polling/SSE for Jamarr clients.
- **Queue replacement needs ownership.** A Jamarr client loading a new queue
  while a foreign session is active takes ownership back and stops the foreign
  URI. A foreign `SetAVTransportURI` does the reverse.
- **Volume is device state**, not session state, and is shared.
- The facade never answers `SetNextAVTransportURI` for devices that cannot
  honour it. Capabilities stay truthful to the facade too.

### Scope order

1. **Media Server first.** It is read-only and touches no playback state. It
   reuses existing library queries, artwork and `/api/stream`. It needs DIDL-Lite
   generation, an SSDP advertiser (today Jamarr only *searches*) and an
   **access model**: UPnP has no auth, so per-user permissions become
   LAN-trust plus a configurable "DLNA library user" whose stream tokens the
   server mints. It stays opt-in and off by default.
2. **OpenHome facade** after a native OpenHome backend exists
   ([ADR-0011](0011-openhome-linn.md), not built) and settles the Playlist ID
   mapping, since the facade mirrors it.
3. **AVTransport facade** last. Its foreign-session model is the most
   intrusive change to the orchestrator.

### Android Cast without Play Services

Recorded as a **separate feature**. The server keeps `pychromecast` and does
not replace its protocol implementation. Device-direct Cast on de-Googled
Android ([ADR-0004](0004-cast-dual-control-path.md)) would need a
CASTV2 client in Kotlin (TLS, protobuf, device auth) without the Cast SDK. It
is substantial and independent of the bridge roles.

## Consequences

- Nothing ships now. The ownership/arbitration model above is the
  precondition for any facade work.
- A Media Server makes the library readable by any LAN device, so it must
  stay opt-in.
- **Unverified**: controller behaviour (BubbleUPnP, Kazoo, TV built-in
  players) against a Jamarr facade, and DLNA profile requirements of specific
  TVs. No implementation or hardware test exists.
