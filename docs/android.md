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

## Stage 3 Plan: Android Auto v1 - 2026-04-25

Stages 0-2 are complete. Stage 5 (Phone UI) is well past its original scope:
home, search, artist detail, album detail, playlists, charts, history,
favourites, queue/now playing, and history+scrobble reporting all ship in the
phone app. The next milestone is in-car playback through Android Auto.

This section captures the concrete decisions made before any car-related code.
Stage 4's `/api/android` adapter is **not** part of v1 - existing endpoints map
to the planned browse tree without change.

### Auth in the car

The car has no UI for typing a password. The `MediaLibraryService` runs on the
phone and reuses the access token already in DataStore.

- If the token is missing or expired beyond refresh, the root browse tree
  returns a single non-playable item titled "Sign in on phone to use Jamarr".
- The existing `JamarrApiClient` auth interceptor handles refresh transparently
  while the car session is live.
- No in-car login flow.

### Service architecture

Upgrade the existing `JamarrPlaybackService extends MediaSessionService` to
extend `MediaLibraryService` instead. `MediaLibraryService` is a subclass of
`MediaSessionService`, so the phone behaviour is preserved and the same service
serves both phone and car. No second service.

### Browse tree

Drive-safe and shallow. The artist and album catalogues are too large to be
useful as flat lists in the car, so they are intentionally **not** root nodes -
voice/text search is the entry point for "play <something specific>".

```
Root
├── Favourites
│   ├── Artists  → artist   → albums   → tracks
│   └── Releases → album    → tracks
└── Playlists    → playlist → tracks
├── Recently PLayed
│   ├── Albums   → album    → tracks
├── Charts
│   ├── Albums   → album    → tracks
├── History
│   ├── Albums   → album    → tracks
│   └── Artists  → artist   → albums   → tracks
├── Recently Added
│   ├── Albums   → album    → tracks

```

Tap behaviour:

- Track: play it; queue siblings (album/playlist) for prev/next.
- Album / playlist: play from track 1.
- Artist: show albums (no auto-play; "Shuffle artist" deferred).

Search is wired through `MediaLibrarySession.Callback.onSearch` later (see
deferred section). For v1, AA's text search field will be empty.

### Stream URL lifecycle

Stream URLs are short-lived, signed tokens. The current phone code resolves the
whole queue's URLs up front, which would fail mid-drive on long playlists.

For Android Auto - and the phone, since they share the service - switch to lazy
resolution: implement a Media3 `ResolvingDataSource.Factory` that calls
`GET /api/stream-url/{id}` immediately before each track plays. The `MediaItem`
holds the track id; the data source resolves it to a fresh URL on demand.

No backend change. This also fixes any "queue dies after N tracks" issue from
expired tokens.

### Artwork

`MediaMetadata.artworkUri` is fetched by the AA system process, not by our app,
so it can't carry our bearer token. v1 embeds bytes:

- Fetch artwork via OkHttp/Coil using the existing
  `/api/art/file/{sha1}?max_size=400` endpoint (auth header attached as normal).
- Set the bytes on `MediaMetadata.artworkData`.
- ~30-100 KB per track in the session bundle - acceptable for now.

If memory/IPC cost becomes a problem, revisit with a signed art URL endpoint.

### History reporting and Last.fm scrobbling

These ship in v1 (not deferred). The phone already calls
`POST /api/player/queue`, `POST /api/player/index`, and
`POST /api/player/progress` from the polling loop in `JamarrApp.kt`. The same
loop must keep running while AA is connected; nothing about car playback should
disable it.

The polling loop is driven by `MediaController` state, not by the foreground
UI, so it should continue working when the phone screen is off and AA is in
control. Verify this explicitly during DHU testing - history rows for
in-car playback must appear at the same 30s/20% threshold the web UI uses.

### Manifest and discovery

- Add `res/xml/automotive_app_desc.xml`:

  ```xml
  <automotiveApp>
      <uses name="media"/>
  </automotiveApp>
  ```

- Application-level meta-data:

  ```xml
  <meta-data
      android:name="com.google.android.gms.car.application"
      android:resource="@xml/automotive_app_desc"/>
  ```

- The service intent filter keeps `MediaSessionService` and adds
  `MediaLibraryService` (Media3 dispatches to both).

### Testing

