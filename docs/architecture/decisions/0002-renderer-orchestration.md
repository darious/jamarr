# ADR-0002: Unified renderer orchestration with pluggable backends

- **Status:** Accepted
- **Date:** 2026-04 (Chromecast refactor, Phase 1)

## Context

Playback originally lived in `app/api/player.py`, which called the `UPnPManager`
singleton directly. Adding Chromecast (and, later, AirPlay or grouped renderers)
that way would scatter `if kind == "cast"` / `if kind == "upnp"` branches across
every player endpoint and the monitor/queue code. Local, server-UPnP, and
Android device-UPnP each already had subtly different state ownership.

## Decision

Introduce a single **orchestration layer** with **pluggable protocol backends**
(`app/services/renderer/`):

- A protocol-neutral contract (`RendererBackend`, `RendererDevice`,
  `RendererStatus`, `RendererCapabilities`) every backend implements.
- A `RendererRegistry` that routes a canonical `renderer_id = "{kind}:{native_id}"`
  to the right backend.
- A `RendererOrchestrator` that owns all protocol-neutral behaviour: queue,
  index, progress, auto-advance, stream/artwork URLs + token policy, and
  history/Last.fm.
- Player endpoints depend only on the orchestrator/registry — never on
  `UPnPManager`, `pychromecast`, or protocol libraries.

The two-layer split (backend/provider vs per-device object) and the
capability/normalised-status model take inspiration from Music Assistant's
provider architecture (reference, not a dependency). Legacy `udn` input/storage
is accepted during migration.

## Consequences

- New protocols (Cast shipped this way; AirPlay/groups are designed-for) add a
  backend without touching endpoints or the monitor.
- Orchestration logic is testable with a fake backend, no real devices needed.
- One API/response shape for all renderers simplifies web/TUI/Android clients.
- Cost: an extra indirection layer and a migration that carries `udn`
  compatibility until all clients move to `renderer_id`. Worth it for the
  branching it removes.
