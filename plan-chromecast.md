# Chromecast Playback — Implementation Plan

## Architecture

Build a single renderer orchestration layer with pluggable backend implementations.
Frontend clients and player API endpoints should deal with one renderer model and
one control API. Protocol-specific details stay inside backend adapters.

```
Web / Android
    |
    v
Player API
    |
    v
RendererOrchestrator
    |-- queue state
    |-- stream URL/token creation
    |-- auto-advance
    |-- progress/history/scrobble updates
    |-- renderer API response shape
    |
    v
RendererRegistry
    |-- upnp:<udn>  -> UpnpRendererBackend
    |-- cast:<uuid> -> CastRendererBackend
    |-- local:<id>  -> local client playback state
```

Backend responsibilities:

- Discover devices
- Persist/update renderer device metadata
- Translate play/pause/resume/stop/seek/volume/status calls into protocol calls
- Emit or expose device playback status/progress
- Hide protocol-native IDs, status strings, connection lifecycle, and libraries

Orchestrator responsibilities:

- Own canonical renderer identity
- Own queue state and active renderer state
- Create stream/artwork URLs with the correct token policy
- Trigger protocol backend playback
- Normalize progress/status into DB state
- Auto-advance tracks
- Log history and Last.fm state
- Serve one frontend/API contract

Renderer identity is canonical and backend-agnostic:

```
renderer_id = "{kind}:{native_id}"
```

Examples:

- `upnp:uuid:...`
- `cast:8f1c...`
- `local:web-client-id`

The old `udn` field remains accepted temporarily for backwards compatibility,
but new code should pass `renderer_id` and `kind`. Avoid adding new API surfaces
that assume every remote renderer has a UPnP UDN.

Two Cast control paths still exist:

| Path | Who discovers | Who controls | Server location | Use case |
|---|---|---|---|---|
| **Server-driven Cast** | Server (mDNS) | Server (`pychromecast`) | Same LAN as Cast devices | Home server, Docker on NAS |
| **Device-direct Cast** | Android (MediaRouter/Cast SDK) | Android | Anywhere public | VPS, public internet server |

Both Cast paths: Cast device fetches stream URL from server over HTTP. Default
Media Receiver handles playback. No custom receiver app for v1.

### Architecture reference — Music Assistant

Use Music Assistant's provider tree as an architecture reference, not as a
dependency:

