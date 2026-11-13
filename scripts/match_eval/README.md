# Match evaluation harness

Before/after comparison for the Last.fm scrobble matcher (`app/matching/`,
run by `sync_scrobbles_for_user` in `app/api/lastfm.py`). Use it before
changing matching code: snapshot a real library once, then re-match it with
the old and the new code and diff the results.

It runs the app's own re-match path (`rematch_all=True`, no fetching) against
a throwaway copy, so what it measures is what a full re-match would do on the
source server. It never writes to the source DB.

## Workflow

```bash
H=scripts/match_eval/match_eval.py

# 1. Snapshot the matcher's tables (read-only: pg_dump + one COPY).
#    --exec-prefix runs pg_dump/psql next to the source DB; default is the
#    local compose container (docker exec -i jamarr_db).
uv run python $H snapshot --exec-prefix "ssh <host> docker exec -i jamarr_db" --name <snap>

# 2. Start the scratch Postgres (container jamarr_match_eval, 127.0.0.1:8115)
#    and load the snapshot. load also exports the matches as found on the
#    source, as run "<snap>-as-found".
uv run python $H up
uv run python $H load <snap>

# 3. Re-match with the code in this checkout. Each run replaces every match
#    in the scratch DB, so runs can follow each other without reloading.
uv run python $H run before        # e.g. on main
git switch my-matcher-branch
uv run python $H run after

# 4. Diff two runs from the same snapshot -> markdown report.
uv run python $H diff before after [--top 100]

uv run python $H down              # remove the container when done
```

## Quick runs on a subset

A full run re-matches every scrobble (about 7 minutes for 131k). For quick
iteration, build a subset once, after a full run:

```bash
uv run python $H subset quick --runs before before-repeat   # flagged + moved + 5000 sampled
uv run python $H run try-1 --subset quick                    # well under a minute
uv run python $H run try-2 --subset quick
uv run python $H diff try-1 try-2
```

The subset holds every scrobble a metric flags in the loaded full run,
every scrobble whose match differs between the `--runs` given, and a seeded
random sample (`--sample`, `--seed`). A subset run puts only those scrobbles
through the same matching loop (`match_and_store`), so it can't show effects
that depend on batches: cache copying between scrobbles, and order. Before
merging, do a full run and a repeat full run. Diffs only compare runs over the
same subset (or two full runs).

Tests come first, in seconds: `tests/unit/test_matcher_regressions.py`
(scorer cases from real misses) and
`tests/integration/test_lastfm_match_and_store.py` (batches and the cache).

## Output

Everything lives under `~/.cache/jamarr/match-eval/` (override with
`--workdir` or `MATCH_EVAL_DIR`), never in the repo:

- `snapshots/<snap>/`: `schema.dump`, `data.dump`, `users.csv`.
- `runs/<label>/`: `matches.csv.gz` (one row per scrobble: the scrobble, the
  matched track, score, method, reason), `metrics.json`, `meta.json` (git
  commit and dirty flag, run time, sync options).
- `runs/diff-<a>--<b>.md`: metrics side by side, then scrobbles grouped by
  outcome (moved to another track, matched in only one run), largest groups
  first.

## Metrics

Heuristic counts from the issue #366 investigation; lower is better:

- `wrong_release`: the scrobble's `album_mbid` names a library release that
  has a track with the same title, but the scrobble is matched elsewhere.
- `version_collapse`: a labelled version ("(Live)", "(Acoustic)",
  "(Radio Edit)", ...) is matched to a differently titled track although the
  library has the exact title by that artist.
- `version_drift`: the reverse, a scrobble without a label matched to a
  labelled version although the plain title exists.
- `double_counted`: a Last.fm history row coincides (same user, ±5 s) with a
  local play of a different track, so one play counts twice.

The two version metrics skip a scrobble matched on the album it names when
that album only has the other title (a single mix on a singles collection, a
live album's tracks): that match is right.

They flag suspects, not certain errors: read the diff's groups before trusting
a number. After changing a metric, recompute saved runs so their numbers stay
comparable (it loads each run's matches back into the scratch DB):

```bash
uv run python $H rescore before after
```

## Noise

Before `feat/matcher-determinism`, the matcher was not deterministic: two runs
of the same code on the same snapshot moved 430 scrobbles, and still 327 with
a fixed `PYTHONHASHSEED`. The winner depended on candidate order (SQL without
`ORDER BY`, set iteration), and the cache chose between rows with equal
`matched_at`. Now the winner is the maximum of a total sort key, and repeat
runs diff to zero. If a change brings noise back, a repeat run shows it, so
make "repeat full run diffs to zero" part of checking any matcher change.

## Notes

- The snapshot copies `artist`, `track`, `track_artist`, `lastfm_scrobble`,
  `lastfm_scrobble_match`, `lastfm_skip_artist` and `playback_history`.
  `user` is not dumped: only id, username and Last.fm username are exported,
  and `load` recreates those rows with placeholder credentials. The
  snapshot still holds listening history, so keep it on the dev box.
- `run` and the export refuse any DB without the `match_eval_marker` table
  that `load` creates, so they can't be pointed at a real install.
- Restoring uses `--disable-triggers`, because tables outside the snapshot
  (artwork, album, ...) would otherwise fail their foreign keys.
