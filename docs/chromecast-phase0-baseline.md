# Chromecast Phase 0 Baseline

Phase 0 records current playback behavior before the renderer backend refactor.
It should not change production code.

Status: completed on 2026-04-30 with the targeted Phase 0 gate passing.

## Current Control Paths

- Local web/mobile playback stores queue and progress in `renderer_state` under
  `local:<client_id>`. The client plays audio and reports progress.
- Server UPnP playback stores active renderer in
  `client_session.active_renderer_udn`. Player API endpoints call the process
  singleton `UPnPManager` directly.
- Android device-UPnP keeps server state pinned to `local:<client_id>`, then the
  phone controls the UPnP renderer and reports queue/progress back to the server.

## Current Ownership

- `client_session.active_renderer_udn`: active local/remote renderer per client.
- `renderer_state.renderer_udn`: queue, current index, progress, playing state,
  transport state, and volume.
- `app/api/player.py`: API orchestration and direct UPnP command routing.
- `app/services/player/monitor.py`: UPnP polling, progress/state updates,
  history logging, and auto-advance detection.
- `app/services/player/queue.py`: current auto-advance helper, hardwired to
  `UPnPManager`.
- `app/services/upnp/device.py`: UPnP stream URL, DIDL metadata, MIME selection,
  and device commands.

## Stream Tokens

- `/api/stream-url/{track_id}` requires auth and returns
  `/api/stream/{track_id}?token=...`.
- Stream tokens are stateless JWTs.
- Current default stream token TTL is 300 seconds.
- Tokens are bound to `track_id`; `verify_stream_token()` rejects tokens for the
  wrong track.

## Phase 0 Test Coverage

- `tests/helpers/fake_renderers.py`
  - Reusable fake UPnP manager command recorder.
  - Reusable fake status helpers for future backend/orchestrator tests.
- `tests/api/test_player_phase0_api.py`
  - Characterizes current remote UPnP transport command routing.
  - Characterizes current remote `/api/player/play` behavior and state writes.
- `tests/unit/test_player_phase0_unit.py`
  - Characterizes current `play_next_track_internal()` behavior.
  - Covers queue auto-advance and end-of-queue state.
- `tests/auth/test_stream_token_phase0.py`
  - Characterizes default stream token TTL and claims.

## Phase 0 Gate

Run:

```bash
./test.sh tests/api/test_player.py tests/api/test_stream.py tests/api/test_player_phase0_api.py tests/unit/test_player_phase0_unit.py tests/auth/test_stream_token_phase0.py
```

These tests should pass before starting Phase 1.
