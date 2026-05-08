# Jamarr Terminal UI (TUI)

A keyboard-driven terminal client for Jamarr. Mirrors the most-used parts of the
SvelteKit web UI: login, search, browse, queue, history, playlists, and dual
local + UPnP playback. Runs against the same `/api/*` endpoints as the web and
Android clients — no backend changes.

This document is the v1 design plan. Code lives under `tui/` once
implementation starts.

---

## 1. Goals and non-goals

### Goals

- One-process Python TUI driven by the existing FastAPI HTTP API.
- Feature parity with the web UI for everyday playback and browsing.
- Both playback paths supported, like the web client:
  - **Local**: stream via `/api/stream-url/{id}` to a subprocess audio player.
  - **UPnP**: drive the server's `/api/player/*` routes against a chosen
    UPnP renderer.
- Renderer picker similar to the web `Renderers` page, listing UPnP devices
  exposed by `/api/renderers` plus a TUI-local entry.
- ASCII-art artwork rendering for fun and offline-readable detail screens.
- Fallback chain for the local audio backend: `mpv` → `ffplay` → fail loudly.

### Non-goals (v1)

- Charts, recommendations, scheduler, Last.fm admin, library scan, media
  quality, missing-albums, settings, scrobble admin.
- Persistent auth (refresh token storage, OS keyring). v1 re-logs in each
  session.
- Registering the TUI as a server-side "local" pseudo-renderer with state in
  `renderer_state`. The TUI's local mode is purely client-side; the server
  knows nothing about it.
- Graphical artwork via Sixel/Kitty/iTerm2 image protocols.
- Offline cache, downloads, sync.
- Mouse-only flows. Keyboard is the primary interface; mouse is a bonus.
- Windows-specific work. Linux/macOS terminals are the target.

---

## 2. Tech choices

### TUI framework: **Textual**

Textual gives async event loops (matches `httpx`), declarative widgets, CSS-ish
styling, screen routing, and a strong test harness. Raw `curses` is doable but
would burn time on layout, focus, and async plumbing that Textual already
solves.

### HTTP: **httpx (async)**

Already in repo dependencies. Single `AsyncClient` with a base URL and an
`Authorization: Bearer` header set after login.

### Audio backend (local mode)

Probe at startup, pick first available:

1. **mpv** via `--input-ipc-server=<socket>`. JSON IPC for play/pause/seek/
   volume/queue/observation of position. Best fit: gapless, accurate seek,
   programmable.
2. **ffplay**. Fallback only. Limited control (no IPC), so seek/volume become
   best-effort and the queue is implemented by tearing down and respawning the
   process per track.
3. None found → exit cleanly with a one-line error explaining what to install.

UPnP mode does not need a local audio binary.

### Artwork → ASCII

`pillow` (already a root dep, but TUI gets its own copy) downsamples
`/api/art/file/{sha1}?max_size=200` to terminal cell dimensions, then maps
luminance to a character ramp. Color via 24-bit truecolor where the terminal
supports it (`COLORTERM=truecolor`), else 256-color, else monochrome ramp.

### Config

CLI flags first, then environment, then a config file:

| Source        | Key                       | Default                              |
|---------------|---------------------------|--------------------------------------|
| `--server`    | server URL                | `https://jamarr.darious.co.uk`       |
| `--username`  | login username (optional) | prompt                               |
| `JAMARR_URL`  | server URL                | as above                             |
| config file   | `~/.config/jamarr-tui/config.toml` | optional overrides          |

Username/password are never persisted. Password is always prompted.

---

## 3. Repository layout

New top-level `tui/` as a uv workspace member. Root `pyproject.toml` gets a
`[tool.uv.workspace]` entry adding `tui` as a member; the TUI's own
`pyproject.toml` declares its slim dependency set.

