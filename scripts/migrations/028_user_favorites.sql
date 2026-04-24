CREATE TABLE IF NOT EXISTS favorite_artist (
    user_id BIGINT NOT NULL,
    artist_mbid TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, artist_mbid),
    FOREIGN KEY(user_id) REFERENCES "user"(id) ON DELETE CASCADE,
    FOREIGN KEY(artist_mbid) REFERENCES artist(mbid) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS favorite_release (
    user_id BIGINT NOT NULL,
    album_mbid TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, album_mbid),
    FOREIGN KEY(user_id) REFERENCES "user"(id) ON DELETE CASCADE,
    FOREIGN KEY(album_mbid) REFERENCES album(mbid) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_favorite_artist_user_created
    ON favorite_artist(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_favorite_artist_artist
    ON favorite_artist(artist_mbid);

CREATE INDEX IF NOT EXISTS idx_favorite_release_user_created
    ON favorite_release(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_favorite_release_album
    ON favorite_release(album_mbid);
