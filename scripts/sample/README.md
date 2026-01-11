# Sample scripts

Small utilities and experiments that hit external APIs.

Use `uv run python scripts/sample/<script>.py ...` for consistent deps.

## `chart.py`

Scrapes the Official Charts albums chart and prints a table. Also attempts MusicBrainz matching for entries.

CLI options:
- `--limit`: Number of rows to print (default: 20).
- `--url`: Chart URL to scrape (default: Official Charts albums chart).
- `--mb-base-url`: MusicBrainz API base URL (default: `http://192.168.1.105:5000`).

Examples:
```bash
uv run python scripts/sample/chart.py
uv run python scripts/sample/chart.py --limit 50
uv run python scripts/sample/chart.py --url https://www.officialcharts.com/charts/albums-chart/
```

## `mb_to_qobuz.py`

Maps a MusicBrainz artist MBID to a Qobuz artist link. Accepts a single MBID or a file containing MBIDs (one per line, optional existing link).

CLI options:
- `input`: Required. MusicBrainz artist MBID or a file path.

Examples:
```bash
uv run python scripts/sample/mb_to_qobuz.py b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d
uv run python scripts/sample/mb_to_qobuz.py /tmp/mbids.txt
```
