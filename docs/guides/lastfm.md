# Last.fm

Jamarr can pull your Last.fm scrobbles, match them to local tracks, and merge
them with local playback history into one timeline.

!!! info "Code"
    `app/lastfm.py`, `app/lastfm_sync_manager.py`, `app/lastfm_jobs.py`,
    `app/matching/` (scrobble→track matching), API in `app/api/lastfm.py`.

## Setup

1. Get Last.fm API credentials from
   <https://www.last.fm/api/account/create> and set in `.env`:

   ```
   LASTFM_API_KEY=...
   LASTFM_SHARED_SECRET=...
   ```

2. In the UI (or via the API), connect your account:
   `GET /api/lastfm/auth/start` → authorize on Last.fm →
   `GET /api/lastfm/callback`.

3. Enable the integration: `POST /api/lastfm/toggle`.

Check state any time with `GET /api/lastfm/status`.

## Syncing

Start a sync with `POST /api/lastfm/sync`; progress streams over SSE at
`GET /api/lastfm/events`. Sync:

- pulls scrobbles from Last.fm,
- matches each to a local track (fuzzy match in `app/matching/`), storing results
  in `lastfm_scrobble_match`,
- merges local history + matched scrobbles into the
  `combined_playback_history_mat` materialized view that powers History and
  Recommendations.

Recurring syncs can be scheduled via the [scheduler](../reference/api.md)
(`/api/scheduler/*`).

## Disconnecting

`POST /api/lastfm/disconnect` removes the link; `POST /api/lastfm/toggle` can
disable syncing without disconnecting.
