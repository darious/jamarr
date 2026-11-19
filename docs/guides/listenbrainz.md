# ListenBrainz

Jamarr sends your plays to [ListenBrainz](https://listenbrainz.org), reads back
listens other apps sent there, and uses ListenBrainz for artist top tracks and
similar artists. It replaced Last.fm, whose API needs a paid subscription from
1 December 2026. Scrobbles Jamarr already fetched from Last.fm stay in history
as an archive.

!!! info "Code"
    Client `app/listenbrainz.py`; sending plays `app/listenbrainz_submissions.py`;
    reading listens `app/listenbrainz_sync.py`; Last.fm reload
    `app/listenbrainz_import.py`; Last.fm archive `app/lastfm_archive.py`;
    top tracks and similar artists `app/scanner/services/listenbrainz.py`;
    API `app/api/listenbrainz.py`.

## Connecting

ListenBrainz has no application keys. Each user connects their own account:

1. Copy your user token from <https://listenbrainz.org/settings/>.
2. In Jamarr, **Settings → User → ListenBrainz**, paste it and connect. Jamarr
   checks it with ListenBrainz before saving it.

The card shows how many plays were sent, are waiting, or were refused, and has
a pause switch and a **Sync now** button.

## Sending plays

Every play Jamarr records (browser, renderers, Cast, Android offline uploads)
is sent, stamped at the time it started. Plays queue in the database, so when
ListenBrainz is unreachable they are retried with backoff (1 minute, doubling
up to 6 hours) and nothing is lost. If ListenBrainz rejects the token, sending
pauses until you paste a new one. Plays made while paused are never sent.

Listens carry MusicBrainz recording, release and artist IDs from your tags.

## Listens from other apps

The **Update ListenBrainz Listens + Match** scheduled job (and **Sync now**)
reads listens other scrobblers sent to ListenBrainz, such as a phone
scrobbler, matches them to library tracks, and adds them to history. Listens
Jamarr sent itself are skipped, since they are already local plays. Each sync
looks back 14 days, so a phone that uploads late is still picked up. The same
job also matches any stored Last.fm scrobbles that are still unmatched.

## History and the cutover

Each user has a **cutover** time. History shows stored Last.fm scrobbles
before it and ListenBrainz listens from it on, so the two never overlap. An
outside listen of a track Jamarr played within a minute counts as that same
play. Disconnecting ListenBrainz never moves the cutover.

## Top tracks and similar artists

The scanner's top-tracks and similar-artists stages use ListenBrainz:
top tracks from its listen counts (one recording per song), similar artists
from its Labs ranking, falling back to lb-radio. ListenBrainz requires a token
for top tracks: set `LISTENBRAINZ_TOKEN`, or connect a user, whose token is
then used (admins first). An artist ListenBrainz knows nothing about keeps the
data it already has.

## Moving from Last.fm

Last.fm history is copied into ListenBrainz once, from Jamarr's own copy, so
it carries Jamarr's MusicBrainz matches. The steps that touch Last.fm have to
happen **before** you deploy the release that removed it, and before
1 December 2026.

**On the old release:**

1. Point any other scrobbler (for example a phone app) at ListenBrainz as
   well as Last.fm.
2. If your ListenBrainz account already has listens you want replaced, delete
   them (ListenBrainz → Settings → Delete listens) and wait until its listen
   count reaches 0. Note the time you deleted them: that is the **cutover**.
3. Let one Last.fm sync run after the cutover (the daily job, or
   **Update Scrobbles & Match**), so the stored scrobbles reach it.

**After deploying:**

4. Connect ListenBrainz in Settings.
5. Rematch the archive with the current matcher:

    ```
    docker compose exec jamarr uv run python -m app.lastfm_archive --user <jamarr-user> --all
    ```

6. Dry run the reload and check the duplicates it will drop:

    ```
    docker compose exec jamarr uv run python -m app.listenbrainz_import \
        --user <jamarr-user> --cutover <cutover, ISO 8601> --dry-run --report cache/lb-import
    ```

    `duplicates.csv` lists each dropped scrobble next to the one kept. Two
    scrobbles of one track closer together than Last.fm's own rule allows
    (half the track, 4 minutes at most) count as one listen.

7. Run it for real (same command without `--dry-run`). This sets the cutover,
   so Jamarr starts sending its own plays from that moment. It prints a
   `--after` resume point after every batch of 1,000; rerun with it if the
   run stops. ListenBrainz files imports in the background, so its count
   catches up over a while.

A scheduled Last.fm sync becomes the ListenBrainz sync when the release is
deployed (migration 038).
