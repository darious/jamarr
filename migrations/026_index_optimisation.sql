-- Index for fast artist/album lookups and filtering
CREATE INDEX IF NOT EXISTS idx_artist_album_lookup 
ON artist_album (artist_mbid, album_mbid);

-- Index for grouping tracks by album (crucial for the LATERAL join and track stats)
CREATE INDEX IF NOT EXISTS idx_track_release_mbid 
ON track (release_mbid);

-- Index for the playback history join (speeds up the 'listens' subquery)
CREATE INDEX IF NOT EXISTS idx_playback_history_track_id 
ON combined_playback_history_mat (track_id);

-- Index for external links by entity (speeds up the link aggregation)
CREATE INDEX IF NOT EXISTS idx_external_link_entity 
ON external_link (entity_id, entity_type);

-- Optimization for the 'ma' subquery (multi-artist links)
CREATE INDEX IF NOT EXISTS idx_artist_album_primary 
ON artist_album (album_mbid) 
WHERE type = 'primary';



CREATE INDEX IF NOT EXISTS idx_artist_album_counts 
ON artist_album (artist_mbid, type, album_mbid);


-- Supports the playback history lookup
CREATE INDEX IF NOT EXISTS idx_track_artist_mbid 
ON track_artist (artist_mbid, track_id);

-- Supports the external link pivot
CREATE INDEX IF NOT EXISTS idx_external_link_artist_pivot 
ON external_link (entity_id, entity_type, type);

-- Supports the album counts
CREATE INDEX IF NOT EXISTS idx_artist_album_counts 
ON artist_album (artist_mbid, type, album_mbid);