```
tui/
  pyproject.toml
  README.md
  jamarr_tui/
    __init__.py
    __main__.py            # `python -m jamarr_tui` entrypoint
    cli.py                 # argparse, --server etc.
    config.py              # config file + env merge
    api/
      __init__.py
      client.py            # AsyncClient wrapper, auth, retry
      models.py            # Pydantic models mirroring API responses
      endpoints.py         # thin functions: search(), get_artist(), ...
    auth/
      login.py             # POST /api/auth/login, stores access token in memory
    playback/
      controller.py        # unified play/pause/seek/queue interface
      local_mpv.py         # mpv IPC controller
      local_ffplay.py      # ffplay subprocess controller (fallback)
      upnp.py              # /api/player/* driver
      probe.py             # backend detection + fallback chain
    art/
      ascii.py             # PIL → ANSI cells
      cache.py             # ~/.cache/jamarr-tui/art/ keyed by sha1
    screens/
      app.py               # Textual App, key bindings, screen stack
      login.py
      home.py              # new releases, recently added, discover
      search.py
      artist.py
      album.py
      playlists.py
      playlist.py
      queue.py
      history.py
      now_playing.py
      renderers.py         # picker
    widgets/
      player_bar.py        # bottom-of-screen track info, transport, volume
      track_list.py
      art_panel.py
      renderer_picker.py
      help_overlay.py
    keymap.py              # central key bindings
    theme.css              # Textual stylesheet
  tests/
    test_api_client.py
    test_ascii.py
    test_playback_probe.py
    test_local_mpv.py      # uses mpv if available; skipped otherwise
```

### Why a separate `pyproject.toml`

The root project depends on asyncpg, mutagen, pychromecast, async-upnp-client,
pillow, croniter, pylast, pychromecast — none of which the TUI needs.

TUI dependencies (rough):

- `textual`
- `httpx`
- `pillow`
- `pydantic` (transitively via FastAPI in the root, but we want it explicitly)

Workspace setup keeps `uv sync --all-packages` working from the repo root and
lets TUI tests run via the existing CI shape.

---

## 4. API surface used

Only existing endpoints. Documented in `docs/api.md`; re-listed here so the
TUI's coupling to the backend is explicit.

### Auth
- `POST /api/auth/login` — username + password, returns access token. v1 ignores
  the refresh cookie because the TUI is a non-browser client; on 401, prompt
  to re-login.

### Search and library
- `GET /api/search?q=`
- `GET /api/artists` (paginated; `limit`/`offset`/`starts_with`)
- `GET /api/artists/index` — letter index
- `GET /api/artists?mbid=` — single-artist detail
- `GET /api/albums?artist_mbid=` / `?album_mbid=`
- `GET /api/tracks?album_mbid=` / `?artist=`
- `GET /api/home/new-releases`
- `GET /api/home/recently-added-albums`
- `GET /api/home/discover-artists`

### Playlists
- `GET /api/playlists`
- `GET /api/playlists/{id}`
- `POST /api/playlists` (create)
- `POST /api/playlists/{id}/tracks` (add)
- `DELETE /api/playlists/{id}/tracks/{playlist_track_id}` (remove)
- `POST /api/playlists/{id}/reorder`
- `PUT /api/playlists/{id}` (rename)
- `DELETE /api/playlists/{id}`

### History
- `GET /api/history/tracks`
- `GET /api/history/albums`
- `GET /api/history/artists`

### Streaming
- `GET /api/stream-url/{track_id}` — call immediately before each track plays
  to avoid stale tokens (same lazy-resolution lesson as the Android Stage 3
  notes).
- `GET /api/stream/{track_id}?token=` — handed straight to the local audio
  backend.

### Artwork
- `GET /api/art/file/{sha1}?max_size=200`

### Renderers and UPnP playback
- `GET /api/renderers` — list. The TUI shows UPnP devices only and ignores
  the server's "local" pseudo-renderer since the TUI provides its own.
- `POST /api/player/renderer` — switch active server renderer.
- `POST /api/player/queue` — replace queue.
- `POST /api/player/queue/append`
- `POST /api/player/queue/clear`
- `POST /api/player/index`
- `POST /api/player/play` / `pause` / `resume` / `seek` / `volume`
- `GET  /api/player/state` — poll while a UPnP renderer is active.

