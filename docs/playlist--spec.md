# Playlist Feature Specification

## Scope
User-scoped playlists for organising and replaying tracks, integrated with the existing playback queue.

---

## Core Features
- Create / rename / delete playlists
- Create playlist from current playback queue
- Add & remove tracks (duplicates allowed)
- Manual track ordering (explicit positions)
- Play playlist (sequential + shuffle)
- Persist playlists in the database (per user)
- **Visibility**: Option for Public (visible to all) or Private (visible only to creator)

---

## Playback Behaviour
- Queue entire playlist
- **Player Controls**: Add Shuffle, Repeat One, and Repeat All toggle buttons to the main playback bar.
- Logic:
    - **Shuffle**: Frontend-side randomization of the queue order.
    - **Repeat**: Logic to handle wrapping queue or repeating current track.
- When playlist is loaded into the queue all existing queue capability should remain.

---

## UI
- Playlist list view
    - **Artwork**: Dynamic 2x2 grid of 4 random distinct artworks from tracks in the playlist.
- Playlist detail view (tracks, total duration)
- “Add to playlist” from track, album, top tracks, singles and playback queue
- “Save queue as playlist” action in player UI

---

## Metadata
- Playlist name
- Description (optional)
- **Public/Private Status**
- Track count
- Total duration
- Last updated timestamp (used for creation time initially)

---

## Backend / Data Model
- Playlist CRUD API
- Join table: `playlist_tracks`
    - `playlist_id`
    - `track_id`
    - `id` (primary key to allow duplicates)
    - `position` (explicit ordering)
- Reorder performed via a single atomic API call (transaction).

---

## Tables
### playlists
Stores playlist-level metadata.

``` sql
CREATE TABLE playlists (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    name          TEXT NOT NULL,
    description   TEXT,
    is_public     BOOLEAN NOT NULL DEFAULT FALSE,
    last_updated  REAL NOT NULL,

    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

### playlist_tracks
Joins playlists to tracks and preserves order.
**Note**: `track_id` is NOT unique per playlist to allow duplicates.

``` sql
CREATE TABLE playlist_tracks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id  INTEGER NOT NULL,
    track_id     INTEGER NOT NULL,
    position     INTEGER NOT NULL,

    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
    FOREIGN KEY (track_id) REFERENCES tracks(id)
);

CREATE INDEX idx_playlist_tracks_pos ON playlist_tracks(playlist_id, position);
```

### Design Notes (Important)
* Explicit position avoids implicit ordering bugs.
* `position` management must handle insertions/deletions (shifting).
* Backend endpoint for reorder should accept a list of IDs or a move operation (e.g., "move item ID X to pos Y") and handle the shifting transactionally.

## Tests

### API
- Create / rename / delete playlist
- Toggle public/private visibility
- List playlists (respecting visibility rules)
- Fetch playlist with ordered tracks and totals
- Generate 2x2 artwork grid (on-demand or cached)

### Track Membership
- Add / remove tracks
- Bulk add tracks
- **Verify duplicates are allowed**

### Ordering
- Reorder tracks persists
- Invalid reorder rejected
- Reorder is atomic

### Playback Integration
- Queue playlist in order
- Shuffle preserves track set (frontend)
- Repeat all wraps correctly
- When playlist added to queue keep all existing queue capability

### Auth
- Access/mutate another user’s *private* playlist is denied.
- Read another user's *public* playlist is allowed.
- Mutate another user's *public* playlist is denied.

### Data Integrity
- Playlist–track ordering invariants enforced
- Cascades / foreign keys behave correctly
- `last_updated` updates on mutation

### Frontend (Smoke)
- Playlist list and detail render
- Drag/drop reorder persists after refresh
- Add-to-playlist works from track/album
- Save queue as playlist creates and opens playlist
- Player controls (Shuffle/Repeat) function correctly
