# Last.fm scripts

These scripts match the stored Last.fm scrobbles to local tracks and help debug misses.
Jamarr no longer fetches from Last.fm (its API needs Pro from 2026-12-01), so
the scrobbles already in the database are all there is.

All commands assume `uv` and `.env` are configured (see `dev.sh`).

## match-lastfm.py

Match scrobbles to local tracks.

Options:
- `--user`: Last.fm username (default `<LASTFM_USERNAME>`)
- `--limit`: Scrobbles to match (default `200`)
- `--dry-run`: Compute matches without writing to DB
- `--force`: Overwrite existing matches
- `--fuzzy`: Enable RapidFuzz title fallback
- `--fuzzy-title-threshold`: Minimum RapidFuzz ratio (default `92`)
- `--workers`: Parallel worker threads (default `1`)
- `--auto-accept-threshold`: Auto-accept score threshold (default `0.95`)
- `--debug-miss-reasons`: Print unmatched breakdown + fuzzy counters

Examples:
```bash
uv run python scripts/lastfm/match-lastfm.py --limit 10000 --workers 8
uv run python scripts/lastfm/match-lastfm.py --fuzzy --fuzzy-title-threshold 85
uv run python scripts/lastfm/match-lastfm.py --dry-run --debug-miss-reasons
```

## review-lastfm.py

Interactive review of match candidates (manual or Ollama-assisted).

Options:
- `--user`: Last.fm username (default `<LASTFM_USERNAME>`)
- `--auto-pass`: Auto-accept obvious matches and exit
- `--auto-limit`: Max scrobbles to auto-review (default `200`)
- `--ollama`: Use Ollama for auto-review
- `--ollama-url`: Ollama base URL (default `http://localhost:11434`)
- `--ollama-model`: Ollama model (default `mistral-nemo:12b-instruct-2407-fp16`)
- `--ollama-limit`: Max scrobbles to send to Ollama (default `100`)

Examples:
```bash
uv run python scripts/lastfm/review-lastfm.py --user <LASTFM_USERNAME>
uv run python scripts/lastfm/review-lastfm.py --auto-pass --auto-limit 500
uv run python scripts/lastfm/review-lastfm.py --ollama --ollama-limit 50
```

## analyze-db-misses.py

Summarize unmatched scrobbles and common miss reasons.

Options: none.

Example:
```bash
uv run python scripts/lastfm/analyze-db-misses.py
```

## debug-misses.py

Inspect recent misses and candidate rows from `lastfm_match_candidate`.

Options: none. Edit the script to customize queries/filters.

Example:
```bash
uv run python scripts/lastfm/debug-misses.py
```

## debug-match-logic.py

Deep-dive into matching logic for specific scrobble/track pairs.

Options: none. Edit `miss_pairs` in the script to target IDs.

Example:
```bash
uv run python scripts/lastfm/debug-match-logic.py
```
