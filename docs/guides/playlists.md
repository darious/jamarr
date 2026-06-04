# Playlists

User-scoped playlists for organising and replaying tracks, integrated with the
playback queue.

!!! info "Code"
    `app/playlist.py` (API). Tables `playlist` and `playlist_track` — see the
    generated [Database Schema](../reference/schema/README.md).

## What you can do

- Create, rename, and delete playlists
- Save the current queue as a playlist
- Add and remove tracks — **duplicates are allowed**
- Reorder tracks (explicit positions, drag-and-drop in the web UI)
- Queue a playlist (sequential or shuffle); repeat-one / repeat-all
- Add to a playlist from a track, album, top tracks, singles, or the queue

## Ordering model

Each `playlist_track` row has an explicit integer `position` and its own primary
key (so the same `track_id` can appear multiple times). Reordering is a single
atomic API call (`POST /api/playlists/{id}/reorder`) that rewrites positions in
one transaction — no implicit ordering, no drift.

## Metadata

A playlist carries a name, optional description, track count, total duration, and
a last-updated timestamp. The list view renders a 2×2 grid of distinct artworks
from the playlist's tracks.

## API

See the [API Reference](../reference/api.md) for the full playlist endpoint set
(`/api/playlists*`), including adding/removing tracks, reordering, and listing
playlists that contain a given artist.

!!! note "Visibility"
    Public/private playlist visibility was part of the original spec. Treat the
    [API Reference](../reference/api.md) as authoritative for which fields and
    endpoints actually exist today.
