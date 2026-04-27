-- Migration: Add indexes for all-time discovery/recommendation queries
-- Description: Optimizes the days=0 (all-time) case which was 10x slower than windowed queries

-- Index for all-time seed generation
-- When days=0, the query uses "WHERE user_id = $1" without time filtering
-- The existing idx_cph_user_played_at is optimized for (user_id, played_at)
-- but for all-time queries, we just need user_id
CREATE INDEX IF NOT EXISTS idx_cph_user_id 
ON combined_playback_history_mat(user_id);

-- Index for track lookups in NOT EXISTS subqueries
-- Used in get_recommendations to exclude artists user has played
CREATE INDEX IF NOT EXISTS idx_track_artist_mbid_id 
ON track(artist_mbid, id) WHERE artist_mbid IS NOT NULL;

-- Index for album exclusion in get_recommended_albums
CREATE INDEX IF NOT EXISTS idx_track_release_mbid_id 
ON track(release_mbid, id) WHERE release_mbid IS NOT NULL;

-- Index for combined_playback_history_mat track_id lookups
-- Used in NOT EXISTS subqueries to check if user played specific tracks
CREATE INDEX IF NOT EXISTS idx_cph_track_id_user_id 
ON combined_playback_history_mat(track_id, user_id);
