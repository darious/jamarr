-- Migration: Add indexes for recommendation system performance
-- Description: Adds critical indexes to speed up recommendation queries by 2-10x

-- Index for combined_playback_history_mat - most critical for seed generation
CREATE INDEX IF NOT EXISTS idx_cph_user_played_at 
ON combined_playback_history_mat(user_id, played_at DESC);

CREATE INDEX IF NOT EXISTS idx_cph_track_user 
ON combined_playback_history_mat(track_id, user_id);

-- Index for track_artist - used in every seed query join
CREATE INDEX IF NOT EXISTS idx_track_artist_track 
ON track_artist(track_id, artist_mbid);

-- Index for artist_album - used in recommendation filtering
CREATE INDEX IF NOT EXISTS idx_artist_album_artist_type 
ON artist_album(artist_mbid, type) WHERE type = 'primary';

-- Indexes for top_track - used in album scoring
CREATE INDEX IF NOT EXISTS idx_top_track_track_type 
ON top_track(track_id, type);

CREATE INDEX IF NOT EXISTS idx_top_track_type_popularity 
ON top_track(type, popularity DESC) WHERE type IN ('top', 'single');

-- Indexes for track - used in exclusion filters
CREATE INDEX IF NOT EXISTS idx_track_release_mbid 
ON track(release_mbid) WHERE release_mbid IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_track_artist_mbid 
ON track(artist_mbid) WHERE artist_mbid IS NOT NULL;
