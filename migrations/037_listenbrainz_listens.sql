-- Listens read back from ListenBrainz from each user's cutover on, matched to
-- library tracks like Last.fm scrobbles. init_db creates the same objects
-- (it runs first and the history view depends on them); this records them.
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS listenbrainz_synced_at TIMESTAMPTZ;
-- History split: Last.fm rows before it, ListenBrainz rows from it. Unlike
-- listenbrainz_since (where the submission queue starts) it survives a
-- disconnect, so history never flips back.
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS listenbrainz_cutover TIMESTAMPTZ;
-- Newest listened_at the sync has read, Jamarr's own listens included.
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS listenbrainz_synced_through BIGINT;

CREATE TABLE IF NOT EXISTS listenbrainz_listen (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    listened_at TIMESTAMPTZ NOT NULL,
    listened_at_uts BIGINT NOT NULL,
    recording_msid TEXT,
    artist_name TEXT NOT NULL,
    track_name TEXT NOT NULL,
    release_name TEXT,
    recording_mbid TEXT,
    release_mbid TEXT,
    artist_mbids TEXT[],
    -- ListenBrainz's own mapping, kept for reference only: its release is the
    -- canonical one, not the edition played, so it never feeds the matcher.
    mapped_recording_mbid TEXT,
    submission_client TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, listened_at_uts, artist_name, track_name)
);
CREATE INDEX IF NOT EXISTS idx_listenbrainz_listen_user_listened
    ON listenbrainz_listen(user_id, listened_at DESC);

CREATE TABLE IF NOT EXISTS listenbrainz_listen_match (
    id BIGSERIAL PRIMARY KEY,
    listen_id BIGINT NOT NULL UNIQUE
        REFERENCES listenbrainz_listen(id) ON DELETE CASCADE,
    track_id BIGINT NOT NULL REFERENCES track(id) ON DELETE CASCADE,
    match_score DOUBLE PRECISION NOT NULL,
    match_method TEXT NOT NULL,
    match_reason TEXT,
    cache_key TEXT,
    matched_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_listenbrainz_listen_match_cache_key
    ON listenbrainz_listen_match(cache_key) WHERE cache_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_listenbrainz_listen_match_track
    ON listenbrainz_listen_match(track_id);
