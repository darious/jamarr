# Jamarr TUI — Status

Snapshot for the in-progress terminal UI. Design lives in
[`docs/tui.md`](../docs/tui.md). Code lives under `tui/`.

## What works

### Build / launch
- uv workspace member at `tui/` with its own `pyproject.toml`.
- Console script `jamarr-tui` (also `python -m jamarr_tui`).
- `--server` flag and `JAMARR_URL` env. No default — when neither is set,
  the login screen prompts for the URL alongside username + password.
- `--username` flag and `JAMARR_USERNAME` env pre-fill the login form.
- Login screen accepts URL + username + password. Auto-prepends `https://`
  if the scheme is missing. Tab/Enter cycles fields, button or final-field
  Enter submits. On auth/connect failure the client is torn down and the
  error surfaces inline; the user can retry without restarting.
- `JamarrClient` refreshes JWT access tokens with the server-managed refresh
  cookie every 8 minutes and retries one 401 after refreshing, so long
  playlist playback survives the default 10-minute access-token TTL.
- `JamarrClient` and `PlaybackController` are constructed only after the
  login form succeeds, so mpv doesn't spin up until we have a server.

### Playback
- mpv subprocess controlled over JSON IPC: `loadfile`, pause toggle, seek,
  volume, time-pos / duration / pause / end-file observation. Auto-advance
  on `end-file`.
- `mpv.stop_playback` clears the current file but keeps mpv idle; used by
  queue clear and by removing the currently-playing track.
- `PlaybackController` owns the queue, the current index, the volume
  level (0–1, mirrored to mpv) and the auto-advance flag. `vol_up`/
  `vol_down` step in 5 % increments.
- When a UPnP / Cast renderer is active, `PlaybackController` polls
  `/api/player/state` for queue, current track, transport state, position,
  duration and volume. Transport controls route to `/api/player/{pause,
  resume,seek,volume,index}` instead of local mpv, and local mpv is stopped
  while the remote renderer is active. Remote progress/history is handled by
  the backend monitor/event path.
- History reporting for local-mode playback. The TUI mirrors queue / index
  to the server's `local:<client_id>` renderer state via `/api/player/queue`
  and `/api/player/index`, then posts `/api/player/progress` every 5 s while
  a track is loaded. Server crosses the same 30 s / 20 % threshold the web
  UI uses and logs the play. Normal users can mirror queue / index and
  control playback; only manual renderer add and debug/test endpoints are
  admin-only.

### Screens
- Home screen mirrors the web/Android layout: New Releases, Recently Added
  Albums, Recently Played Albums, Discover (Newly Added) Artists, Recently
  Played Artists. Sections fetched in parallel from `/api/home/*` and
  `/api/history/{albums,artists}`. Enter on a row opens album / artist.
- Album screen → `/api/tracks?album_mbid=…`. Enter starts playback from the
  selected row and queues the rest of the album. Art panel beside the
  track list.
- Artist screen → `/api/albums?artist_mbid=`. Main releases first, then
  appears-on. Enter on an album opens it. Art panel beside the list.
- Search screen (`/` from home): debounced `/api/search`, three sections —
  artists / albums / tracks. Enter on an artist opens their albums, Enter
  on an album opens it, Enter on a track plays it as a single-track queue.
- Queue screen (`q`): full queue with the current track marked, Enter
  jumps to a row, `d` / `Delete` removes via `/api/player/queue/reorder`,
  `J` / `K` reorder, `c` clears via `/api/player/queue/clear`.
  Auto-refreshes once a second so the marker follows playback.
- Now Playing screen (`n`): full-window track / artist / album, large
  ASCII / Kitty art panel, custom `_SeekBar` widget styled with `$accent`
  / `$boost` for clear filled-vs-empty rendering, time markers either side
  of the bar. PlayerBar docked at the bottom for the same status line as
  every other screen.
- Playlists screens. List screen (`p` from home) supports create (`c`,
  prompts via a modal Input), rename (`R`), delete (`d`), Enter to open.
  Detail screen plays from any row, removes via `d` / `Delete`, reorders
  via `J` / `K`, posts to `/api/playlists/{id}/{tracks,reorder}`.
- Help overlay (`?` from anywhere). ModalScreen listing key bindings.
- Renderer picker (`ctrl+r` from anywhere). Lists `/api/renderers`, marks the
  active local / UPnP / Cast renderer, `r` rescans, Enter posts
  `/api/player/renderer` and switches the controller into local or remote
  mode.

