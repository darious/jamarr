# Artwork Audit

## How artwork quality is determined

- Backend entry point: `app/media/art.py`
- URL helper: `web/src/lib/api/index.ts`
- All frontend artwork URLs use `/api/art/file/{sha1}?max_size={size}` via `getArtUrl(...)`.
- Server snaps requested sizes to the next allowed bucket: `100`, `200`, `300`, `400`, `600`.
- Any resized image is re-encoded as `JPEG` with `quality=85` and `optimize=True`.
- If `max_size` is omitted, the original file is served with its original mime/quality. Several large hero/background call sites now use the unsized/original path.

## Backend quality rules

| Location | Usage | Quality used |
| --- | --- | --- |
| `app/media/art.py:15` | Generated test artwork (`/art/test`) | JPEG, `quality=85`, 600x600 |
| `app/media/art.py:101` | Main artwork serving endpoint | Original file if no `max_size`; otherwise resized output |
| `app/media/art.py:171` | Cached resized derivatives | JPEG, `quality=85`, `optimize=True` |
| `app/services/upnp/device.py:114` | UPnP/DLNA album art URL | Requests `max_size=600` -> effective 600px derivative, JPEG `quality=85` |

## Frontend artwork usages

### Shared helpers/components

| Location | Usage | Requested size | Effective served size | Quality used |
| --- | --- | ---: | ---: | --- |
| `web/src/lib/api/index.ts:153` | `getArtUrl(sha1, size)` helper | Variable | Snapped to 100/200/300/400/600 | Resized JPEG `quality=85` |
| `web/src/lib/components/TrackCard.svelte:100` | TrackCard artwork image | 100 | 100 | JPEG `quality=85` |

### Small artwork

| Location | Usage | Requested size | Effective served size | Quality used |
| --- | --- | ---: | ---: | --- |
| `web/src/lib/components/SearchBar.svelte:175` | Artist search result | 100 | 100 | JPEG `quality=85` |
| `web/src/lib/components/SearchBar.svelte:236` | Album search result | 100 | 100 | JPEG `quality=85` |
| `web/src/lib/components/SearchBar.svelte:308` | Track search result | 100 | 100 | JPEG `quality=85` |
| `web/src/lib/components/PlayerBar.svelte:549` | Player bar current track art | 60 | 100 | JPEG `quality=85` |
| `web/src/lib/components/NowPlayingOverlay.svelte:221` | Full-screen overlay blurred background | 100 | 100 | JPEG `quality=85` |
| `web/src/lib/components/QueueDrawer.svelte:199` | Drag preview artwork | 120 | 200 | JPEG `quality=85` |
| `web/src/routes/history/+page.svelte:1098` | History artist rows | 50 | 100 | JPEG `quality=85` |
| `web/src/routes/history/+page.svelte:1133` | History album rows | 50 | 100 | JPEG `quality=85` |
| `web/src/routes/history/+page.svelte:1178` | History track rows | 50 | 100 | JPEG `quality=85` |
| `web/src/routes/history/+page.svelte:1225` | History entry track art | 60 | 100 | JPEG `quality=85` |

### Medium artwork