Use Android Studio's Desktop Head Unit (DHU) to iterate without driving:

- Install DHU via the SDK Manager (Extras > Android Auto Desktop Head Unit).
- Phone needs USB debugging + AA developer mode enabled.
- A small helper script under `android/scripts/dhu.sh` should:
  - check `adb` is available,
  - start the phone-side AA in head-unit-server mode,
  - launch the DHU binary,
  - tear everything down on Ctrl-C.

The `android/README.md` (or root README) needs a "Testing in the car" section
linking to the script and noting prerequisites. Real-car validation is the
final step.

### Deferred to v2

- Voice/text search (`onSearch`) - intentional v1 omission.
- Custom session commands (favourite from car, etc.).
- Offline downloads.
- Pagination/alphabet scaffolding for full Artists/Albums browse - rejected
  for v1; search covers the use case.
- The `/api/android` adapter - revisit only if a v1 awkwardness justifies it.

### Implementation order

1. Lazy stream resolution via `ResolvingDataSource.Factory` (fixes phone bug
   too).
2. Service upgrade to `MediaLibraryService` + manifest changes.
3. Root browse tree + Recently Played + Favourites + Playlists nodes.
4. Drilldown nodes (album→tracks, artist→albums, playlist→tracks).
5. Embedded artwork on `MediaMetadata`.
6. DHU helper script + README.
7. Verify history/scrobble reporting still works under AA.

## Current Implementation Status - 2026-04-21

The native Android proof of concept now exists under `android/`.

Backend and web were intentionally left unchanged. The app uses existing Jamarr
API routes only.

### Verified On Device

Test device:

- Pixel XL
- Android 10
- ADB serial seen locally as `HT69K0206009`

Verified behavior:

- Login works against a LAN Jamarr server URL.
- Track search works.
- The app calls `GET /api/stream-url/{track_id}` and plays the returned stream
  URL with Media3 ExoPlayer.
- Playback works on device.
- Media notification shade controls work.
- In-app controls work:
  - play
  - pause
  - previous
  - next
  - seek back 10 seconds
  - seek forward 30 seconds
- Notification shade controls also work.
- Artwork appears in the Android media notification.
- Scrolling works on the phone UI.

### Implemented App Shape

The current app is a native Kotlin Android project:

```text
android/
  settings.gradle.kts
  build.gradle.kts
  gradle/wrapper/
  app/
    build.gradle.kts
    src/main/AndroidManifest.xml
    src/main/java/com/jamarr/android/
      MainActivity.kt
      auth/SettingsStore.kt
      data/JamarrApiClient.kt
      data/JamarrDtos.kt
      playback/JamarrPlaybackController.kt
      playback/JamarrPlaybackService.kt
      ui/JamarrApp.kt
      ui/Theme.kt
    src/main/res/drawable/jamarr_logo.png
```

Main dependencies:

- Kotlin
- Jetpack Compose
- AndroidX DataStore preferences
- Media3 ExoPlayer
- Media3 Session
- OkHttp
- kotlinx.serialization
- Coil 3 for artwork loading

Build stack:

- Android Gradle Plugin 9.0.1
- Gradle wrapper 9.1.0
- AGP 9 built-in Kotlin support
- Compose compiler plugin 2.3.10
- kotlinx.serialization compiler plugin 2.3.10
- JDK 17

### API Routes Used

Authentication:

```text
POST /api/auth/login
```

Search and playback:

```text
GET /api/search?q=<query>
GET /api/stream-url/{track_id}
GET /api/stream/{track_id}?token=<stream_jwt>
```

Home page sections:

```text
GET /api/home/new-releases
GET /api/home/recently-added-albums
GET /api/history/albums
GET /api/home/discover-artists
GET /api/history/artists
```

Album playback:

```text
GET /api/tracks?album=<album>&artist=<artist>
```

Artwork:

```text
GET /api/art/file/{sha1}?max_size=400
```

### Stage 1 Result

Stage 1 is complete for the POC.

Implementation details:

- Server URL and access token are saved with DataStore.
- Login sends the existing JSON body:

  ```json
  {
    "username": "REDACTED",
    "password": "..."
  }
  ```

- The password field had to be changed to `KeyboardType.Password`. Before this,
  Android treated it as normal autocorrect text, which could leave unexpected
  whitespace in the field and cause `Invalid credentials`.