The TUI sets `X-Jamarr-Client-Id: jamarr-tui-<random>` for player calls so the
server tracks UPnP state separately from any web/Android client.

---

## 5. Playback model

Two backends behind one `PlaybackController` interface:

```python
class PlaybackController:
    async def set_queue(self, tracks: list[QueuedTrack]) -> None: ...
    async def append(self, tracks: list[QueuedTrack]) -> None: ...
    async def play_index(self, idx: int) -> None: ...
    async def play(self) -> None: ...
    async def pause(self) -> None: ...
    async def next(self) -> None: ...
    async def prev(self) -> None: ...
    async def seek(self, position_s: float) -> None: ...
    async def set_volume(self, level: float) -> None: ...
    async def state(self) -> PlaybackState: ...      # polled by PlayerBar
```

Two implementations: `LocalController` (mpv/ffplay) and `UpnpController`
(server `/api/player/*`). Switching renderers swaps the active controller and
hands it the current queue.

### Local mode details

- `mpv` started once per session: `mpv --idle --input-ipc-server=/tmp/jamarr-tui-<pid>.sock --no-video --no-config`.
- Queue managed in-process; on track-end (mpv `end-file` event) advance to the
  next item, fetch a fresh stream URL, `loadfile`.
- Position polled every 500 ms via `get_property time-pos`.
- `ffplay` fallback: spawn one process per track, poll `wait()` to advance.
  Seek and live volume are not supported with ffplay; PlayerBar greys those
  controls out.

### UPnP mode details

- Polls `GET /api/player/state` once per second while a UPnP renderer is
  active, similar to the web UI.
- Queue lives server-side; TUI reflects, doesn't own.
- `/api/player/progress` is **not** sent from the TUI. The web UI uses it to
  report local-renderer progress for history; the TUI's local mode reports
  history differently (see below) and UPnP mode lets the server's existing
  monitor handle history.

### History reporting (local mode)

The web UI hits `/api/player/progress` with the `local` renderer to cross the
30s/20% history threshold. Since the TUI deliberately does not register a
server-side local renderer, v1 doesn't report local-mode plays as history.
That's a known gap, called out so we can fix it in v2 (likely via a small
`POST /api/history/local` adapter or by reusing `/api/player/progress` with a
synthetic client id).

---

## 6. Screen map

```
LoginScreen                          (entry; replaced by HomeScreen on success)
  └─ HomeScreen                      (default after login)
       ├─ SearchScreen               (/, focuses search input)
       ├─ ArtistScreen               (Enter on artist row)
       ├─ AlbumScreen                (Enter on album row)
       ├─ PlaylistsScreen
       │    └─ PlaylistScreen
       ├─ HistoryScreen
       ├─ QueueScreen                (q)
       ├─ NowPlayingScreen           (n; full-window player + ASCII art)
       └─ RendererPickerScreen       (r; modal)
PlayerBar widget docked at bottom on every screen.
```

### Key bindings (v1)

```
?            help overlay
q            queue
n            now playing
/            focus search box (or open SearchScreen)
r            renderer picker
h            home
H            history
p            playlists
space        play/pause
,            previous track
.            next track
[ / ]        seek -10s / +10s
- / +        volume down / up
g g          top of list
G            bottom of list
Enter        open / play
a            add to playlist (modal)
Q            quit
```

Bindings live in `keymap.py` so they can be themed/overridden later.

---

## 7. Rendering and theme

- Single Textual stylesheet at `theme.css`, palette tuned to match the
  dark/pink web theme so screenshots feel like the same product.
- Lists virtualized via Textual's `DataTable`/`OptionList`.
- ASCII art panel sized in cell units, re-rasterized on viewport resize. Cache
  rendered output keyed by `(sha1, width, height, color_mode)`.
- Player bar shows: current track, artist, album, position/duration, transport
  state, volume, active renderer name. Same surface area as `PlayerBar.svelte`.

