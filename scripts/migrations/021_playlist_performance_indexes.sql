-- Add indexes to improve playlist query performance

-- Index for filtering playlists by user
CREATE INDEX IF NOT EXISTS idx_playlist_user_id ON playlist(user_id);

-- Index for sorting playlists by updated_at (DESC for most recent first)
CREATE INDEX IF NOT EXISTS idx_playlist_updated_at ON playlist(updated_at DESC);

-- Index for artwork lookups in playlist queries
CREATE INDEX IF NOT EXISTS idx_track_artwork_id ON track(artwork_id);

-- Index for reverse lookups from track to playlist_track
CREATE INDEX IF NOT EXISTS idx_playlist_track_track_id ON playlist_track(track_id);
