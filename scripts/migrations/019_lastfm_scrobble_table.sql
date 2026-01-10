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
