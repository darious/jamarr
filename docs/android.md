# Native Android and Android Auto Approach

## Goal

Add a native Android client for Jamarr without turning the backend into a new
platform project.

The Android app should be another Jamarr client. It should reuse the existing
FastAPI API, auth model, stream URL flow, artwork endpoints, and library data as
much as possible. Android Auto support should play through Android's
`MediaSession` in the car; it should not use Jamarr's UPnP renderer support.

This document intentionally separates the first safe milestone from optional
later improvements. The first milestone should be small enough to validate the
approach before committing to larger API work.

## Non-Goals

- No rewrite of the current web API.
- No changes to the Svelte UI contract unless independently needed.
- No Android Auto support for UPnP renderers.
- No new backend queue system for Android in the first milestone.
- No new auth model in the first milestone.
- No database schema changes in the first milestone.
- No broad `/api/mobile` platform redesign before a working Android prototype
  proves what is actually needed.

## Sequence Plan

The work should be staged so each step proves one thing and keeps backend risk
low. Stages 0-2 are the real initial scope. Later stages are optional and should
only happen after the earlier stages expose a concrete need.

### Stage 0: API Survey

Goal: confirm which existing Jamarr endpoints the Android app can already use.

Work:

1. List the current auth, search, library, artwork, and stream URL endpoints.
2. Identify the smallest path from "logged in" to "play one track".
3. Note missing fields only if they block Android playback.

Backend changes allowed: none.

Exit criteria:

- A short endpoint map exists for the Android prototype.
- There is a known existing endpoint path to find or select a track.
- There is a known existing endpoint path to generate a playable stream URL.

Stage 0 output: [api.md](api.md).

### Stage 1: Phone Playback Prototype

Goal: prove native Android can play Jamarr audio without backend redesign.

Work:

1. Create the native Android project.
2. Store a Jamarr server URL.
3. Log in using the existing auth endpoints.
4. Fetch enough library or search data to select one track.
5. Request an existing Jamarr stream URL for that track.
6. Play the stream with Android Media3/ExoPlayer.

Backend changes allowed: none unless a tiny compatibility fix is required to
play one track.

Exit criteria:

- The app can log in.
- The app can select one Jamarr track.
- The app can play that track through ExoPlayer.
- The web UI still works without changes.

### Stage 2: MediaSession Foundation

Goal: make Android own playback in the standard Android way.

Work:

1. Add a Media3 `MediaSession`.
2. Connect ExoPlayer to the session.
3. Show Android media notification controls.
4. Support play, pause, seek, previous, and next inside the phone app.

Backend changes allowed: none.

Exit criteria:

- Lock screen and notification controls work.
- Headset/media button controls work.
- Playback state is reported by Android's `MediaSession`, not Jamarr's UPnP
  renderer state.

### Stage 3: Android Auto Browse Prototype

Goal: prove Android Auto can browse and play Jamarr tracks through the phone's
media session.

Work:

1. Add a Media3 `MediaLibraryService`.
2. Expose a small Android Auto browse tree.
3. Map browse selections to Jamarr track IDs.
4. Resolve selected tracks to existing Jamarr stream URLs.
5. Test with Android Auto Desktop Head Unit or a real car.

Backend changes allowed: none at first. If current web-shaped endpoints make
the media tree awkward, stop and add the small adapter described in the next
stage.

Exit criteria:

- Android Auto can display at least one browse path.
- Android Auto can start playback.
- Playback happens through ExoPlayer and `MediaSession`.
- No UPnP or Jamarr renderer state is involved.

### Stage 4: Minimal Android Adapter, Only If Needed

Goal: reduce Android Auto client complexity if the existing API is awkward for
tree-shaped browsing.

Work:

1. Add one narrow FastAPI router at `app/api/android.py`.
2. Add only these routes:
   - `GET /api/android/browse/root`
   - `GET /api/android/browse/{node_id}/children`
   - `POST /api/android/resolve`
3. Reuse existing auth and existing database/library/stream logic.
4. Add focused tests for the new routes.

Backend changes allowed: one additive router only. No migrations, no web route
changes, no auth rewrite, no player rewrite.

Exit criteria:

- Android Auto browse code is simpler than it was against the web API.
- Existing web UI behavior is unchanged.
- New tests cover the adapter routes.

### Stage 5: Phone UI Expansion

Goal: turn the prototype into a useful phone app.

Work:

1. Add basic library screens.
2. Add search.
3. Add artist, album, and playlist detail screens.
4. Add now-playing and queue UI managed locally by Android Media3.

Backend changes allowed: small additive fields or endpoint fixes only when the
Android UI proves a specific gap.

Exit criteria:

- The phone app can browse enough of the library to be useful.
- Local Android playback remains independent of Jamarr UPnP playback.

### Stage 6: Optional Hardening

Goal: improve reliability and polish after the core app works.

Possible work:

- Android playback history reporting.
- Better artwork sizing or caching.
- Batch stream URL resolution.
- Offline downloads.
- Android device/session management.
- Mobile-specific queue persistence.

Backend changes allowed: only individually justified additions. Avoid grouping
these into one large platform rewrite.

Exit criteria:

- Each hardening item has a concrete problem it solves.
- Each item can be tested independently.

## First Milestone Summary

