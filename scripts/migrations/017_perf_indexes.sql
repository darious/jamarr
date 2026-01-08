CREATE INDEX IF NOT EXISTS idx_track_release_mbid ON track(release_mbid);
CREATE INDEX IF NOT EXISTS idx_track_release_group_mbid ON track(release_group_mbid);
CREATE INDEX IF NOT EXISTS idx_track_artist_map_track ON track_artist(track_id);
CREATE INDEX IF NOT EXISTS idx_artist_album_map_artist_type ON artist_album(artist_mbid, type);
CREATE INDEX IF NOT EXISTS idx_album_release_group_mbid ON album(release_group_mbid);