### Widgets
- `PlayerBar` bottom-docked status bar on every non-modal screen: track —
  artist · state · position / duration · `vol NN%`. Ticks at 0.5 s, posts
  `/api/player/progress` every 5 s.
- `ArtPanel` prefers the Kitty graphics protocol when the terminal
  supports it (Ghostty on Linux + macOS, Kitty itself). PNG transmitted
  once via APC `a=t,f=100` and re-placed via `a=p` with a stable
  `placement_id` on every render at the panel's screen coordinates;
  cell box (`c` × `r`) is computed from the source aspect ratio + the
  terminal's reported pixel cell aspect so square art doesn't stretch. On
  non-Kitty terminals the panel falls back to half-block (`▀`) ANSI
  rendering via PIL + LANCZOS. Source bytes cached at
  `~/.cache/jamarr-tui/art/<sha1>-<max_size>`.
- Source size for art is picked per panel: panel cell box × ~10 × 20 px
  per cell, snapped up to the server's allowed sizes
  (100 / 200 / 300 / 400 / 600). The fetch is deferred to the first
  resize that has non-zero dimensions, then re-fetched if the panel
  later grows past the cached size.
- `_SeekBar` (Now Playing): two `Static`s in a horizontal row, the left
  one carrying `$accent` background sized to the played fraction of the
  container, the right one carrying `$boost` filling the remainder.
  Recomputes on `progress` change and on resize.

### Globals
- `ctrl+q` quits from anywhere.
- `?` toggles the help overlay.
- `-` / `+` (and `=`) adjust volume from any screen — controller owns the
  level, so the value is consistent across PlayerBar and Now Playing.
- `ctrl+r` opens the renderer picker.

### Logging
- `/tmp/jamarr-tui.log` — app + controller + mpv-event level (rewritten
  on every launch).
- `/tmp/jamarr-tui-<id>.mpv.log` — raw mpv stdout/stderr (path printed
  in the app log on startup, rewritten on every launch).

## What is not built yet

Deferred for now:

1. History screen — paginated `/api/history/tracks` browser with filters.
2. A non-mpv local audio backend. ffplay fallback has been dropped; mpv is
   the supported local playback backend.

## Key bindings

| Key            | Action                          |
|----------------|---------------------------------|
| `space`        | play / pause                    |
| `,` `.`        | previous / next track           |
| `[` `]`        | seek −10 s / +10 s              |
| `-` / `+`      | volume down / up (anywhere)     |
| `escape`       | back / close overlay            |
| `r` (home)     | refresh sections                |
| `r` (picker)   | rescan renderers                |
| `/` (home)     | open search                     |
| `p` (home)     | playlists                       |
| `q`            | queue screen                    |
| `n`            | now-playing screen              |
| `?`            | help overlay (anywhere)         |
| `ctrl+r`       | renderer picker (anywhere)      |
| `ctrl+q`       | quit (anywhere)                 |
| `Q` (home)     | quit (alias)                    |
| `Enter`        | open / play (in lists)          |
| `d` / `Delete` | remove track (queue / playlist) |
| `J` / `K`      | move track down / up            |
| `c`            | clear queue / create playlist   |
| `R`            | rename playlist                 |

## How to run on a machine with audio

```bash
# from repo root
uv sync --all-packages

# Pass the server on the CLI…
uv run --package jamarr-tui jamarr-tui --server https://jamarr.example.com

# …or in the environment…
JAMARR_URL=https://jamarr.example.com uv run --package jamarr-tui jamarr-tui

# …or omit it and the login screen will prompt.
uv run --package jamarr-tui jamarr-tui
```

Requirements:

- `mpv` on `$PATH`.
- A working audio output (PipeWire / PulseAudio / ALSA). Headless LXC
  containers reached over SSH need audio forwarding to the host.
- For inline artwork: a Kitty-graphics-capable terminal (Ghostty on
  Linux / macOS, or Kitty). Other terminals fall back to half-block
  ANSI art.

## Known sharp edges

- mpv is launched with `--no-config` for predictable TUI playback, so user
  mpv config files do not affect the session.
- mpv is the only supported local audio backend.
- Manual renderer add plus player debug/test endpoints are admin-only.
  Normal users can list/rescan renderers, select a renderer, mutate their
  queue, and control playback across local, UPnP and Cast renderers.
- ASCII fallback uses the terminal's reported pixel cell aspect for art
  aspect preservation, falling back to ~2 : 1 when the terminal doesn't
  expose pixel dimensions.
