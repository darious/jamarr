-- Manual MusicBrainz release-group overrides for chart entries.
-- Keyed by chart entry text (case-insensitive) so overrides survive the
-- weekly chart_album wipe/reinsert and re-apply when an album re-enters.
CREATE TABLE IF NOT EXISTS chart_match_override (
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    release_group_mbid TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chart_match_override_key
    ON chart_match_override (lower(artist), lower(title));
