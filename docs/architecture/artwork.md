# Artwork

How Jamarr stores, sizes, and serves cover art.

!!! info "Code"
    Backend: `app/media/art.py`. Frontend URL helper: `getArtUrl()` in
    `web/src/lib/api/index.ts`. UPnP album art: `app/services/upnp/device.py`.

## Serving model

All frontend artwork URLs go through `getArtUrl(sha1, size)` →
`/api/art/file/{sha1}?max_size={size}`. The server:

- **Snaps** the requested `max_size` up to the next allowed bucket:
  `100`, `200`, `300`, `400`, `600`.
- **Re-encodes** any resized image as JPEG (`quality=85`, `optimize=True`) and
  caches it under `cache/art/resized`.
- If `max_size` is **omitted**, serves the **original file** at original
  mime/quality — used for large hero/background images.

So a request for `50` or `60` is served at `100`; `120` is served at `200`.

## Size buckets in use

| Bucket | Typical usage |
|---|---|
| `100` | Track rows, search results, player-bar art, history rows, queue rows (all `TrackCard`-based usages request 100) |
| `200` | Drag-preview thumbnails |
| `300` | Home/discovery/charts/artists grids, similar artists, 4-up playlist thumbnails |
| `600` | Album cards, single playlist covers, accent-colour extraction source |
| original | Full-screen now-playing art, album hero, artist hero/secondary backgrounds |

## Quality rules

| Location | Output |
|---|---|
| `/art/test` (UPnP test image) | JPEG `quality=85`, 600×600 |
| `/api/art/file/{sha1}` with no `max_size` | original file, original mime/quality |
| `/api/art/file/{sha1}` with `max_size` | resized JPEG `quality=85`, `optimize=True` |
| UPnP/DLNA album art | requests `max_size=600` → 600px JPEG `quality=85` |

There is a single server-side quality setting for all resized artwork:
**JPEG `quality=85`**.

## Authentication

Artwork routes (`/art/...` and `/api/art/...`) are currently **unauthenticated**
so Cast and UPnP receivers can fetch images directly during playback. This is a
known trade-off — see the API reference note and
[ADR-0004](decisions/0004-cast-dual-control-path.md).
