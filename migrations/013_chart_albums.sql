-- Create chart_album table to store Official Charts data
CREATE TABLE IF NOT EXISTS chart_album (
    position INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    last_week TEXT,
    peak TEXT,
    weeks TEXT,
    status TEXT,
    release_mbid TEXT,
    release_group_mbid TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for joining
CREATE INDEX IF NOT EXISTS idx_chart_album_rg_mbid ON chart_album(release_group_mbid);