The first real milestone is the end of Stage 2: Android can log in, play one
Jamarr track with ExoPlayer, and expose that playback through Media3
`MediaSession`.

Android Auto begins in Stage 3. The optional `/api/android` backend adapter is
Stage 4, not a prerequisite.

## Android App Shape

Use a normal native Android app:

- Kotlin
- Jetpack Compose for phone UI
- Media3 ExoPlayer for playback
- Media3 Session for `MediaSession` / Android Auto integration
- Retrofit or Ktor for HTTP
- DataStore for server URL and local app preferences
- Secure local storage for refresh/session material

Suggested package layout:

```text
android/
  app/
    ui/          # Compose screens
    data/        # Jamarr API client and DTOs
    auth/        # Login, refresh, token storage
    playback/    # ExoPlayer and MediaSession
    car/         # MediaLibraryService for Android Auto
```

The first app does not need a full Jamarr UI. A small login screen, search or
library picker, and now-playing screen are enough to validate the playback path.

## Android Auto Model

Android Auto media apps are not custom projected phone screens. The car host
connects to the app's media service, asks for a browsable media tree, and sends
playback commands through the app's media session.

For Jamarr, Android Auto should be:

```text
Jamarr FastAPI -> Android app -> ExoPlayer -> MediaSession -> Android Auto
```

It should not be:

```text
Android Auto -> Jamarr backend player state -> UPnP renderer
```

The app owns playback in the car. Jamarr provides metadata, artwork, and stream
URLs.

## Backend Strategy

Start with no backend changes. If Android Auto needs a cleaner browse tree than
the current web API naturally provides, add one narrow adapter router.

The adapter should:

- live under new Android-specific paths;
- reuse existing auth dependencies;
- use existing database/library query logic where practical;
- avoid schema changes;
- avoid changing existing web endpoints;
- return a small Android-friendly media item shape.

Suggested file if needed:

```text
app/api/android.py
```

Suggested route prefix if needed:

```text
/api/android
```

## Minimal Optional Android Adapter

Only add this after the first Android playback prototype works and the Android
Auto `MediaLibraryService` proves that current endpoints are awkward.

### `GET /api/android/browse/root`

Returns a small fixed set of top-level folders for Android Auto.

Example:

```json
{
  "items": [
    {
      "id": "recent",
      "title": "Recently Played",
      "browsable": true,
      "playable": false
    },
    {
      "id": "playlists",
      "title": "Playlists",
      "browsable": true,
      "playable": false
    },
    {
      "id": "artists",
      "title": "Artists",
      "browsable": true,
      "playable": false
    },
    {
      "id": "albums",
      "title": "Albums",
      "browsable": true,
      "playable": false
    }
  ]
}
```

### `GET /api/android/browse/{node_id}/children`

Maps simple node IDs to existing Jamarr data.

Possible mappings:

```text
recent           -> recent tracks or playback history
playlists        -> playlist list
playlist:{id}    -> playlist tracks
artists          -> artist list
artist:{mbid}    -> artist albums or tracks
albums           -> album list
album:{id}       -> album tracks
```

Response shape:

```json
{
  "items": [
    {
      "id": "track:123",
      "title": "Dreams",
      "subtitle": "Fleetwood Mac",
      "image_url": "/api/art/...",
      "browsable": false,
      "playable": true
    }
  ]
}
```

The Android app should treat `id` as opaque. The backend can parse IDs however
it wants internally.

### `POST /api/android/resolve`

Converts an Android media item ID into a playable stream.

Request:

```json
{
  "id": "track:123"
}
```

Response:

```json
{
  "id": "track:123",
  "track_id": 123,
  "stream_url": "/api/stream/123?token=...",
  "title": "Dreams",
  "artist": "Fleetwood Mac",
  "album": "Rumours",
  "duration_ms": 257000,
  "image_url": "/api/art/..."
}
```

This should wrap the existing Jamarr stream URL behavior. It should not create a
new streaming system.

## Why This Adapter Is Small

The adapter is not a new API platform. It is a translation layer between:

- Android Auto's tree-shaped media browsing model; and
- Jamarr's existing library, playlist, history, artwork, and stream data.

It should be read-only except for stream URL generation, which Jamarr already
does. It should not own playback state.

## What To Defer

These may be useful later, but they should not block the first app:

- Android-specific playback history reporting.
- Offline downloads.
- Batch stream URL resolution.
- Artwork resizing/caching endpoints.
- Android session/device management.
- Mobile-specific queue persistence.
- A generalized `/api/mobile/v1` API.
- Car App Library templated media screens.

Add these only after the first Android app shows a concrete need.

## Risk Controls

- Keep all new backend routes under `/api/android`.
- Do not modify existing web routes for Android.
- Add focused tests only for any new Android adapter endpoints.
- Avoid migrations for the first Android work.
- Keep Android Auto playback local to Android Media3.
- Use the existing Jamarr stream URL endpoint for actual file access.

## Main Decision

The important decision is to prove playback before designing a larger API. If
the proof of concept can play Jamarr tracks through Media3, Android Auto support
becomes a focused media-service task rather than a backend rewrite.

The order is:

1. API survey.
2. Phone playback prototype.
3. MediaSession foundation.
4. Android Auto browse prototype.
5. Minimal Android adapter only if needed.
6. Phone UI expansion.
7. Optional hardening.
