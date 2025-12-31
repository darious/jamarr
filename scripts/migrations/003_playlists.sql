-- Playlists table (Singular 'playlist')
CREATE TABLE IF NOT EXISTS playlist (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL,
    name          TEXT NOT NULL,
    description   TEXT,
    is_public     BOOLEAN NOT NULL DEFAULT FALSE,
    last_updated  DOUBLE PRECISION NOT NULL,

    FOREIGN KEY (user_id) REFERENCES "user"(id) ON DELETE CASCADE
);

-- Playlist Tracks table (Singular 'playlist_track')
-- track_id is NOT unique per playlist to allow duplicates as requested
CREATE TABLE IF NOT EXISTS playlist_track (
    id           BIGSERIAL PRIMARY KEY,
    playlist_id  BIGINT NOT NULL,
    track_id     BIGINT NOT NULL,
    position     INTEGER NOT NULL,

    FOREIGN KEY (playlist_id) REFERENCES playlist(id) ON DELETE CASCADE,
    FOREIGN KEY (track_id) REFERENCES track(id) ON DELETE CASCADE
);

-- Index for efficient ordering
CREATE INDEX IF NOT EXISTS idx_playlist_track_pos ON playlist_track(playlist_id, position);
