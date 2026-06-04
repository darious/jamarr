# ADR-0005: Two-phase library scan (scan, then enrich)

- **Status:** Accepted
- **Date:** scanner v3

## Context

A music library scan does two very different kinds of work: reading file tags off
disk (fast, local, deterministic) and fetching rich metadata from external APIs
(slow, rate-limited, network-dependent — MusicBrainz, Spotify, Last.fm, Fanart.tv,
Qobuz). Doing both in one pass means a full scan is gated by the slowest external
API, and a transient API failure can stall ingesting files that are already on
disk.

## Decision

Split scanning into two CLI phases (`app/scanner/cli.py`):

1. **`scan`** — walk the filesystem, extract tags (mutagen), detect changes via
   `mtime`, and populate tracks/artists/albums + MusicBrainz IDs. Fast and
   offline.
2. **`metadata`** — enrich the existing DB from external APIs (bios, artwork,
   sort names, external links) through the v3 pipeline. Only fills blank fields;
   never overwrites tag-based names.

`prune` removes orphans; `full` runs scan → metadata → prune. Enrichment is built
as a planner/executor/stages pipeline (see
[Scanner Pipeline](../scanner-pipeline.md)).

## Consequences

- Initial scans are fast and usable immediately; rich metadata fills in
  on-demand or in the background.
- External API failures degrade gracefully — they only affect the `metadata`
  phase, not file ingestion.
- Enrichment is re-runnable and filterable (`--artist`, `--mbid`, `--links-only`,
  `--bio-only`) without re-walking the filesystem.
- Cost: a freshly scanned library looks sparse until `metadata` runs; multi-artist
  collaborations have blank names until then.