- Cleartext HTTP is currently enabled in the manifest for LAN development URLs
  such as `http://REDACTED_IP:8111`.
- Do not use `localhost` from a physical phone unless Jamarr is running on the
  phone itself. Use the machine's LAN IP.

### Stage 2 Result

Stage 2 is complete for the POC.

Implementation details:

- `JamarrPlaybackService` extends Media3 `MediaSessionService`.
- The service owns the ExoPlayer instance.
- `JamarrPlaybackController` uses a Media3 `MediaController`.
- The phone UI no longer owns ExoPlayer directly.
- The manifest declares the media playback foreground service:

  ```xml
  <service
      android:name=".playback.JamarrPlaybackService"
      android:exported="true"
      android:foregroundServiceType="mediaPlayback">
      <intent-filter>
          <action android:name="androidx.media3.session.MediaSessionService" />
      </intent-filter>
  </service>
  ```

- The app requests notification permission on Android 13+.
- Search results are turned into a Media3 playlist, so previous/next works from
  both the app and notification shade.

### UI Work Completed

The UI is no longer just the original bare POC.

Completed UI changes:

- Dark grey and pink theme.
- Site logo copied from `web/static/assets/logo.png` into Android resources.
- Home screen with horizontal artwork rows matching the web home page:
  - New Releases
  - Recently Added
  - Recently Played Albums
  - Newly Added Artists
  - Recently Played Artists
- Album cards load artwork and can start playback.
- Artist cards currently search for the artist name.
- Search still works and track cards can start playback.
- Now-playing controls remain visible in the screen.

### Development Environment Notes

Host environment used:

- CachyOS / Arch
- Android Studio installed
- Android SDK under `/home/darious/Android/Sdk`
- Android SDK platform `android-36` present
- ADB available at `/usr/bin/adb`
- System Java default was Java 26:

  ```text
  java-26-openjdk (default)
  ```

- Java 17 was already installed:

  ```text
  java-17-openjdk
  ```

Important build detail:

- Use Java 17 for Android Gradle Plugin builds.
- The project has a Gradle wrapper pinned to Gradle 9.1.0.
- The system `gradle` package was 9.4.1 and used Java 26 by default, so the
  wrapper is preferred.
- AGP 9 built-in Kotlin is enabled. Do not re-add the
  `org.jetbrains.kotlin.android` plugin; AGP 9 provides Kotlin support for the
  Android app module.

Recommended build command:

```bash
cd android
JAVA_HOME=/usr/lib/jvm/java-17-openjdk ./gradlew :app:assembleDebug
```

Recommended install command:

```bash
cd android
JAVA_HOME=/usr/lib/jvm/java-17-openjdk ./gradlew :app:installDebug
```

The Codex sandbox could not use `/home/darious/.gradle` because it was outside
the writable workspace. During this session, builds used a workspace-local
Gradle user home:

```bash
GRADLE_USER_HOME=/home/darious/code/jamarr/android/.gradle-user
```

That directory is ignored by `android/.gitignore` and should not be committed.

ADB needed to run outside the sandbox to access USB and the local ADB daemon.

Useful device checks:

```bash
adb devices
adb shell pm list packages com.jamarr.android
adb shell monkey -p com.jamarr.android 1
```

### Build Status

The final checked app state built and installed successfully on 2026-04-21:

```text
BUILD SUCCESSFUL
Installed on 1 device.
```

### Known Limitations

These are acceptable for the current POC but should be addressed later:

- Access tokens are stored in DataStore. Refresh-cookie/session handling is not
  fully implemented yet.
- Refresh/session material is not stored in encrypted storage yet.
- Stream URLs are resolved eagerly for a whole queue. Later, resolve URLs lazily
  when a track is about to play so short-lived stream tokens do not expire in a
  long queue.
- Album playback currently fetches album tracks from the existing web-shaped
  `/api/tracks` route.
- Artist cards do not open artist detail screens yet; they trigger a search.
- No playlist, album detail, artist detail, or full library screens yet.
- No playback history reporting from Android yet.
- No Android Auto `MediaLibraryService` browse tree yet. That remains Stage 3.
- No `/api/android` adapter exists. Stage 4 should only be added if Android Auto
  browsing proves the current API is too awkward.
