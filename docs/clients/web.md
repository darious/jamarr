# Web Client

The primary Jamarr UI — a SvelteKit + Vite single-page app in `web/`.

!!! info "Code"
    `web/src/routes/` (pages) and `web/src/lib/` (components, stores, API
    helpers). Styling via Tailwind + Skeleton UI.

## Stack

- **SvelteKit** (Svelte) + **Vite** build/dev server
- **Tailwind CSS** + **Skeleton UI** components
- Talks to the backend only through `/api/*` (same contract as TUI/Android)

## Routes

`album`, `artist`, `artists`, `charts`, `discovery`, `history`, `login`,
`playlists`, `queue`, `renderers`, `settings`, plus the home page.

## Runtime model

- **Auth** — access token kept in memory (Svelte store); refresh-on-401 against
  the HttpOnly refresh cookie. See [Authentication](../architecture/auth.md).
- **Playback state** — polls `/api/player/state`; optimistic UI updates on user
  action, reconciled with the backend.
- **Renderers** — switch between local `<audio>`, UPnP, and Cast via the
  unified renderer API. See [Renderers & Playback](../architecture/renderers.md).
- **Artwork** — loaded via `getArtUrl()`; see [Artwork](../architecture/artwork.md).

## Development

```bash
./dev.sh   # backend (Docker, hot-reload) + Vite dev server on :5173
```

Edit `web/src/**` → instant HMR. See [Dev Mode](../getting-started/dev-mode.md).

Tests / checks:

```bash
./test-web.sh            # vitest + svelte-check + css lint + build
./test-web.sh unit       # vitest only
```

## Responsive design

The UI targets phone, tablet, and desktop breakpoints. The approach is
shell-first: a responsive app shell (compact mobile header, mobile nav, mobile
renderer switcher, phone search entry point, player-aware padding) before
per-page tweaks. Overlays (queue, renderer picker, now-playing, menus) become
bottom sheets / full-screen overlays on phone; the player bar renders distinct
compact/medium/full layouts by breakpoint.

Acceptance bar for any route at phone width: no horizontal overflow, no clipped
persistent controls, touch-sized tap targets, fully usable search and queue, and
readable detail pages without zooming. Remaining responsive work is tracked in
the [Roadmap](../roadmap.md).
