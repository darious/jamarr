# Jamarr TUI

Keyboard-driven terminal client for Jamarr. Talks to the same `/api/*` endpoints
as the web and Android clients.

See [docs/tui.md](../docs/tui.md) for the design.

## Run

```bash
# from repo root
uv sync --all-packages

# Pass the server URL on the CLI…
uv run --package jamarr-tui jamarr-tui --server https://jamarr.example.com

# …or set it in the environment…
JAMARR_URL=https://jamarr.example.com uv run --package jamarr-tui jamarr-tui

# …or omit it and the login screen will prompt for URL + credentials.
uv run --package jamarr-tui jamarr-tui
```

## Requirements

- `mpv` on `$PATH` for local playback (or `ffplay` as a fallback once
  implemented).
- A terminal that handles 256-color or truecolor for ASCII artwork.
