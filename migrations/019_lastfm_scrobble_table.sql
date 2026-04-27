-- Create lastfm_scrobble table (prerequisite for scrobble matching)
CREATE TABLE IF NOT EXISTS lastfm_scrobble (
    id BIGSERIAL PRIMARY KEY,
    lastfm_username TEXT NOT NULL,
    played_at TIMESTAMPTZ NOT NULL,
    played_at_uts BIGINT,
    track_mbid TEXT,
    track_name TEXT NOT NULL,
    track_url TEXT,
    artist_mbid TEXT,
    artist_name TEXT NOT NULL,
    artist_url TEXT,
    album_mbid TEXT,
    album_name TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(lastfm_username, played_at, track_name, artist_name)
);

CREATE INDEX IF NOT EXISTS idx_lastfm_scrobble_user_played
ON lastfm_scrobble(lastfm_username, played_at DESC);

-- Match table: Links scrobbles to library tracks with cache optimization
CREATE TABLE IF NOT EXISTS lastfm_scrobble_match (
    id BIGSERIAL PRIMARY KEY,
    scrobble_id BIGINT NOT NULL UNIQUE,
    track_id BIGINT NOT NULL,
    match_score DOUBLE PRECISION NOT NULL,
    match_method TEXT NOT NULL,
    match_reason TEXT,
    cache_key TEXT,
    matched_at TIMESTAMPTZ DEFAULT NOW(),
    FOREIGN KEY(scrobble_id) REFERENCES lastfm_scrobble(id) ON DELETE CASCADE,
    FOREIGN KEY(track_id) REFERENCES track(id) ON DELETE CASCADE
);

-- Index for cache key lookups (partial index for efficiency)
CREATE INDEX IF NOT EXISTS idx_scrobble_match_cache_key 
    ON lastfm_scrobble_match(cache_key) 
    WHERE cache_key IS NOT NULL;

-- Index for track_id lookups (for re-matching when tracks change)
CREATE INDEX IF NOT EXISTS idx_scrobble_match_track_id 
    ON lastfm_scrobble_match(track_id);

-- Skip artist table: Database-persisted filter for non-music content
CREATE TABLE IF NOT EXISTS lastfm_skip_artist (
    artist_name TEXT PRIMARY KEY,
    reason TEXT,
    added_at TIMESTAMPTZ DEFAULT NOW()
);

-- Populate default skip list (podcasts, radio shows, etc.)
INSERT INTO lastfm_skip_artist (artist_name, reason) VALUES
    ('bbc radio', 'radio'),
    ('bbc radio 1', 'radio'),
    ('bbc radio 1xtra', 'radio'),
    ('bbc radio 2', 'radio'),
    ('bbc radio 3', 'radio'),
    ('bbc radio 4', 'radio'),
    ('bbc radio 4 extra', 'radio'),
    ('bbc radio 5 live', 'radio'),
    ('bbc radio 6 music', 'radio'),
    ('bbc radio scotland', 'radio'),
    ('bbc radio ulster', 'radio'),
    ('bbc radio wales', 'radio'),
    ('bbc world service', 'radio'),
    ('cariad lloyd', 'podcast'),
    ('leo laporte and the twits', 'podcast'),
    ('muddy knees media', 'podcast'),
    ('hotel spa', 'ambient'),
    ('tom merritt molly wood and veronica belmont', 'podcast'),
    ('steve gibson with leo laporte', 'podcast'),
    ('pixel corps', 'podcast'),
    ('stephen colbert', 'podcast'),
    ('plosive productions', 'podcast'),
    ('rain sounds xle library', 'ambient'),
    ('nature sounds xle library', 'ambient'),
    ('spa', 'ambient')
ON CONFLICT (artist_name) DO NOTHING;
