# Offline Playback and Stream Buffering Plan

Status: **Phases 1-3 implemented** (written 2026-08-02, updated 2026-10-01).
Phases 4-5 not started.

Two features, one shared piece of infrastructure:

1. **Offline downloads** — download tracks/albums/artists/playlists/top tracks, browse what
   is downloaded, play with no server reachable.
2. **Online buffering** — pre-cache the current and next track so short network
   glitches do not interrupt playback and the next track starts instantly.

## Core design

Both features come from a Media3 disk cache keyed by a *stable* key, placed
**above** the existing `ResolvingDataSource`.

Current chain (`app/src/main/java/com/jamarr/android/playback/JamarrPlaybackService.kt`,
`onCreate`):

```
DefaultMediaSourceFactory
  -> ResolvingDataSource (jamarr://track/N -> /api/stream/N?token=<jwt>)
    -> DefaultHttpDataSource
```

Planned chain:

```
DefaultMediaSourceFactory
  -> CacheDataSource(downloadCache, NoOpCacheEvictor)      # read-only in playback
    -> CacheDataSource(prefetchCache, LRU evictor)         # writes
      -> ResolvingDataSource (jamarr://track/N -> signed URL)
        -> DefaultHttpDataSource
```

Ordering is the whole trick. The cache layers see the stable
`jamarr://track/{id}` URI, never the rotating signed URL, so:

- the cache never fragments across token rotations;
- a cache hit skips `resolveDataSpec` entirely, so offline playback needs no
  network by construction;
- long queues stop dying on expired stream tokens.

Set `MediaItem.customCacheKey = "track:{id}:{quality}"`. Quality belongs in the
key so a re-download at a different quality cannot serve the wrong bytes.

Two cache instances, because downloads and prefetch have opposite eviction
policies:

| Cache | Location | Evictor | Purpose |
|---|---|---|---|
| `downloadCache` | `filesDir/downloads` | `NoOpCacheEvictor` | user downloads, only `DownloadManager` removes |
| `prefetchCache` | `cacheDir/prefetch` | `LeastRecentlyUsedCacheEvictor` (default 1 GiB) | transient read-ahead |

`SimpleCache` allows one instance per directory per process — both live as
singletons on `JamarrApplication`.

## Backend impact

Phases 1-3 need **no backend change**. `GET /api/stream-url/{track_id}` and
`GET /api/stream/{track_id}?token=` already suffice. The 300 s
`STREAM_TOKEN_TTL_SECONDS` (`app/auth_tokens.py`) is not a problem for large
downloads: resolution happens per data-source open, and a resumed range request
reopens with a fresh token.

Phase 4 adds one endpoint (offline play history). That is the only backend work
in the whole plan.

---

## Phase 1 — online buffering (no UI, ships alone) — **done**

1. ✅ `playback/JamarrMediaCache.kt` — the two `SimpleCache` singletons above,
   held lazily by `JamarrApplication`. Also exposes `isFullyCached` /
   `isDownloaded`, which Phase 2 needs.
2. ✅ Data-source chain rewired in `JamarrPlaybackService.onCreate`. The
   download layer passes a null sink factory so playback can never write it.
3. ✅ Prefetch worker — `playback/StreamPrefetcher.kt`, driven from
   `onMediaItemTransition`, `onTimelineChanged` and `STATE_READY`. Skips
   read-ahead on a metered network when the wifi-only setting is on
   (`SettingsStore.observeWifiOnlyTransfers`, default off).
4. ✅ `DefaultLoadControl` at 50 s/300 s, and `targetBufferBytes` raised to
   48 MB — the audio default (~13 MB) would stop a lossless stream far short of
   `maxBufferMs`, making the duration setting a lie.

Both regressions handled, not deferred:

- ✅ Quality labels moved out of `resolveDataSpec` into a `streamLabels` map
  applied on media-item transition. On a cache hit resolve never runs, and
  resolve now also fires for prefetched tracks that are *not* current, so the
  old placement was wrong in both directions.
