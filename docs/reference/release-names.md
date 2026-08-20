# Release names

Every Jamarr release gets a musician or band as a codename, passed to
`release.sh` alongside the version:

```bash
./release.sh v1.8.1 "Hans Zimmer"           # server: Docker image
./release.sh android-v1.9.0 "All Time Low"  # app: signed APK
```

That produces the tag and a GitHub release titled `<tag> - <Name>`. Use
`--dry-run` first to validate without pushing.

## Two streams, two letters

The server and the Android app are released independently, because they are
installed independently — a phone can be several server releases behind.

| Stream | Tag | Letter | Builds | Triggered workflow |
|---|---|---|---|---|
| Server (backend + web UI) | `v1.8.1` | **Z** | Docker image, `latest` moves | `publish_docker.yml` |
| App | `android-v1.9.0` | **A** | signed APK on the release | `android_release.yml` |

The letter is what tells the two chains apart at a glance: a Z name is a server
release, an A name is an app release. Before `v1.8.1` both streams drew from
the same A pool, which is why the server's history below is all A names.

The letter walks with the major version — the app counts **up** from A, the
server counts **down** from Z:

| Major | App | Server |
|---|---|---|
| 1.x | A | Z |
| 2.x | B | Y |
| 3.x | C | X |

`release.sh` derives this rather than hardcoding it, so a major bump needs no
change to the script. The two chains would collide at 13.x, which is a problem
for a future that will not arrive.

A server tag does not rebuild the APK, and an app tag does not rebuild the
image. Before the split (`ad5403d`), `android_release.yml` fired on every `v*`
tag, so a backend-only release republished an unchanged APK.

## Version numbers drift, and that is fine

The two numbers are independent and are **expected** to diverge. The server may
be several releases ahead while the app sits unchanged; the app's number then
tells you the release it last actually changed in.

Align them — cut both at the same number — **only when a change to one requires
the other**: a new API the app depends on, a contract change, an auth or stream
format the old client cannot speak. A fix that only touches one artifact ships
on one stream. Never bump a version to keep the numbers level.

There is nothing else in the repo carrying a version. The web UI is built into
the server image and served by it, so it can never be out of step. The TUI is
not published — it runs from a checkout. The `0.1.0` strings in
`pyproject.toml`, `tui/pyproject.toml` and `web/package.json` are inert
placeholders that nothing reads.

## Convention

- One artist per release, **used once and never reused** — across both streams.
- The letter comes from the stream and the major version: `v1.x` takes Z, `v2.x`
  takes Y; `android-v1.x` takes A, `android-v2.x` takes B.
- Ordering within a letter is not alphabetical and never has been. Pick
  whichever name fits; the queues below are just to avoid repeats and
  deliberation.
- Move a name from the queue into the used table as part of the release.

## Used

Reconciled against the published releases on 2026-08-20.

| Tag | Name | Released |
|---|---|---|
| v1.8.0 | Alter Bridge | 2026-08-11 |
| android-v1.8.0 | Alter Bridge | 2026-08-11 |
| v1.7.0 | Christina Aguilera | 2026-08-10 |
| v1.6.0 | Bryan Adams | 2026-08-09 |
| v1.5.0 | Tori Amos | 2026-08-02 |
| v1.4.2 | Aphex Twin | 2026-07-29 |
| v1.4.1 | AC/DC | 2026-07-24 |
| v1.4.0 | Adele | 2026-07-23 |
| v1.3.4 | Alice Cooper | 2026-05-13 |
| v1.3.3 | Avicii | 2026-05-08 |
| v1.3.2 | Angels & Airwaves | 2026-05-04 |
| v1.3.1 | Alphaville | 2026-05-03 |
| v1.3.0 | Alice in Chains | 2026-05-01 |
| v1.2.1 | A-ha | 2026-04-29 |
| v1.2.0 | Aerosmith | 2026-04-29 |
| v1.1.0 | Arctic Monkeys | 2026-04-28 |
| v1.0.0 | ABBA | 2026-04-27 |

`android-v1.8.0` and `v1.8.0` share a name: they were cut three minutes apart
when the streams split, and are the only pair that will.

## Queue — server (Z)

| # | Name | Tracks |
|---|---|---|
| 1 | ZZ Top | 180 |
| 2 | Hans Zimmer | 155 |
| 3 | Rob Zombie | 108 |
| 4 | ZAYN | 64 |
| 5 | Zero 7 | 51 |
| 6 | The Zutons | 46 |
| 7 | Zedd | 36 |
| 8 | Zucchero | 28 |
| 9 | Zeitkratzer | 6 |
| 10 | Zendaya | 4 |

The Z bench is shallow — 40 artists in the library, and only eight with real
catalogues. When it runs out, take any Z artist rather than reaching for
another letter; the letter is what identifies the stream and the major version.
The bench refills at `v2.0.0`, which moves the server chain to Y.

## Queue — app (A)

Already-used names removed.

| # | Name | Tracks |
|---|---|---|
| 1 | All Time Low | 150 |
| 2 | Ryan Adams | 147 |
| 3 | Anastacia | 139 |
| 4 | Ash | 137 |
| 5 | Asian Dub Foundation | 130 |
| 6 | James Arthur | 109 |
| 7 | Anthrax | 108 |
| 8 | Avenged Sevenfold | 107 |
| 9 | Ashanti | 105 |
| 10 | Anouk | 101 |
| 11 | ATB | 101 |
| 12 | Autechre | 101 |
| 13 | AWOLNATION | 101 |
| 14 | Amon Amarth | 96 |
| 15 | Anathema | 92 |
| 16 | Air | 91 |

## Regenerating a queue

Counts are from the production library — A on 2026-08-02, Z on 2026-08-20.
Grouping uses `artist.letter`, derived from the sort name, so artists filed
under a surname (Tori Amos, Hans Zimmer) count as A and Z respectively,
matching how the library browses.

```sql
SELECT a.name, COUNT(DISTINCT ta.track_id) AS tracks
FROM artist a
JOIN track_artist ta ON ta.artist_mbid = a.mbid
WHERE a.letter = 'Z'
GROUP BY a.name
ORDER BY tracks DESC, a.name
LIMIT 45;
```

Without database access, the running server answers the same question:
`GET /api/artists?starts_with=Z` for the names, then `GET /api/tracks?artist=<name>`
per artist for the counts. The API route credits featured artists slightly
differently from the SQL, so treat its counts as approximate — fine for
ordering a queue.

## Before tagging

**There is nothing to bump.** The tag is the version:

- `android_release.yml` parses `android-vX.Y.Z` and builds the APK with that
  `versionName`, plus a `versionCode` derived from it (`major*10000 +
  minor*100 + patch`, so 1.8.0 is 10800). It then re-reads the built APK and
  fails the release if either disagrees with the tag.
- `publish_docker.yml` bakes the tag into the image as `JAMARR_VERSION`, which
  is what `/api/version` and the generated API reference report.

Nothing in the working tree carries a version, so there is no bump to forget,
no version to collide with another PR, and no way for a published artifact to
disagree with its tag. Builds outside a release report `0.0.0-dev` (app) or
`dev` (server).

`release.sh` checks the tag does not already exist and that the tree is clean.
It does not check:

- Land everything through a PR to `main` first — tagging is what publishes the
  signed APK and the Docker image, and both are public and awkward to retract.
- Pick MAJOR/MINOR/PATCH from what actually changed: a new user-facing feature
  is a MINOR bump, a fix-only release is a PATCH.
- The two streams number independently, and the letter must match the stream.
