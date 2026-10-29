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

## Resize cache

Resized variants live under `cache/art/resized/{bucket}/{sha1[:2]}/{sha1}`.
How a miss is filled (`ensure_resized` / `_create_resized` in `app/media/art.py`):

- **One resize per key per process.** Concurrent cold requests for the same
  artwork and bucket share a single task; waiters are shielded, so one client
  going away cannot cancel the resize the others are waiting on. A failure
  reaches every waiter (they fall back to the original) and the next request
  starts a fresh attempt.
- **Atomic publication.** The JPEG is encoded into a uniquely named
  `.{sha1}.*.tmp` staging file in the same directory, fsynced, then renamed
  into place. A reader only ever sees a missing file or a complete one, in this
  process or in any other that shares the cache directory. Coalescing itself is
  per process: two server processes may each resize once, the rename keeps the
  result correct. A resize that finds the file already published does nothing.
  A hard crash mid-encode can leave a `.tmp` file behind; it is never served
  and can be deleted at any time.
- **Bounded, output-sized memory.** Resizes run on their own small thread pool
  (`artwork.resize_workers` in `config.yaml`, env `ART_RESIZE_WORKERS`,
  default 2), independent of the shared threadpool. JPEG sources are decoded
  at reduced scale (`draft`), every image is resized before it is converted,
  and transparency is flattened onto white **after** the resize, so a
  transparent cover costs memory proportional to the output rather than to a
  full-resolution RGB background. Output dimensions keep the aspect ratio and
  never drop below 1 px; nothing is upscaled.

## Authentication

Artwork routes (`/art/...` and `/api/art/...`) are currently **unauthenticated**
so Cast and UPnP receivers can fetch images directly during playback. This is a
known trade-off — see the API reference note and
[ADR-0004](decisions/0004-cast-dual-control-path.md).