- ✅ `recordBufferingEvent` returns early when the current track is fully
  cached: that stall is disk or decoder, not a slow network, and must not walk
  the adaptive policy down the ladder.

Two deliberate deviations from the plan above:

- **Only the next track is prefetched, not the remainder of the current one.**
  Two writers on one cache key contend, and the loser falls back to an uncached
  upstream read — fetching the same bytes twice. The in-progress track is
  covered by the enlarged buffer instead.
- **A quality downgrade cancels read-ahead.** Cache keys carry the quality, so
  anything already fetched at the old quality is dead weight.

Tests: `StreamCacheKeysTest` (key mapping, and that a signed URL can never
become a key) and `PrefetchPolicyTest` (target normalisation, metered gate).
The Media3 plumbing in `StreamPrefetcher` itself is left to the instrumented
tests — the decisions it makes live in `PrefetchPolicy`.

Not done in this phase: there is no settings UI for wifi-only yet — the flag is
stored and honoured, but only Phase 5 surfaces it.

## Phase 2 — download engine + local metadata — **done**

5. ✅ Dependencies: `media3-exoplayer-workmanager` (now 1.11.1, in step with
   the other media3 artifacts), Room 2.8.4 with KSP 2.3.11. The flagged risk did
   not materialise — KSP 2.3.11 runs under AGP 9.4.1 / Kotlin 2.4.20, so the
   kotlinx-serialization fallback was not needed.
6. ✅ `download/JamarrDownloadService` + `download/JamarrDownloads`, the
   process-wide engine held lazily by `JamarrApplication`. `WorkManagerScheduler`
   requeues after reboot or network return; requirements follow the wifi-only
   flag (`NETWORK_UNMETERED` when set).
   - `DownloadRequest.id` and `customCacheKey` are both
     `track:{id}:{quality}`, and the downloader is built with the same
     `JamarrCacheKeyFactory` playback uses.
7. ✅ Room schema in `download/db/` as planned, plus a `position` column on the
   join table so a group's tracks come back in the order they were requested.
8. ✅ `DownloadManager.Listener` feeding
   `JamarrDownloads.states: StateFlow<Map<Long, DownloadProgress>>`, mirrored
   onto the view model. Rebuilt from Media3's download index at startup — Room
   records intent, the index is the truth about bytes.
9. ✅ Download affordance on `TrackRow`, wired into the album screen, and a
   `DownloadsScreen` reading Room.

Deviations from the plan above:

- **`StreamUrlResolver` was extracted from `JamarrPlaybackService` first.** The
  downloader has to resolve stream URLs exactly as playback does; a download
  that resolved differently would write bytes the player could never find. The
  service now delegates to it, so there is one implementation, not two.
- **Downloads are fetched at `original`, not at a chosen quality.** Cache keys
  carry the quality, so a download at some other quality would not be a cache
  hit under the key the player looks up, and would silently re-stream. A
  download-quality setting has to arrive together with a player-side lookup that
  accepts *any* downloaded quality — moved to phase 5.
- **No `TrackRow` overflow menu.** A trailing icon (arrow / percent / tick)
  costs one optional parameter and leaves every existing call site untouched.
- **Standalone tracks get their own `TRACK` group.** Removal is then uniform —
  a track dies with its last group — instead of needing a separate rule for
  tracks nothing else owns.
- **The foreground notification is hand-built.** Media3's
  `DownloadNotificationHelper` lives in `media3-ui`, whose View-based player UI
  this Compose app has no other use for.
- **Downloads are reached from an icon in the home header**, not a sixth bottom
  tab, per the open decision above.

Tests: `DownloadProgressTest` (Media3 state mapping) as a JVM test, and
`DownloadDaoInstrumentedTest` — group ownership, orphan detection, ordering and
cascade — on the emulator, since Room needs a device.

Not done in this phase: album/artist/playlist download buttons, offline artwork,
offline mode. Those are phase 3, unchanged.

## Phase 3 — offline library + offline mode — **done**

10. ✅ Group downloads: album detail header button, playlist detail header button,
    artist detail "download all releases" behind a confirm dialog showing track
    count and estimated size (a full discography can be tens of GB — never
    one-tap).
