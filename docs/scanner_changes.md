# Release Type

Remove both `type` fields from album and still add `release_type` to both track and album so they match.

Normalize raw FLAC release-type tags into these UI-level categories:
album | live | compilation | EP | single | other

Preserve the original raw value for audit and future reprocessing.

Fields (for each track and album)
- `release_type_raw` (TEXT) — exact tag value(s), never overwritten
- `release_type` (TEXT) — one of: `album` | `live` | `compilation` | `EP` | `single` | `other`

Raw values are extracted verbatim from FLAC tags, e.g.:
- `album`
- `album;live`
- `mixtape/street`
- `dj-mix`
- `soundtrack`
- `<none>`

## Normalization rules

1. Tokenization
   - Split `release_type_raw` on `;`
   - Trim whitespace
   - Case-insensitive matching
   - First matching rule wins (see Ordering below)

2. Mapping (apply in order)
   - album
     - Match if any token is `album` or starts with `album` (e.g. `album+*`)
     - Examples: `album`, `album;live`, `album;compilation`, `album;remix`, `album;soundtrack`
   - live
     - Match if token is `live` (only when not already classified as `album`)
   - compilation
     - Match if token is any of:
       - `compilation`, `soundtrack`, `remix`, `dj-mix`, `mixtape/street`
   - EP
     - Match if token is `ep`
   - single
     - Match if token is `single`
   - other
     - Any other value (except `<none>`) maps to `other` (examples: `demo`, `spokenword`)

3. Missing / Unknown
   - If no recognised token exists:
     - `release_type_raw = "<none>"`
     - `release_type = "album"`

### Outliers
- Rare values should be folded into existing buckets; do not create new UI categories.

### Ordering (important)
Apply rules in this exact order:
1. album  
2. live  
3. compilation  
4. EP  
5. single  
6. fallback to other

This prevents `album;live` being misclassified as `live`.

### Non-goals (explicit)
- ❌ Do not delete or rewrite original tags  
- ❌ Do not invent new UI categories  
- ❌ Do not infer meaning beyond tag content

### UX / follow-up
- Add the count and a clickable link to the media-quality page album section for items with `release_type_raw = "<none>"` so they can be cleaned up later.

# Dates

Replace the current `date` field on `track` with:
- `release_date_raw` — the raw extracted value from the tag  
- `release_date_tag` — the name of the tag the raw value came from  
- `release_date` — the standardized date (defaults: 1st of month if only year+month; 1st January if only year)

On `album`, keep using `release_date`, but ensure it is a date in the same format as `track.release_date`.

Make sure album dates are updated when tracks change during a scan (same behavior as track updates).

## Precision-first priority order
Prefer the most precise date value (full > partial > year-only). If multiple candidates have the same precision, use tag order as a tiebreaker.

### Date tag scanning order (used for tie-breaking only; precision has priority)
Full/partial candidates (scanned first):
- `MUSICBRAINZ_ORIGINAL_RELEASE_DATE`
- `ORIGINALDATE`
- `TDOR`
- `MUSICBRAINZ_RELEASEDATE`
- `DATE`
- `RELEASEDATE`
- `TDRC`

Year-only fallbacks (only if no full/partial date found):
- `MUSICBRAINZ_ORIGINAL_RELEASE_YEAR`
- `ORIGINALYEAR`
- `TORY`
- `MUSICBRAINZ_RELEASE_YEAR`
- `YEAR`
- `TYER`

## Key rule to implement
- For each candidate tag:
  - Inspect the value (not the tag name)
  - Classify precision:
    - `YYYY-MM-DD` → full date
    - `YYYY-MM` → partial date
    - `YYYY` → year-only
  - Choose the highest-precision value; if multiple values have equal precision, prefer the one earlier in the tag order above.
  - Example: `DATE=1999-06-01` beats `ORIGINALYEAR=1999`.

# Genre

- Remove the `genre` field from `track` — it is always null and not used (please confirm if any downstream code expects it; otherwise drop).

# Examples and Notes

- `release_type_raw` is never overwritten; it remains the verbatim tag content.  
- If a raw value contains multiple tokens, tokenization and ordering rules determine the final `release_type`.  
- Do not create new UI categories for rare or outlier tags; fold them into existing categories or `other`.
