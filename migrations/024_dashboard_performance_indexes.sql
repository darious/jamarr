-- Performance indexes for dashboard queries
-- These indexes optimize the /api/home/* endpoints

-- Index for track.updated_at (used in new-releases ordering)
CREATE INDEX IF NOT EXISTS idx_track_updated_at ON track(updated_at DESC);

-- Index for track.id (used in recently-added-albums ordering)
CREATE INDEX IF NOT EXISTS idx_track_id_desc ON track(id DESC);

-- Composite index for track album grouping with release_date
CREATE INDEX IF NOT EXISTS idx_track_album_release_date 
    ON track(album, release_mbid, release_date DESC) 
    WHERE album IS NOT NULL;

-- Index for track.album (used in WHERE clause)
CREATE INDEX IF NOT EXISTS idx_track_album ON track(album) WHERE album IS NOT NULL;

-- Index for track_artist joins
CREATE INDEX IF NOT EXISTS idx_track_artist_artist_mbid ON track_artist(artist_mbid);