11. ✅ Top-tracks downloads, **kept in sync**: a download button on each of the
    artist's Top Tracks tabs — Most Scrobbled, Most Listened and Singles. New
    group kind `ARTIST_TOP`, `groupId` `artist_top:{artistMbid}:{scrobbled|listened|singles}`,
    tracks in server order via `position`. Unlike a release, these lists move:
    rankings shift, play counts change, new singles appear. So the group is a
    subscription, not a snapshot — on app start and on reconnect, re-fetch each
    list, enqueue tracks that joined, drop membership for tracks that left, and
    rewrite positions. A dropped track stays on disk while another group holds
    it (the existing last-group-out removal rule). Sync downloads obey the
    wifi-only flag. Most Listened is per-user, so it follows the logged-in
    account.
12. ✅ Offline artwork: for each distinct `artSha1`, fetch bytes at 400 and 600 into
    `filesDir/art/{sha1}_{size}`, and add a Coil `Fetcher`/interceptor mapping
    `/api/art/file/{sha1}?max_size=N` to the local file when present. Without
    this, downloaded albums render blank offline.
13. ✅ Offline mode: automatic (server unreachable) plus a manual toggle in
    settings. In offline mode the repository serves Room instead of
    `JamarrApiClient`.
14. ✅ Downloads UI: tabs Tracks / Albums / Artists / Playlists, mirroring the
    Favourites screen shape. Top-tracks groups list under their artist.
15. ✅ Offline fallback screens. Today an API failure on Home leaves nothing useful
    (same class of bug as the web blank-home-on-session-expiry issue). In
    offline mode, Home must route to Downloads rather than render a dead screen.

Deviations from the plan above:

- **Offline mode does not swap the API for Room behind the existing screens.**
  The album, artist and playlist screens each fetch their own data, so there
  is no single repository to swap. Offline, Home renders the Downloads screen
  instead, a downloaded group opens a Room-backed detail screen
  (`DownloadGroupScreen`), and the server-only tabs (Favourites, Playlists,
  Charts, History) show `OfflinePlaceholder` pointing back at the downloads.
- **Detection is `data/ConnectivityMonitor`**: the default-network callback plus
  an `/api/health` probe, re-run on every network change, after a failed home
  load, every 30 s while the server is down and every 5 min while it is up.
  Offline = manual switch, or no network, or no answer from the server — a
  phone on someone else's wifi is offline too. Token refresh only runs on a
  401, which needs the server to answer, so going offline never logs out
  (guarded by `JamarrApiClientTest.anUnreachableServerLeavesTheSessionAlone`).
  The limit is the refresh token: `REFRESH_TOKEN_TTL_DAYS` (21) since the last
  successful refresh, sliding on each one. Offline longer than that, the first
  request after reconnecting fails to refresh and the app returns to the login
  screen; downloads stay on disk. Downloads belong to the device, not the
  account. Log out is unreachable offline (it lives on Home, which offline
  mode replaces) — keep it that way, or disable it offline: logging out with
  no server would lock the user out of their downloads.
- **The manual switch is in the Account dialog**, there being no settings
  screen until phase 5.
- **Offline playback is local-only and downloads-only.** Every renderer
  streams from the server, and a queue with an undownloaded track would stall
  on a fetch that cannot succeed. Queue/progress reports to the server are
  skipped too, since each would sit out the connect timeout first.
- **Re-requesting a group replaces its track list** (`replaceGroupTracks`),
  rather than adding to it; tracks that left are deleted unless another group
  holds them. The top-tracks sync is the same call. Tracks already on disk keep
  their row and state (`insertTrackIfAbsent`), and groups are written with
  `@Upsert` — SQLite's `REPLACE` deletes the row first, which risks cascading
  the group's links away.
- **One art size, not 400 and 600.** `filesDir/art/{sha1}.img` at 600 px,
  served by `OfflineArtworkInterceptor` for *every* `max_size` (lists ask 200,
  heroes 800); Coil scales it. Art is fetched for the group and each track on
  request, and pruned when nothing downloaded refers to it. A locally played
  queue points its artwork at the file itself (`file://`), because Media3
  loads notification and lock-screen art with its own loader, which the Coil
  interceptor never sees — found on the emulator with the network cut.
