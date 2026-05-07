# Audio Analysis Status

## What changed

Jamarr now has a local audio-analysis pipeline backed by `track_audio_analysis`.
It is driven from the scanner CLI:

```bash
docker exec -it jamarr uv run python -m app.scanner.cli audio-analysis --phase all --batch-size 25 --concurrency 4
```

Supported phases:

- Phase 1: loudness LUFS, loudness range, sample peak, true peak, leading/trailing silence.
- Phase 2: locally computed track ReplayGain via ffmpeg, plus album ReplayGain when complete albums have current track ReplayGain.
- Phase 3: local BPM estimate from decoded PCM.
- Phase 4: derived playback/quality hints and local energy score.

The CLI has Rich progress feedback with selected count, `x/y`, percentage, elapsed time, and ETA.

## Schema

New table:

- `track_audio_analysis`

Important fields:

- `track_quick_hash`
- `analysis_version`
- `phase1_analyzed_at`
- `phase2_analyzed_at`
- `phase3_analyzed_at`
- `phase4_analyzed_at`
- `loudness_lufs`
- `loudness_range_lu`
- `sample_peak_db`
- `true_peak_db`
- `first_audio_start_seconds`
- `last_audio_end_seconds`
- `leading_silence_seconds`
- `trailing_silence_seconds`
- `replaygain_track_gain_db`
- `replaygain_track_peak`
- `replaygain_album_gain_db`
- `replaygain_album_peak`
- `bpm`
- `bpm_confidence`
- `gapless_hint`
- `transition_hint`
- `energy_score_local`

Migrations added:

- `030_track_audio_analysis.sql`
- `031_track_audio_analysis_silence_durations.sql`

## Current outcomes

Last checked dataset:

- 600 analyzed rows
- 600 complete rows
- 41 artists
- 41 albums
- all 600 rows had phases 1-4 complete

The data has already surfaced useful signal:

- Source/media quality warnings: 10cc `Windows in the Jungle` has multiple tracks with very large digital silence tails.
- Energy browsing: modern compressed rock/hip-hop material ranks high; older quieter material and intros rank low.
- Tempo matching: cross-album and cross-artist tracks with compatible BPM are easy to query.

Example source issue:

- `Taxi! Taxi!` has about 349 seconds of trailing digital silence.
- Raw ffmpeg checks confirmed this is actual zero-sample tail audio, not a parser bug.

## Known caveats

- BPM is a local estimator, not a ground-truth library. It is useful for rough queueing and matching, but confidence should be considered.
- Album ReplayGain only fills once all tracks in an album have current Phase 2 analysis.
- `gapless_hint`, `transition_hint`, and `energy_score_local` are derived labels/scores. Treat them as Jamarr-local heuristics.
- Short trailing silence should not be presented as a source defect. Reserve warnings for long/severe digital tails.

## Suggested issue policy

Derive these labels in API/query logic rather than storing them as fixed facts:

- `short_silence_tail`: trailing silence from 0.2s to 5s.
- `long_silence_tail`: trailing silence from 5s to 30s.
- `long_digital_tail`: trailing silence >= 30s and >= 20% of track duration.
- `severe_digital_tail`: trailing silence >= 60s or >= 50% of track duration.

Do not auto-trim or auto-skip yet. First expose warnings/data.

## Useful commands

Run analysis:

```bash
docker exec -it jamarr uv run python -m app.scanner.cli audio-analysis --phase all --batch-size 25 --concurrency 4
```

Run a test batch:

```bash
docker exec -it jamarr uv run python -m app.scanner.cli audio-analysis --phase all --limit 100 --batch-size 25 --concurrency 4
```

Check coverage:

```bash
docker exec jamarr_db psql -p 8110 -U jamarr -d jamarr -c "
SELECT
  count(*) AS rows,
  count(*) FILTER (WHERE status='complete') AS complete,
  count(*) FILTER (WHERE phase1_analyzed_at IS NOT NULL) AS p1,
  count(*) FILTER (WHERE phase2_analyzed_at IS NOT NULL) AS p2,
  count(*) FILTER (WHERE phase3_analyzed_at IS NOT NULL) AS p3,
  count(*) FILTER (WHERE phase4_analyzed_at IS NOT NULL) AS p4
FROM track_audio_analysis;"
```

Find long tails:

```bash
docker exec jamarr_db psql -p 8110 -U jamarr -d jamarr -c "
SELECT
  t.artist,
  t.album,
  t.title,
  round(t.duration_seconds::numeric, 1) AS duration,
  round(a.trailing_silence_seconds::numeric, 2) AS tail,
  round((100 * a.trailing_silence_seconds / NULLIF(t.duration_seconds, 0))::numeric, 1) AS tail_pct
FROM track_audio_analysis a
JOIN track t ON t.id = a.track_id
WHERE a.trailing_silence_seconds >= 5
ORDER BY a.trailing_silence_seconds DESC
LIMIT 30;"
```

Find tempo-compatible tracks:

```bash
docker exec jamarr_db psql -p 8110 -U jamarr -d jamarr -c "
WITH analyzed AS (
  SELECT t.id, t.artist, t.album, t.title, a.bpm, a.bpm_confidence, a.energy_score_local
  FROM track t
  JOIN track_audio_analysis a ON a.track_id = t.id
  WHERE a.bpm IS NOT NULL AND a.bpm_confidence >= 0.75
),
pairs AS (
  SELECT
    a.artist, a.album, a.title, a.bpm, a.energy_score_local,
    b.artist AS artist2, b.album AS album2, b.title AS title2,
    b.bpm AS bpm2, b.energy_score_local AS energy2,
    abs(a.bpm - b.bpm) AS delta
  FROM analyzed a
  JOIN analyzed b ON a.id < b.id
    AND COALESCE(a.album, '') <> COALESCE(b.album, '')
  WHERE abs(a.bpm - b.bpm) <= 0.5
)
SELECT *
FROM pairs
ORDER BY (energy_score_local + energy2) DESC, delta
LIMIT 20;"
```

## Recommended next steps

1. Add API/service aggregation layer for audio analysis.
2. Add endpoints:
   - `/api/audio-analysis/summary`
   - `/api/audio-analysis/issues`
   - `/api/audio-analysis/albums`
   - `/api/audio-analysis/tracks`
   - `/api/audio-analysis/tempo-matches`
3. Add Media Quality -> Audio Analysis tab.
4. Surface source anomalies first:
   - long digital tails
   - severe digital tails
   - true peak over 0 dBTP
   - very quiet/loud masters
   - missing analysis
5. Add album and track technical panels.
6. Later add energy/tempo tools:
   - tracks like this energy
   - tempo-compatible tracks
   - Energy Lane queue generator
   - smooth queue ordering

Best first UI feature:

- Audio source anomalies, because it is low risk and immediately actionable.

Best later "wow" feature:

- Energy Lane: generate a queue from similar energy, compatible tempo, not-recently-played tracks, and limited artist repetition.