---

## 8. Error handling and edge cases

- Server unreachable on startup → show retry screen with last error and
  `r` to retry, `s` to change server URL.
- 401 on any request → fall back to LoginScreen with the current path
  remembered; on re-login, return.
- Stream URL 404/410 (token expired) → re-fetch once, then surface error and
  skip to next track.
- Audio backend dies mid-playback → re-spawn once; if it dies again,
  surface error and stop the queue.
- UPnP device disappears → revert active renderer to TUI-local, log the
  reason in the help overlay's last-error slot.
- Terminal resize → all panels reflow; ASCII art re-rasterizes.

---

## 9. Testing strategy

`tui/tests/` runs under the same pytest harness as the root project (uv
workspace). Three layers:

1. **Unit**: API client URL building and DTO parsing, ASCII rasterizer
   determinism, keymap parsing, config merge order.
2. **Component**: Textual `Pilot`-driven snapshot tests for each screen
   against a mocked API client.
3. **Integration (manual)**: a `make tui-smoke` target that points the binary
   at a real Jamarr instance (default the prod URL) and walks login → search
   → play one track → switch renderer → quit. Documented in
   `tui/README.md`.

Out of scope for v1: end-to-end UPnP tests against a real renderer.

---

## 10. Build, install, run

```bash
# from repo root, sets up the workspace and installs TUI deps
uv sync --all-packages

# run the TUI against prod for smoke testing
uv run --package jamarr-tui jamarr-tui --server https://jamarr.darious.co.uk

# or the long form
uv run --package jamarr-tui python -m jamarr_tui
```

`tui/pyproject.toml` declares a console script `jamarr-tui` pointing at
`jamarr_tui.cli:main`.

No Docker image in v1. The TUI runs on the user's host so it can drive their
local audio.

---

## 11. Implementation order

Each step ends in something runnable.

1. **Workspace scaffold** — `tui/pyproject.toml`, root workspace entry, empty
   `jamarr_tui` package, `__main__` that prints the resolved server URL.
2. **API client + login** — `httpx` wrapper, `LoginScreen`, on success store
   the access token and show a placeholder home screen.
3. **Search + browse** — `SearchScreen`, `ArtistScreen`, `AlbumScreen`. No
   playback yet; selecting a track is a no-op.
4. **Local playback (mpv)** — `LocalController` over mpv IPC, queue management,
   `PlayerBar` widget. Selecting a track plays it. `space`, `, .`, `[ ]`,
   `- +` work.
5. **Local playback (ffplay fallback)** — backend probe, `LocalController`
   ffplay path, capability flags so `PlayerBar` greys out seek/volume.
6. **Queue and now-playing screens** — `QueueScreen`, `NowPlayingScreen`,
   add-to-queue from track lists, reorder/remove inside the queue screen.
7. **Renderer picker + UPnP playback** — `GET /api/renderers`, picker modal,
   `UpnpController` driving `/api/player/*`, polling `state`.
8. **Home screen sections** — new releases, recently added, discover artists.
9. **Playlists** — list, detail, create, add tracks, reorder, rename, delete.
10. **History** — paginated list + filter by scope/artist/album.
11. **ASCII artwork** — `art/ascii.py`, `ArtPanel` widget, wire into Artist,
    Album, NowPlaying screens.
12. **Polish** — help overlay, error toasts, theme pass, README.

Each step gets its own commit/PR. Backend changes should not be needed for
any of these; if a step uncovers a real gap, raise it as a separate ticket
rather than expanding the TUI PR.

---

## 12. Open questions for v2

- Should the TUI register a server-side "local" renderer so history reporting
  matches the web UI? Likely yes; needs a small client-id contract decision.
- Persistent auth (OS keyring) — worth it once daily-driver use shows the
  re-login prompt is a real annoyance.
- Sixel/Kitty image rendering for terminals that support it, behind a flag.
- Voice/text search shortcut from the player bar (mirror web's search overlay).
- Multi-pane layout (artist/album/track columns) for power users.