- **"Download all releases" skips Appears On** — those are other artists'
  albums. The confirm dialog gets its numbers by fetching every release's track
  list first, so the count is exact and the size is estimated from each
  track's bitrate (median FLAC, 968 kbps, when the server sends none).
- **An album download is keyed on the MBID the album screen resolved**,
  usually the release group (the API's `album_mbid`), because the download has
  to match the track list the screen shows. An album opened by title alone has
  no stable key and gets no download button.
- **Top-tracks groups (item 11) sync on app start (when online) and on every
  reconnect**, one sync at a time. A list that fails to load is left as it is,
  so an unreachable server never reads as an empty list.

Tests: `DownloadGroupsTest` (group ids, aggregate status, size estimate) and
`OfflineArtworkTest` (URL parsing, fetch-once, prune) on the JVM;
`DownloadDaoInstrumentedTest` gains replace/sync, state preservation, cross-group
links and art references on the emulator.

Not done in this phase: the instrumented download → airplane mode → play cycle
(see Testing), and the online album/artist/playlist screens are still
API-only — reached offline via the back stack they show their load error.

## Phase 4 — offline history + Android Auto

16. Blocking bug fix: in the `JamarrPlaybackService` reporting loop,
    `apiClient.reportProgress(...)` is not wrapped in `runCatching`, unlike the
    queue and index reports above it. A throw escapes the `while (true)` loop
    and permanently kills the reporting coroutine — the
    `CoroutineExceptionHandler` logs it but does not restart it. Offline
    playback makes that failure routine.
17. Offline play log: Room table `pending_play` (trackId, playedAtUtc,
    msPlayed). Flush on reconnect.
18. Backend addition — `POST /api/history/offline`, taking a batch of
    `{track_id, played_at, ms_played}`, applying the same 30 s / 20 % threshold
    the web UI uses, idempotent on `(track_id, played_at)`. First check whether
    the history table accepts an explicit `played_at`; if not, that is one new
    `migrations/NNN_*.sql` plus the matching DDL in `app/db.py` `init_db`.
19. Android Auto: add a `Downloads` node to `JamarrLibraryProvider`'s root,
    served from Room. Biggest practical win — a car with no signal still plays.

## Phase 5 — settings and polish

20. Settings: download quality picker (reuse the server ladder from
    `app/services/stream_profiles.py`: original / FLAC 24-48 / FLAC 16-48 /
    MP3 320 / Opus 128), wifi-only downloads, prefetch cache cap, storage used,
    delete-all.
21. Default download quality: `flac_16_48` rather than `original`, for phone
    storage. **This cannot ship on its own.** Cache keys carry the quality, so
    the player must first learn to accept a downloaded track at *any* quality
    rather than only the active one — otherwise a track downloaded at
    `flac_16_48` is a cache miss during `original` playback and re-streams over
    the network. Phase 2 pins downloads to `original` for exactly this reason.

## Testing

- Unit (pure Kotlin, no Robolectric): cache-key mapping, download-state reducer,
  group/track removal logic, offline play threshold.
- Instrumented (emulator `jamarr36`, LAN server): Room DAO, and a
  download → airplane mode → play cycle.
- Backend pytest for the offline history endpoint, if Phase 4 lands.
- `android/test.sh` needs no change.

## Open decisions

- **Nav placement.** Five bottom tabs already exist (Home, Favourites,
  Playlists, Charts, History). A sixth is crowded — the recommendation is to
  reach Downloads from Home/overflow plus the offline toggle. Alternative:
  replace Charts.
- **Room vs JSON store** — see the Phase 2 risk note.
- **Is Phase 4 in scope?** It is the only part touching the backend and a
  migration. Phases 1-3 are Android-only.

Phase 1 is self-contained and worth landing first: it fixes the
expired-token-in-a-long-queue glitch class before any UI work starts.