- [`_demo_player_provider`](https://github.com/music-assistant/server/tree/dev/music_assistant/providers/_demo_player_provider)
  shows the smallest useful shape for a player provider: setup, discovery,
  register/update, unload, and per-player command methods.
- [`chromecast`](https://github.com/music-assistant/server/tree/dev/music_assistant/providers/chromecast)
  is the closest reference for Cast discovery, manual known-host discovery,
  duplicate discovery suppression, app launch, status callbacks, volume mapping,
  and Cast group handling.
- [`dlna`](https://github.com/music-assistant/server/tree/dev/music_assistant/providers/dlna)
  is the closest reference for UPnP/DLNA discovery, event subscription with
  polling fallback, manual reconnect, transport-state mapping, and renderer
  quirks such as passive speakers.
- [`airplay`](https://github.com/music-assistant/server/tree/dev/music_assistant/providers/airplay)
  is a future reference for capability differences, pairing/auth, fixed output
  formats, and stream/session-based playback.
- [`local_audio`](https://github.com/music-assistant/server/tree/dev/music_assistant/providers/local_audio)
  is a useful reference for local playback as a backend with limited capabilities.
- [`universal_player`](https://github.com/music-assistant/server/tree/dev/music_assistant/providers/universal_player)
  is a future reference for logical renderers that wrap one or more protocol
  renderers.
- [`sync_group`](https://github.com/music-assistant/server/tree/dev/music_assistant/providers/sync_group)
  is a future reference for grouped renderers and leader selection. Ignore for v1.

Concepts to borrow:

- Small provider/backend interface, not a full plugin ecosystem
- Separate provider/backend object from per-device player object
- Explicit capability model per renderer
- Normalized playback state independent of protocol-native status strings
- Discovery callbacks that update existing devices instead of duplicating them
- Manual discovery/address handling per backend
- Event callbacks where available, polling fallback where needed
- Per-protocol quirks contained inside the backend
- Logical renderers and sync groups later, after real devices are stable

### Delivery rules

- Build phases in order. Do not start a phase until the previous phase's delivery
  gate is satisfied.
- Keep phases mergeable independently. Each phase should leave local playback and
  existing UPnP behavior working.
- Prefer fake backend tests for orchestration logic. Use real device smoke tests
  only for protocol/library behavior that cannot be mocked reliably.
- Do not add a new protocol path directly to `player.py`. All new backend work
  must go through registry/orchestrator.
- Every endpoint/API shape change must keep backwards compatibility until web and
  Android callers have moved to `renderer_id`.

### Test commands

Run the relevant subset for each slice, then full gates before phase completion:

- Server tests: `./test.sh`
- Targeted server tests: `./test.sh tests/api/test_player.py tests/api/test_stream.py`
- Web tests: `cd web && npm run check && npm test`
- Web build: `cd web && npm run build`
- Android tests/build: `android/test.sh`
- Android instrumentation when device/emulator is available:
  `RUN_ANDROID_INSTRUMENTATION=1 android/test.sh`

---

## Phase 0 — Baseline & Characterization

Before changing architecture, lock down current behavior so refactors can move
internals without changing user-visible playback.

### 0.1 Current behavior inventory

- List every player endpoint that touches `UPnPManager`
- Document current local, server-UPnP, and Android device-UPnP flows
- Document DB ownership:
  - `client_session.active_renderer_udn`
  - `renderer_state.renderer_udn`
  - queue/current index/progress/volume fields
- Capture current stream-token behavior for browser, Android, and UPnP playback
- Capture current monitor behavior: polling interval, STOPPED detection,
  auto-advance, history logging, Last.fm now-playing updates

### 0.2 Test fixtures

- Add fake renderer/backend fixtures that record commands without touching network
- Add fake status event helpers for `PLAYING`, `PAUSED`, `STOPPED`, `IDLE`,
  progress updates, volume updates, and track-ended events
- Add sample renderer IDs:
  - `local:test-client`
  - `upnp:uuid:test-upnp`
  - `cast:test-cast-uuid`

### 0.3 Required test coverage

- API characterization tests for queue set, play, pause, resume, seek, volume,
  skip/index, clear queue, renderer selection, and `/api/player/state`
- Monitor characterization tests for auto-advance and history threshold logging
- Stream token tests proving existing 300s default behavior remains unchanged
  until the Cast token policy is introduced
- Existing `tests/api/test_player.py` and `tests/api/test_stream.py` must pass

### 0.4 Exit criteria

- Current UPnP and local playback behavior is covered by tests or explicitly
  documented as manual-only
- Fake backend/status fixtures exist and can be reused by Phase 1 tests
- No production behavior changes in this phase

---

## Phase 1 — Unified Renderer Backend API (Foundation)

Both Cast paths and future protocols need this. Without it, every player endpoint
and monitor path grows protocol checks (`if kind == "cast"`, `if kind == "upnp"`).
Phase 1 should prove the contract by moving existing UPnP behavior behind the
same backend API Cast will use.

Delivery strategy: ship this in small slices with UPnP behavior preserved at
each step. Do not add Chromecast control until UPnP works through the new
orchestrator.

### Phase 1 implementation status

Implemented in this branch:

- Protocol-neutral renderer contracts, registry, persistence helpers, and
  orchestrator foundation
- UPnP adapter wrapping the existing `UPnPManager`
- `renderer.kind`, `renderer.native_id`, `renderer.renderer_id`, Cast metadata,
  availability, and `client_session.active_renderer_id` migration/backfill
- Backwards-compatible renderer selection: old `udn` input and
  `active_renderer_udn` storage still work
- `/api/renderers`, `/api/player/renderer`, and `/api/player/state` expose
  canonical `renderer_id`/`kind` fields
- Player endpoints route playback controls through the orchestrator instead of
  importing `UPnPManager` directly
- Renderer-kind stream token policy hook: default streams remain 300s; Cast-kind
  stream URLs use duration-aware TTL capped by `CAST_STREAM_TOKEN_TTL_SECONDS`
- Server verification passed: `./test.sh` -> 335 passed, 1 skipped

Deferred to Phase 2/3:

- Real Chromecast/AirPlay backends
- Full callback-driven status pipeline for event-capable renderers
- Android UI migration to prefer `renderer_id` everywhere

### 1.1 DB migration

```
migrations/029_renderer_backend.sql
```

- Add `kind TEXT DEFAULT 'upnp'` to `renderer` table
- Add `native_id TEXT` column (UDN for UPnP, UUID for Cast)
- Add `renderer_id TEXT UNIQUE` column, canonical `{kind}:{native_id}`
- Backfill existing UPnP rows:
  - `kind = 'upnp'`
  - `native_id = udn`
  - `renderer_id = 'upnp:' || udn`
- Add `cast_uuid TEXT UNIQUE` column (Cast device UUID, nullable compatibility field)
- Add `cast_type TEXT` column (Chromecast, Google Home, Cast Group, Android TV, etc.)
- Add `last_discovered_by TEXT DEFAULT 'server'` column (`server`/`device`)
- Add `active_renderer_id TEXT` to `client_session`, or replace `active_renderer_udn`
  once compatibility work is complete
- Keep `active_renderer_udn` readable during migration for old clients/tests
- Consider renaming `renderer_state.renderer_udn` later; for now store canonical
  `renderer_id` in that column to minimize migration blast radius

### 1.2 Backend contracts

```
app/services/renderer/contracts.py
```

Define protocol-neutral dataclasses:

```python
@dataclass
class RendererCapabilities:
    can_play: bool = True
    can_pause: bool = True
    can_stop: bool = True
    can_seek: bool = True
    can_set_volume: bool = True
    can_mute: bool = False
    can_next_previous: bool = False
    can_enqueue: bool = False
    can_group: bool = False
    can_power: bool = False
    reports_progress: bool = True
    supports_events: bool = False
    requires_flow_mode: bool = False
    supported_mime_types: set[str] = field(default_factory=set)

@dataclass
class RendererDevice:
    renderer_id: str
    kind: str
    native_id: str
    name: str
    ip: str | None = None
    manufacturer: str | None = None
    model_name: str | None = None
    cast_type: str | None = None
    discovered_by: str = "server"
    capabilities: RendererCapabilities = field(default_factory=RendererCapabilities)
    available: bool = True
    enabled_by_default: bool = True
    is_group: bool = False
    group_members: list[str] = field(default_factory=list)

@dataclass
class RendererStatus:
    renderer_id: str
    state: str  # PLAYING, PAUSED, STOPPED, BUFFERING, IDLE, UNKNOWN
    position_seconds: float = 0
    duration_seconds: float | None = None
    volume_percent: int | None = None
    volume_muted: bool | None = None
    current_track_id: int | None = None
    current_media_url: str | None = None
    active_source: str | None = None
    available: bool = True
    ended: bool = False

@dataclass
class PlaybackContext:
    base_url: str
    user_id: int | None
    username: str | None = None
    token_ttl_seconds: int | None = None
```

Define `RendererBackend`:

```python
class RendererBackend(Protocol):
    kind: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    async def discover(self, refresh: bool = False) -> list[RendererDevice]: ...
    async def add_manual(self, address: str) -> RendererDevice | None: ...
    async def list_devices(self) -> list[RendererDevice]: ...
    async def unload_device(self, renderer_id: str) -> None: ...

    async def play_track(
        self,
        renderer_id: str,
        track: dict,
        context: PlaybackContext,
    ) -> RendererStatus: ...

    async def pause(self, renderer_id: str) -> RendererStatus: ...
    async def resume(self, renderer_id: str) -> RendererStatus: ...
    async def stop_playback(self, renderer_id: str) -> RendererStatus: ...
    async def seek(self, renderer_id: str, seconds: float) -> RendererStatus: ...
    async def set_volume(self, renderer_id: str, percent: int) -> RendererStatus: ...
    async def mute(self, renderer_id: str, muted: bool) -> RendererStatus: ...
    async def get_status(self, renderer_id: str) -> RendererStatus: ...
```

Optional callback interface for event-capable protocols:

```python
class SupportsStatusEvents(Protocol):
    def register_status_listener(
        self,
        renderer_id: str,
        callback: Callable[[RendererStatus], Awaitable[None]],
    ) -> Callable[[], None]: ...
```

UPnP can use polling. Cast can use media-controller callbacks. The orchestrator
should not care which mechanism produced a `RendererStatus`.

### 1.3 Renderer registry

```
app/services/renderer/registry.py
```

- Own backend instances keyed by `kind`
- Parse canonical `renderer_id`
- `get_backend(renderer_id) -> RendererBackend`
- `list_all() -> list[RendererDevice]`
- `discover_all(refresh=False) -> list[RendererDevice]`
- `get_device(renderer_id) -> RendererDevice | None`
- `set_active(client_id, renderer_id)` updates `client_session.active_renderer_id`
- Compatibility lookup: accept old UDN and map to `upnp:<udn>` when possible

### 1.4 Renderer orchestrator

```
app/services/renderer/orchestrator.py
```

Own the playback behavior that is currently spread across `player.py`,
`monitor.py`, and `queue.py`:

- `play_queue(client_id, queue, start_index, user, request_context)`
- `play_track(client_id, track_id, user, request_context)`
- `pause(client_id)`
- `resume(client_id)`
- `stop(client_id)`
- `seek(client_id, seconds)`
- `set_volume(client_id, percent)`
- `skip_to_index(client_id, index)`
- `handle_status(renderer_id, status)`
- `advance_queue(renderer_id)`
- `start_monitor(renderer_id)`
- `stop_monitor(renderer_id)`

Orchestrator rules:

- Local playback remains state-only; clients play audio themselves
- Remote playback always calls a backend via registry
- Queue updates, current index, progress, auto-advance, and history stay
  protocol-neutral
- Backend status strings are normalized before reaching DB/API
- `play_next_track_internal()` moves here and stops importing `UPnPManager`
- Capability checks happen before commands; unsupported commands become clear API
  errors or no-op fallbacks decided by orchestrator
- Backends may optimistically update status after a command, but orchestrator is
  the only layer that persists normalized player state

### 1.5 Shared renderer persistence

```
app/services/renderer/persistence.py
```

Borrow the Music Assistant idea of register/update semantics:

- `register_or_update(RendererDevice)` upserts renderer metadata by `renderer_id`
- Discovery callbacks update existing renderers in place
- Removed/unreachable devices mark `available = false`; do not immediately delete
- Disabled renderers stay persisted and are ignored by discovery/control
- Manual-discovery addresses are backend config, not global player API special cases
- Keep protocol-specific device info (`cast_type`, `supported_mime_types`, group
  details) in normalized columns or JSON metadata, but keep player API response flat

### 1.6 Backend/device split

Use a two-layer internal structure, matching the useful part of Music Assistant:

- Backend/provider object owns discovery, shared clients, lifecycle, caches, and
  manual addresses
- Per-device object owns native connection/control/status for one renderer

Examples:

- `UpnpRendererBackend` owns SSDP discovery, HTTP requester/session, notify server
  if added later, and UDN/device cache
- `UpnpRendererDevice` owns one DMR wrapper and UPnP command/status mapping
- `CastRendererBackend` owns `CastBrowser`, known hosts, discovery lock, and UUID cache
- `CastRendererDevice` owns one `pychromecast.Chromecast`, media controller,
  status listeners, app launch, and group metadata

Keep this split internal. Public code still depends only on `RendererBackend`.

### 1.7 UPnP backend

```
app/services/renderer/upnp_backend.py
```

Wrap existing `UPnPManager`/`UPnPDeviceControl` behind `RendererBackend`.

- Use existing UPnP discovery/control code initially
- Convert UPnP UDN to canonical `upnp:<udn>`
- Keep current UPnP polling monitor, but emit normalized `RendererStatus`
- Add/route real `stop_playback()` support; current facade lacks a stop method
- Keep UPnP MIME selection and DIDL generation inside UPnP backend
- No Cast logic in UPnP backend
- Map `TransportState.PLAYING`/`TRANSITIONING` to `PLAYING`
- Map `PAUSED_PLAYBACK`/`PAUSED_RECORDING` to `PAUSED`
- Map unknown/vendor states to `IDLE` or `UNKNOWN`, not raw strings
- Treat event subscription as optional; always keep polling fallback
- Detect passive/non-playable renderers and ignore or disable them

### 1.8 Refactor player.py

All player endpoints switch from direct `UPnPManager` usage:
```python
await upnp.set_renderer(udn)
await upnp.play_track(...)
```
to:
```python
await renderer_orchestrator.play_track(client_id, track_id, user, request_context)
```

Endpoints should not import `UPnPManager`, `CastManager`, `pychromecast`, or
protocol-specific modules. They should only use orchestrator/registry.

### 1.9 Stream token policy

Cast receivers parse the URL once — they don't re-auth. Current 300s TTL is too short for a 10-minute track.

- Add token TTL policy to orchestrator, not individual backends
- Add `CAST_STREAM_TOKEN_TTL_SECONDS` env var, default `86400` (24h) unless
  duration-based TTL is chosen before implementation
- Prefer duration-based TTL when `duration_seconds` is available:
  `max(1800, duration_seconds * 2)` capped at configured maximum
- When `kind == "cast"`, create token with Cast TTL
- Token still bound to track_id — scope is narrow even with long TTL
- Reissuing a stateless JWT does **not** invalidate previous URLs. If stale-token
  invalidation is required, add token nonce/version persistence and verify it in
  `/api/stream/{track_id}`
- Alternative considered but deferred: LAN-allowlist bypass (breaks auth model)

### 1.10 Unified monitor/status entry point

```
app/services/player/monitor.py (modify)
```

- `start_monitor(renderer_id)` dispatches through registry/backend capability
- UPnP backend uses poll loop and reports `RendererStatus`
- Cast backend subscribes to `pychromecast` media controller callbacks
- Orchestrator handles normalized status:
  - progress updates
  - volume sync
  - track-ended detection
  - auto-advance via `advance_queue(renderer_id)`
  - history/scrobble updates
- Avoid backend-specific calls from monitor code

### 1.11 Renderer API responses

- `/api/renderers` returns unified renderer objects:
  - `renderer_id`
  - `kind`
  - `native_id`
  - `udn` (compat for UPnP)
  - `name`
  - `ip`
  - `manufacturer`
  - `model_name`
  - `cast_type`
  - `discovered_by`
  - `capabilities`
- `/api/player/renderer` accepts `renderer_id`; accept `udn` as compatibility
- `/api/player/state` response includes `renderer_id` and `renderer_kind`
- Android/web should use `renderer_id` for new selections

### 1.12 Development slices

1. Contract-only slice:
   - Add `contracts.py`
   - Add fake backend implementation for tests
   - No endpoint behavior changes

2. Persistence slice:
   - Add migration
   - Add renderer persistence helpers
   - Backfill existing UPnP renderers
   - Keep old `udn` reads working

3. Registry slice:
   - Add `RendererRegistry`
   - Register fake backend in tests
   - Register UPnP backend behind feature flag or internal wiring
   - `/api/renderers` can return both old and new fields

4. Orchestrator read/write slice:
   - Move active renderer lookup/update into registry/orchestrator
   - Move queue/state writes behind orchestrator
   - Keep actual playback calls routed to existing UPnP path until tests pass

5. UPnP backend slice:
   - Wrap existing UPnP discovery/control
   - Commands flow through `RendererBackend`
   - Monitor emits normalized `RendererStatus`

6. Endpoint cutover slice:
   - Remove direct `UPnPManager` imports from `player.py`
   - Player endpoints call orchestrator only
   - Compatibility `udn` input still accepted

7. Cleanup slice:
   - Delete dead UPnP-specific monitor/queue paths only after all tests pass
   - Keep thin compatibility adapters if Android/web still rely on old response
     fields

### 1.13 Required test coverage

- Unit tests for `RendererCapabilities`, `RendererDevice`, `RendererStatus`, and
  renderer ID parsing/formatting
- Migration tests:
  - Existing renderer rows backfill to `upnp:<udn>`
  - `client_session` compatibility still reads old active renderer values
  - New `renderer_id` uniqueness is enforced
- Registry tests:
  - Backend lookup by `renderer_id`
  - Legacy UDN maps to `upnp:<udn>`
  - Unknown kind and unknown renderer fail cleanly
  - `discover_all()` merges multiple backends without duplicate IDs
- Persistence tests:
  - `register_or_update()` creates and updates devices
  - Removed devices mark unavailable, not deleted
  - Disabled renderer is ignored for control
- Orchestrator API tests with fake backend:
  - queue set/play calls backend with expected track/context
  - pause/resume/stop/seek/volume route to active backend
  - unsupported capability returns clear API error or documented no-op
  - status events update DB state
  - `ended=True` advances queue once
  - duplicate/end-of-load events do not double-advance
- UPnP adapter tests:
  - transport state mapping
  - volume scaling remains unchanged
  - stream URL and artwork URL generated as before
  - stop fallback works for devices with/without stop action
- Regression tests:
  - Existing local playback API behavior unchanged
  - Existing server-UPnP endpoint tests pass
  - Existing stream/auth tests pass

### 1.14 Delivery gate

- Web app can still play locally and control existing UPnP renderers
- Android device-UPnP still works
- `/api/renderers`, `/api/player/renderer`, and `/api/player/state` expose new
  fields while staying backwards-compatible
- `app/api/player.py` no longer imports protocol-specific backend libraries
- Fake backend tests cover the protocol-neutral orchestration path

**Files touched:** ~12
**New files:** ~6
**Migration:** 1

---

## Phase 2 — Server-Driven Cast

Server discovers and controls Cast devices on same LAN. Useful for home-server deployments (Docker on NAS, Pi, etc.).

### 2.1 Dependencies

```
pyproject.toml
```

Add `pychromecast>=14.0.0` and `zeroconf>=0.130.0` (if not already a transitive dep).

### 2.2 Cast backend (`app/services/renderer/cast_backend.py`)

- `CastRendererBackend` implements `RendererBackend`
- mDNS browser for `_googlecast._tcp.local` via `pychromecast.discovery`
- Accept manual known hosts / manual IPs in backend config
- Guard discovery callbacks with a lock and a pending-discovery set so the same
  UUID is not created twice while async setup is still running
- Parse Cast device info into `RendererDevice`:
  - `renderer_id = "cast:{uuid}"`
  - `kind = "cast"`
  - `native_id = uuid`
  - `cast_type = audio/display/group/android_tv/etc.`
- Manual IP entry via `add_manual(address)` for VLAN scenarios
- Persist through shared renderer persistence, not a Cast-specific save path
- `discover(refresh=True)` scans and returns normalized `RendererDevice` objects
- `list_devices()` returns cached devices
- Ignore dynamic/ephemeral Cast groups if they are not stable enough for v1
- Ignore passive multichannel child endpoints; expose the usable group/parent

### 2.3 Cast control behavior

- Backend wraps `pychromecast.Chromecast`
- `play_track()`: `cast.media_controller.play_media(url, content_type)` with metadata
- `pause()`: `cast.media_controller.pause()`
- `resume()`: `cast.media_controller.play()`
- `stop_playback()`: `cast.media_controller.stop()`
- `seek()`: `cast.media_controller.seek(seconds)`
- `set_volume()`: `cast.set_volume(percent / 100.0)`
- `get_status()` maps `cast.media_controller.status` to `RendererStatus`
- Metadata passed via `pychromecast.controllers.media.MediaMetadata` (title, artist, album, images for artwork)
- Artwork URL included in metadata — Cast receiver fetches it directly
- App launch is explicit:
  - Default Media Receiver for v1
  - Wait for launch callback/event with timeout
  - Treat timeout as renderer unavailable/failure, not silent success
- Cast callbacks happen on pychromecast/socket threads; dispatch state mutation
  back onto the asyncio event loop
- Cast receiver codec support must be explicit. If v1 does not transcode, document
  unsupported codecs/containers as expected failures.

### 2.4 Cast status events

- Implement `register_status_listener(renderer_id, callback)` if practical with
  `cast.media_controller.register_status_listener()`
- Callback-driven, no poll loop
- Convert Cast states to normalized `RendererStatus`
- On `PLAYING` → emit position/transport update
- On `IDLE` with previous state `PLAYING` → emit `ended=True`
- Grace period after `play_track()` (3s) to ignore transient `IDLE` during load
- Volume changes synced on callback
- Orchestrator receives events and owns DB updates/auto-advance

### 2.5 main.py wiring

- Register `CastRendererBackend` with `RendererRegistry` in FastAPI lifespan startup
- `startup`: `await registry.start_all()`
- `shutdown`: `await registry.stop_all()`
- No `CastManager` singleton; registry owns backend lifecycles

### 2.6 Development slices

1. Dependency/import slice:
   - Add dependencies
   - Add backend skeleton
   - Backend can start/stop without network discovery enabled

2. Discovery slice:
   - Add mDNS discovery and manual known hosts
   - Convert pychromecast device info into `RendererDevice`
   - Persist devices through shared persistence
   - Mark unavailable on connection loss/removal callback

3. Command slice:
   - Implement play/pause/resume/stop/seek/volume/get_status
   - Launch Default Media Receiver explicitly with timeout
   - Generate Cast-safe stream URL through orchestrator token policy

4. Status/event slice:
   - Register media/cast status listeners
   - Dispatch callbacks onto asyncio loop
   - Normalize Cast state into `RendererStatus`
   - Feed status into orchestrator

5. End-to-end slice:
   - Server-discovered Cast devices appear in `/api/renderers`
   - Web can select Cast renderer and use existing player controls
   - Auto-advance works from Cast ended event

### 2.7 Required test coverage

- Unit tests with mocked `pychromecast`:
  - discovery creates `cast:<uuid>` renderer IDs
  - duplicate discovery does not create duplicate devices
  - manual known host is passed to Cast browser
  - dynamic groups/passive endpoints are filtered according to v1 policy
  - app launch success, timeout, and failure paths
  - command methods call pychromecast APIs with expected values
  - volume maps 0-100 to 0.0-1.0 and back
  - callback thread handoff schedules event-loop updates
  - Cast states map to normalized `RendererStatus`
- Orchestrator integration tests with fake Cast backend:
  - Cast token TTL policy is used
  - `IDLE` after `PLAYING` emits one queue advance
  - transient `IDLE` during load grace period is ignored
  - volume/status callbacks update `renderer_state`
- API tests:
  - `/api/renderers` returns UPnP and Cast devices together
  - `/api/player/renderer` accepts `renderer_id=cast:<uuid>`
  - play/pause/resume/seek/volume endpoints route to Cast backend
- Optional manual smoke:
  - One real Chromecast or Google Home on LAN
  - Start playback, pause, seek, volume, skip, end-of-track auto-advance

### 2.8 Delivery gate

- Server-driven Cast is usable from web with the existing player controls
- Existing UPnP and local tests still pass
- Cast device disconnect does not crash server or leave monitor task stuck
- Unsupported Cast codecs are documented or covered by an explicit error path

**Files touched:** ~5
**New files:** ~2

---

## Phase 3 — Android Device-Direct Cast

Android phone discovers and controls Cast devices directly on the same Wi-Fi as the Cast device. Phone calls server REST API for stream URLs, but Cast protocol goes phone ↔ Cast device. Works when server is public (VPS) or on different network.

### 3.1 Dependencies

```
android/app/build.gradle.kts
```

Add Google Play Services Cast SDK:
```kotlin
implementation("com.google.android.gms:play-services-cast:21.5.0")
implementation("com.google.android.gms:play-services-cast-framework:21.5.0")
```

Requires Google Play Services on device (standard on all Google-certified Android).

### 3.2 Android renderer controller contract

Mirror the backend architecture on Android so the ViewModel does not need a
branch for every protocol.

```
android/.../renderer/DeviceRendererController.kt
```

Common contract:

```kotlin
interface DeviceRendererController {
    val kind: String
    val renderers: StateFlow<List<DeviceRendererInfo>>
    val state: StateFlow<DeviceRendererPlaybackState>

    fun start()
    fun stop()
    fun search()
    fun selectRenderer(rendererId: String)

    suspend fun playQueue(tracks: List<QueuedTrack>, startIndex: Int)
    suspend fun pause()
    suspend fun resume()
    suspend fun stopPlayback()
    suspend fun seek(seconds: Double)
    suspend fun setVolumePercent(percent: Int)
    suspend fun next()
    suspend fun previous()
    suspend fun jumpTo(index: Int)
}
```

Existing `UpnpDeviceController` becomes first implementation. New
`CastDeviceController` becomes second implementation.

### 3.3 Cast device controller (`android/.../cast/CastDeviceController.kt`)

New class implementing `DeviceRendererController`:

- **Discovery**: `MediaRouter` with `MediaRouteSelector` for Cast routes (`"com.google.android.gms.cast.CATEGORY_CAST"`)
- **Renderer list**: `StateFlow<List<DeviceRendererInfo>>` with canonical `cast:<uuid>` renderer IDs
- **Control**:
  - `selectRenderer(rendererId)` → connect via `CastContext.getSharedInstance().sessionManager`
  - `playQueue(tracks, startIndex)` → build `MediaQueueItem` list from tracks, load into `RemoteMediaClient`
  - `pause()`, `resume()`, `seek()`, `setVolume()` → delegate to `RemoteMediaClient`
  - `next()`, `previous()` → `RemoteMediaClient.queueJumpToItem()`
- **Position polling**: `RemoteMediaClient.addProgressListener()` with 1s interval, similar to UPnP
- **Auto-advance**: on `MediaStatus.MEDIA_STATUS_FINISHED`, advance queue internally and `queueJumpToItem()`
- Track metadata: `MediaMetadata` with title, artist, album, artwork URL
- Volume: 0.0-1.0 float internally, expose 0-100 to match app convention

### 3.4 Cast SDK app config

Cast Framework requires app configuration beyond Gradle dependencies:

- Add `OptionsProvider` implementation
- Add required `com.google.android.gms.cast.framework.OPTIONS_PROVIDER_CLASS_NAME`
  manifest metadata
- Use Default Media Receiver app ID for v1
- Verify behavior on devices without Google Play Services and report clear UI state

### 3.5 `QueuedTrack` — stream URL resolution

Same data class as UPnP's `QueuedTrack`. Stream URL obtained from server REST API (`/api/stream-url/{track_id}`) before building `MediaQueueItem` list. Cast device fetches the URL directly — phone does not proxy audio.

For Cast, request a Cast-safe stream token policy. Options:

- Add query parameter to `/api/stream-url/{track_id}?renderer_kind=cast`
- Add a new request body endpoint if token policy needs more context
- Or have server infer Cast from active renderer when device-direct Cast pins the
  server active renderer to `local:<clientId>`

### 3.6 ViewModel integration (`JamarrViewModel.kt`)

- Replace protocol-specific branching with an active `DeviceRendererController`
  where practical
- `RendererSource` enum gains `DEVICE_CAST` or uses `DEVICE` plus `kind`
- Renderer picker can show separate device sections, but selection stores canonical
  `renderer_id`
- Unified device-mode toggle controls both UPnP + Cast discovery unless UX needs
  separate toggles
- Playback actions dispatch to active controller contract, not concrete UPnP/Cast classes
- Device-direct Cast should pin server active renderer to `local:<clientId>` and
  report queue/progress/index through existing server APIs so history/scrobble
  behavior matches Android device-UPnP

### 3.7 Renderer picker UI

```
android/.../ui/components/RendererPicker.kt (modify)
```

- Add "Cast" section header when device mode is on and Cast devices are found
- `CastIcon` composable already exists in file (line 272) — no icon work needed
- Server-rendered Cast devices appear in server section (discovered by Phase 2), device-discovered Cast devices appear in device section

### 3.8 Cast button (optional)

Android Cast SDK includes `MediaRouteButton` for discovery. Can add to PlayerBar as quality-of-life. Not required for v1 — renderer picker is sufficient.

### 3.9 Development slices

1. Android controller contract slice:
   - Add `DeviceRendererController`
   - Adapt `UpnpDeviceController` to the interface
   - ViewModel can still use UPnP through the contract

2. Cast SDK setup slice:
   - Add dependencies
   - Add `OptionsProvider`
   - Add manifest metadata
   - Add Play Services availability handling

3. Cast discovery slice:
   - Discover Cast routes
   - Expose `DeviceRendererInfo` with `cast:<uuid>` IDs
   - Show Cast devices in renderer picker

4. Cast playback slice:
   - Resolve stream URLs with Cast token policy
   - Build `MediaQueueItem` list
   - Load queue into `RemoteMediaClient`
   - Implement pause/resume/seek/volume/next/previous/jump

5. Progress/history slice:
   - Report queue to server under `local:<clientId>`
   - Report progress/index to server like device-UPnP
   - Keep history and Last.fm behavior consistent

6. UX slice:
   - Add Cast section in renderer picker
   - Add optional Cast button only after renderer picker path works
   - Show clear unavailable state when Play Services or Cast session fails

### 3.10 Required test coverage

- Android unit tests:
  - `DeviceRendererController` contract behavior using fake controller
  - ViewModel dispatch routes to active controller by source/kind
  - Device-UPnP still reports queue/progress through the contract
  - Cast stream URL requests use selected Cast token policy
  - progress/index reporting works for device-direct Cast
  - renderer picker state stores canonical `renderer_id`
- Cast controller tests with fakes/mocks where feasible:
  - discovered route becomes `cast:<uuid>`
  - queue item metadata contains title/artist/album/artwork
  - volume maps 0-100 to Cast float
  - progress listener updates state
  - finished status advances internal queue and reports index
- UI tests:
  - renderer picker shows local, server, device-UPnP, and device-Cast sections
  - selecting Cast updates active renderer/source
  - missing Play Services shows non-crashing disabled/unavailable state
- Manual device smoke:
  - Android phone and Cast device on same Wi-Fi
  - Server can be on another network/public URL
  - Play, pause, seek, volume, skip, queue advance, history logging

### 3.11 Delivery gate

- Android can choose device-direct Cast without server LAN discovery
- Device-direct Cast logs history/scrobbles via existing progress path
- Android device-UPnP remains working through the new controller contract
- App handles no Play Services and failed Cast session without crash

**Files touched:** ~5
**New files:** ~3

---

## Phase 4 — Web App Cast UI

### 4.1 Renderer icons

```
web/src/lib/components/RendererPicker.svelte (modify)
```

- `CastIcon.svelte` — SVG cast icon (rectangle + WiFi arcs)
- `SpeakerIcon.svelte` — existing speaker for UPnP
- Show correct icon per `kind` field from `/api/renderers`

### 4.2 No other changes

Web app already talks to server REST API. Cast devices discovered by Phase 2 appear alongside UPnP. No new control flow.

### 4.3 Required test coverage

- Web unit/component tests:
  - renderer picker renders Cast icon for `kind="cast"`
  - renderer picker still renders UPnP/local renderers
  - selecting a renderer sends `renderer_id`
  - old `udn` fallback still works if API returns compatibility fields
- API/client tests:
  - player store accepts `renderer_id` and `renderer_kind`
  - state polling does not drop unknown future renderer kinds
- Manual browser smoke:
  - select local renderer
  - select UPnP renderer
  - select server Cast renderer
  - play/pause/seek/volume still call same API endpoints

### 4.4 Delivery gate

- Web UI needs no protocol-specific control path beyond icon/label rendering
- Existing web playback behavior unchanged for local and UPnP

**Files touched:** ~2
**New files:** ~1

---

## Phase 5 — Future Backend Shapes

These are not required for Chromecast v1, but the Phase 1 contract should avoid
blocking them.

### 5.1 Local audio backend

Use Music Assistant `local_audio` as a reference for a backend with narrow
capabilities.

- `local:<clientId>` stays frontend-controlled for web/mobile today
- A future server-local backend could expose host soundcards as `local_audio:<id>`
- Capability model must support volume-only or no-playback devices cleanly
- Hardware volume can fail; support fallback to software/app volume

### 5.2 Universal/logical renderer

Use Music Assistant `universal_player` as a reference only.

- Logical renderer wraps one or more protocol renderers for the same physical
  device
- Useful later when a device exposes both DLNA and Cast/AirPlay
- Prefer active external source/protocol based on current status
- Do not implement until physical-device matching is stable

### 5.3 Sync group renderer

Use Music Assistant `sync_group` as a reference only.

- Group renderer owns queue and delegates playback to a selected leader/member
- Needs leader selection, member compatibility, dissolve/reform, and progress
  ownership rules
- Defer until single-renderer Cast/DLNA behavior is reliable

### 5.4 Required test coverage before implementing any future backend

- Backend contract conformance tests reused from UPnP/Cast
- Capability matrix tests proving unsupported commands are handled consistently
- Logical renderer tests proving wrapped renderers do not duplicate history or
  fight over queue ownership
- Group tests proving leader changes do not double-advance or double-log plays

---

## Phase 6 — Edge Cases & Hardening

### 6.1 Cast groups (speaker groups)

Google Home speaker groups appear as single `CastDevice` with `cast_type = "group"`. `pychromecast` handles them transparently — the group UUID maps to a `Chromecast` object that routes audio to all members. No special handling required. Verify volume/position reporting works sensibly across group members.

### 6.2 Device reconnect

Cast devices can disconnect (power off, network change). Both control paths need reconnect logic:
- Server: `pychromecast` has auto-reconnect. Re-verify on monitor error.
- Android: `SessionManagerListener` handles session lifecycle.

### 6.3 Switching renderer mid-session

Orchestrator handles this protocol-neutrally: stop current backend renderer,
persist active `renderer_id`, reset/reload queue state as needed, then call the
new backend. Do not leave switching behavior inside `player.py`.

### 6.4 Volume scaling consistency

API uses 0-100 everywhere. UPnP devices: passed as-is (0-100). Cast: translate to 0.0-1.0 in device layer (`/ 100.0`). Cast → API: reverse translate (`* 100`). Single source of truth in protocol definition.

### 6.5 Race: track change while loading

Cast has an async load phase (~1-3s). If user skips track while previous track is loading, `pychromecast` / `RemoteMediaClient` handles the abort and re-queue internally. Add a `_loading` flag in monitors to suppress auto-advance during transitions (same pattern as `_mark_monitor_starting` in existing UPnP code).

### 6.6 Long-lived stream tokens

Phase 1's 24h Cast stream tokens are a weak point. Tokens are track-bound (`track_id` claim) so scope is limited, but a leaked URL plays one track for one day. Mitigations:
- Prefer duration-based TTL capped by config
- If true revocation is needed, add a token nonce/version store; reissuing a
  stateless JWT alone does not make old URLs stale
- Consider IP-agnostic design (no client IP binding — Cast device IP is unpredictable)
- Future: token bound to Cast device UUID (picked up from Cast protocol handshake)

### 6.7 Hardening test coverage

- Reconnect tests:
  - backend marks device unavailable after disconnect
  - backend recovers after rediscovery
  - active renderer state remains readable while unavailable
- Race tests:
  - skip during Cast load does not auto-advance wrong track
  - duplicate ended/status callbacks do not double-advance
  - pause near end of track does not falsely advance
  - renderer switch stops old backend before new backend starts
- Token tests:
  - duration-based Cast token TTL if implemented
  - expired Cast token returns 401
  - wrong-track token returns 401
  - nonce/version revocation if implemented
- Group tests:
  - Cast group volume/status mapping
  - group disconnect marks group unavailable without marking unrelated devices dead
- Regression suite:
  - server API tests
  - stream/auth tests
  - web component tests
  - Android unit tests

### 6.8 Delivery gate

- Known disconnect/race/token cases covered by automated tests
- Manual smoke across local, UPnP, server-Cast, and Android device-Cast completed
- Documentation updated for Docker host networking, codec support, token TTL, and
  Android Play Services limitation

---

## Phase Ordering & Dependencies

```
Phase 0 (Baseline) ──required──▶ Phase 1 (Foundation)
                                  │
                                  ├──required──▶ Phase 2 (Server Cast)
                                  │                   │
                                  │                   └──required──▶ Phase 4 (Web UI)
                                  │
                                  └──required──▶ Phase 3 (Device Cast)

Phase 6 (Hardening) follows Phase 2+3+4.

Phase 5 (Future Backend Shapes) is design-only for v1 and should not block Cast.
```

**Recommended build order:** 0 → 1 → 2 → 4 → 3 → 6

Phase 1 is the riskiest because it touches every playback endpoint. Phase 2 is
the highest-value deliverable. Phase 4 should follow Phase 2 so server-driven
Cast is usable from web before Android device-direct Cast starts.

Minimum phase gates:

- Phase 0: `./test.sh tests/api/test_player.py tests/api/test_stream.py`
- Phase 1: `./test.sh`, `cd web && npm run check && npm test`, `android/test.sh`
- Phase 2: `./test.sh`, plus manual server-Cast smoke on real hardware
- Phase 4: `cd web && npm run check && npm test && npm run build`
- Phase 3: `android/test.sh`, plus manual Android-to-Cast smoke on real hardware
- Phase 6: full regression gates plus all manual smoke paths

---

## Open Design Decisions

1. **Stream token TTL for Cast** — 24h is simple but long. Per-track tokens that live as long as the track duration * 2 (to cover pauses) would be tighter. Needs `duration_seconds` at token creation time.

2. **Server Cast in Docker** — Docker `network_mode: host` is already required for UPnP multicast. Same for Cast mDNS. Document this.

3. **Android Cast without Play Services** — Cast SDK requires Google Play Services. LineageOS / de-Googled devices can't use device-direct Cast (server-driven still works). Accept this limitation.

4. **Cast firmware compatibility** — `pychromecast` supports Cast protocol v2 (Chromecast gen 1+). Google Nest / Chromecast Audio / Google Home all work. Very old (2013) gen 1 Chromecast limited to v1 — test before claiming support.

5. **Auth on artwork URLs** — Cast receiver fetches artwork URL directly. Currently `/art/{sha1}.jpg` has no auth requirement. Confirm this stays true and document.
