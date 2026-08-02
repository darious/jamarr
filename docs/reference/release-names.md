# Release names

Every Jamarr release gets a musician or band as a codename, passed to
`release.sh` alongside the version:

```bash
./release.sh v1.5.0 "Arcade Fire"
```

That produces the tag `v1.5.0` and a GitHub release titled
`v1.5.0 - Arcade Fire`. Use `--dry-run` first to validate without pushing.

## Convention

- One artist per release, **used once and never reused**.
- Every `v1.x` release so far has used an artist beginning with **A**, so the
  letter appears to track the major version — `v1.x` = A, `v2.x` = B.
  Confirm that before cutting `v2.0.0`; nothing in `release.sh` enforces it.
- Ordering within a letter is not alphabetical and never has been. Pick
  whichever name fits; the queue below is just to avoid repeats and
  deliberation.

## Used

| Version | Name | Released |
|---|---|---|
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

## Queue

The artists with the most tracks in the library, already-used names removed.
Take from the top, delete the line, and move it into the table above as part
of the release commit.

| # | Name | Tracks |
|---|---|---|
| 1 | Tori Amos | 306 |
| 2 | Bryan Adams | 299 |
| 3 | Christina Aguilera | 177 |
| 4 | All Time Low | 150 |
| 5 | Alter Bridge | 147 |
| 6 | Ryan Adams | 147 |
| 7 | Anastacia | 139 |
| 8 | Ash | 137 |
| 9 | Asian Dub Foundation | 130 |
| 10 | James Arthur | 109 |
| 11 | Anthrax | 108 |
| 12 | Avenged Sevenfold | 107 |
| 13 | Ashanti | 105 |
| 14 | Anouk | 101 |
| 15 | ATB | 101 |
| 16 | Autechre | 101 |
| 17 | AWOLNATION | 101 |
| 18 | Amon Amarth | 96 |
| 19 | Anathema | 92 |
| 20 | Air | 91 |

Counts are from the production library on 2026-08-02. Grouping uses
`artist.letter`, which is derived from the sort name — so artists filed under
a surname (Tori Amos, Bryan Adams) count as A, matching how the library
browses. Regenerate against prod with:

```sql
SELECT a.name, COUNT(DISTINCT ta.track_id) AS tracks
FROM artist a
JOIN track_artist ta ON ta.artist_mbid = a.mbid
WHERE a.letter = 'A'
GROUP BY a.name
ORDER BY tracks DESC, a.name
LIMIT 45;
```

## Before tagging

`release.sh` checks the tag does not already exist and that the tree is
clean, but it does not check any of the following:

- **Bump `versionCode` and `versionName`** in `android/app/build.gradle.kts`.
  `versionCode` must increase for every published APK, or a device cannot tell
  one build from the next and will not treat it as an update.
- Land everything through a PR to `main` first — tagging is what publishes the
  signed APK (`android_release.yml`) and the Docker image
  (`publish_docker.yml`), and both are public and awkward to retract.
- Pick MAJOR/MINOR/PATCH from what actually changed: a new user-facing feature
  is a MINOR bump, a fix-only release is a PATCH.
