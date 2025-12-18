
# Web-Based UPnP Music Controller – v1 Outline

## Goal
Build an **open-source, web-based music controller** that:
- Scans a local music library
- Caches rich metadata (including hi‑res info)
- Presents a fast, Qobuz-style web UI
- Plays music to a **Naim Uniti Atom** via UPnP with artwork & metadata visible on the device

This document describes a **minimal but correct v1** implementation.

---

## 1. Backend Architecture (Python)

### Tech Choices
- **FastAPI** – HTTP API + frontend hosting
- **SQLite** – local metadata cache
- **mutagen** – tags & embedded artwork
- **ffprobe (ffmpeg)** – codec, sample rate, bit depth, duration
- **async-upnp-client** – UPnP discovery & AVTransport control
- **uvicorn** – ASGI server

### Core Responsibilities
1. Scan filesystem and extract metadata
2. Cache metadata/artwork in SQLite
3. Serve audio & artwork over HTTP
4. Act as a UPnP Control Point for the Naim Atom
5. Provide a simple web UI

---

## 2. SQLite Data Model

### tracks
- id (PK)
- path (unique)
- mtime
- title
- artist
- album
- album_artist
- track_no
- disc_no
- date
- genre
- duration_seconds
- codec
- sample_rate_hz
- bit_depth
- channels
- art_id (FK)

### artwork
- id (PK)
- sha1 (unique, dedupe)
- mime
- width
- height
- path_on_disk

### renderers
- id (PK)
- friendly_name
- udn (unique)
- location_url
- last_seen

---

## 3. Library Scanning

### Supported Formats (initial)
- FLAC, WAV, AIFF, ALAC, MP3, OGG, DSF/DFF (optional)

### Scan Flow
1. Walk configured music roots
2. Detect new/changed files via mtime
3. Extract:
   - Tags (mutagen)
   - Embedded artwork or folder.jpg / cover.jpg
   - Technical info (ffprobe)
4. Cache artwork files
5. Update SQLite

### Notes
- Bit depth is best-effort (format-dependent)
- Artwork deduplicated by hash
- Thumbnail generation can be deferred

---

## 4. Media Hosting

### HTTP Endpoints
- `/stream/{track_id}`
  - Must support **HTTP Range requests**
  - Correct MIME types
- `/art/{art_id}`
  - Serves original or cached artwork

Renderers (including the Atom) **pull** audio over HTTP.

---

## 5. UPnP Playback (Naim Atom)

### Control Point Actions
- Discover Atom via SSDP
- Use:
  - AVTransport.SetAVTransportURI
  - AVTransport.Play / Pause / Stop
  - (Optional) RenderingControl.SetVolume

### Playback Flow
1. Build stream URL:
   - http://SERVER_IP:PORT/stream/{track_id}
2. Build artwork URL:
   - http://SERVER_IP:PORT/art/{art_id}
3. Generate DIDL-Lite metadata:
   - dc:title
   - upnp:artist
   - upnp:album
   - upnp:albumArtURI
   - res (with protocolInfo)
4. Call SetAVTransportURI with metadata
5. Call Play

### Important
- Well-formed DIDL-Lite is critical for artwork display
- Range support is mandatory for reliable playback

---

## 6. Backend API (v1)

### Library
- `POST /api/scan`
- `GET /api/tracks?query=&limit=&offset=`
- `GET /api/tracks/{id}`

### Media
- `GET /stream/{track_id}`
- `GET /art/{art_id}`

### Renderers
- `GET /api/renderers`
- `POST /api/renderers/{id}/play`
- Optional:
  - `/pause`
  - `/stop`
  - `/seek`

---

## 7. Frontend Web UI (v1)

### Features
- Renderer selector (Naim Atom)
- Search-first track browser
- Artwork thumbnails
- Display:
  - Title / Artist / Album
  - Sample rate / Bit depth
- Play button per track

### Tech
- Simple HTML + JS (no build tooling)
- Or React/Vite later

---

## 8. Project Structure

```
app/
  main.py
  db.py
  models.py
  scanner/
    scan.py
    tags.py
    probe.py
    artwork.py
  upnp/
    discover.py
    control.py
    didl.py
  media/
    stream.py
    art.py
web/
  index.html
  app.js
  styles.css
cache/
  art/
library.sqlite
```

---

## 9. v1 Milestones

1. Scan small library into SQLite
2. Serve artwork & audio over HTTP
3. Discover Atom via UPnP
4. Play a track from web UI
5. Verify artwork & metadata on Atom screen
6. Optimise for large libraries later

---

## Philosophy
- **Your app owns the library**
- UPnP is used only for transport/control
- UI speed comes from your DB, not ContentDirectory
- Open, debuggable, vendor-neutral