| Location | Usage | Requested size | Effective served size | Quality used |
| --- | --- | ---: | ---: | --- |
| `web/src/routes/+page.svelte:86` | Home page album art block 1 | 300 | 300 | JPEG `quality=85` |
| `web/src/routes/+page.svelte:191` | Home page album art block 2 | 300 | 300 | JPEG `quality=85` |
| `web/src/routes/+page.svelte:292` | Home page album art block 3 | 300 | 300 | JPEG `quality=85` |
| `web/src/routes/+page.svelte:396` | Home page artist art block 1 | 300 | 300 | JPEG `quality=85` |
| `web/src/routes/+page.svelte:441` | Home page artist art block 2 | 300 | 300 | JPEG `quality=85` |
| `web/src/routes/discovery/+page.svelte:196` | Discovery seed artist art | 300 | 300 | JPEG `quality=85` |
| `web/src/routes/discovery/+page.svelte:238` | Discovery recommended artist art | 300 | 300 | JPEG `quality=85` |
| `web/src/routes/discovery/+page.svelte:288` | Discovery recommended album art | 300 | 300 | JPEG `quality=85` |
| `web/src/routes/artists/+page.svelte:124` | Artists index grid art | 300 | 300 | JPEG `quality=85` |
| `web/src/routes/charts/+page.svelte:200` | Charts entry art | 300 | 300 | JPEG `quality=85` |
| `web/src/routes/artist/[id]/+page.svelte:162` | Artist page fallback portrait used for accent extraction | 300 | 300 | JPEG `quality=85` |
| `web/src/routes/artist/[id]/+page.svelte:209` | Artist playlist thumbnail helper `getArtistArtUrl` | 300 | 300 | JPEG `quality=85` |
| `web/src/routes/artist/[id]/+page.svelte:755` | Artist hero fallback art | 300 | 300 | JPEG `quality=85` |
| `web/src/routes/artist/[id]/+page.svelte:780` | Artist secondary fallback art | 300 | 300 | JPEG `quality=85` |
| `web/src/routes/artist/[id]/+page.svelte:866` | Similar artist artwork | 300 | 300 | JPEG `quality=85` |
| `web/src/routes/artist/[id]/+page.svelte:970` | Artist album cards | 600 | 600 | JPEG `quality=85` |
| `web/src/routes/artist/[id]/+page.svelte:1055` | Artist page playlist grid thumbnails (4-up) | 300 | 300 | JPEG `quality=85` |
| `web/src/routes/artist/[id]/+page.svelte:1064` | Artist page single playlist cover | 600 | 600 | JPEG `quality=85` |
| `web/src/routes/playlists/+page.svelte:327` | Playlists index 4-up thumbnails | 300 | 300 | JPEG `quality=85` |
| `web/src/routes/playlists/+page.svelte:337` | Playlists index single cover | 600 | 600 | JPEG `quality=85` |
| `web/src/routes/playlists/[id]/+page.svelte:331` | Playlist detail 4-up header thumbnails | 300 | 300 | JPEG `quality=85` |
| `web/src/routes/playlists/[id]/+page.svelte:339` | Playlist detail single header cover | 600 | 600 | JPEG `quality=85` |

### Large artwork

| Location | Usage | Requested size | Effective served size | Quality used |
| --- | --- | ---: | ---: | --- |
| `web/src/lib/components/NowPlayingOverlay.svelte:311` | Full-screen now playing main art | none | original file | Original mime/quality |
| `web/src/routes/album/[id]/+page.svelte:29` | Album page hero art from album metadata | none | original file | Original mime/quality |
| `web/src/routes/album/[id]/+page.svelte:31` | Album page hero fallback from first track art | none | original file | Original mime/quality |
| `web/src/routes/artist/[id]/+page.svelte:160` | Artist background used for accent extraction | 600 | 600 | JPEG `quality=85` |
| `web/src/routes/artist/[id]/+page.svelte:753` | Artist hero background | none | original file | Original mime/quality |
| `web/src/routes/artist/[id]/+page.svelte:778` | Artist secondary background | none | original file | Original mime/quality |

### TrackCard-based usages

These call sites render artwork through `TrackCard`, which always requests `100`, so they all use the 100px resized derivative at JPEG `quality=85`.

| Location | Usage | Effective served size | Quality used |
| --- | --- | ---: | --- |
| `web/src/lib/components/QueueDrawer.svelte:328` | Queue list track rows | 100 | JPEG `quality=85` |
| `web/src/lib/components/NowPlayingOverlay.svelte:512` | Now playing queue list track rows | 100 | JPEG `quality=85` |
| `web/src/routes/discovery/+page.svelte:402` | Discovery recommended tracks | 100 | JPEG `quality=85` |
| `web/src/routes/playlists/[id]/+page.svelte:568` | Playlist detail track rows | 100 | JPEG `quality=85` |
| `web/src/routes/artist/[id]/+page.svelte:1173` | Artist top tracks | 100 | JPEG `quality=85` |
| `web/src/routes/artist/[id]/+page.svelte:1203` | Artist album tracks | 100 | JPEG `quality=85` |
| `web/src/routes/artist/[id]/+page.svelte:1233` | Artist singles/other track rows | 100 | JPEG `quality=85` |

## Summary

- I found one server-side quality setting for all resized artwork: JPEG `quality=85`.
- The frontend now uses a mix of resized `100`/`300`/`600` artwork and original full-quality artwork for some large hero/background images.
- Requests for `50` and `60` are both snapped up to `100`.
- The only request for `120` is snapped up to `200`.
