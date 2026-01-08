import asyncpg
import os
from typing import AsyncGenerator

# Connection pool (initialized on startup)
_pool: asyncpg.Pool = None

# PostgreSQL connection configuration from environment
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "8110"))
DB_USER = os.getenv("DB_USER", "jamarr")
DB_PASS = os.getenv("DB_PASS", "jamarr")
DB_NAME = os.getenv("DB_NAME", "jamarr")


async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Dependency injection for database connections.
    Yields a connection from the pool.
    """
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_db() first.")

    async with _pool.acquire() as conn:
        yield conn


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_db() first.")
    return _pool


async def init_db():
    """
    Initialize the PostgreSQL connection pool and create schema.
    """
    global _pool

    # Create connection pool
    _pool = await asyncpg.create_pool(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        min_size=5,
        max_size=20,
        command_timeout=60,
    )

    # Initialize schema
    async with _pool.acquire() as conn:
        # Enable extensions
        await conn.execute("CREATE EXTENSION IF NOT EXISTS citext")
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

        # Enable slow query logging in development
        if os.getenv("ENV") == "development":
            await conn.execute("SET log_min_duration_statement = 200")

        # Create tables
        await conn.execute("""
            -- Track table with FTS vector
            CREATE TABLE IF NOT EXISTS track (
                id BIGSERIAL PRIMARY KEY,
                path TEXT UNIQUE NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                title TEXT,
                artist TEXT,
                album TEXT,
                album_artist TEXT,
                track_no INTEGER,
                disc_no INTEGER,

                release_date DATE,
                release_type TEXT,
                release_type_raw TEXT,
                release_date_raw TEXT,
                release_date_tag TEXT,
                duration_seconds DOUBLE PRECISION,
                codec TEXT,
                sample_rate_hz INTEGER,
                bit_depth INTEGER,
                bitrate INTEGER,
                channels INTEGER,
                label TEXT,
                artist_mbid TEXT,
                album_artist_mbid TEXT,
                track_mbid TEXT,
                release_track_mbid TEXT,
                release_mbid TEXT,
                release_group_mbid TEXT,
                artwork_id BIGINT,
                size_bytes BIGINT,
                quick_hash BYTEA,
                mtime DOUBLE PRECISION,
                fts_vector tsvector
            );
            
            -- Manual auto-migration for existing DBs
            ALTER TABLE track ADD COLUMN IF NOT EXISTS size_bytes BIGINT;
            ALTER TABLE track ADD COLUMN IF NOT EXISTS quick_hash BYTEA;
            ALTER TABLE track ADD COLUMN IF NOT EXISTS mtime DOUBLE PRECISION;
            
            -- Artist table with citext for case-insensitive name
            CREATE TABLE IF NOT EXISTS artist (
                mbid TEXT PRIMARY KEY,
                name citext,
                sort_name TEXT,
                bio TEXT,
                image_url TEXT,
                image_source TEXT,
                artwork_id BIGINT,
                letter TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            ALTER TABLE artist ADD COLUMN IF NOT EXISTS letter TEXT;
            
            -- Album table
            CREATE TABLE IF NOT EXISTS album (
                mbid TEXT PRIMARY KEY, -- Release ID
                release_group_mbid TEXT, -- Release Group ID
                title TEXT,

                release_date DATE,
                release_type TEXT,
                release_type_raw TEXT,
                artwork_id BIGINT,
                description TEXT,
                peak_chart_position INTEGER,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            
            -- Manual auto-migration for existing DBs
            ALTER TABLE track ADD COLUMN IF NOT EXISTS size_bytes BIGINT;
            ALTER TABLE track ADD COLUMN IF NOT EXISTS quick_hash BYTEA;
            ALTER TABLE track ADD COLUMN IF NOT EXISTS mtime DOUBLE PRECISION;
            ALTER TABLE album ADD COLUMN IF NOT EXISTS description TEXT;
            ALTER TABLE album ADD COLUMN IF NOT EXISTS peak_chart_position INTEGER;
            ALTER TABLE album ADD COLUMN IF NOT EXISTS release_group_mbid TEXT;
            CREATE TABLE IF NOT EXISTS artist_album (
                artist_mbid TEXT,
                album_mbid TEXT,
                type TEXT,
                PRIMARY KEY (artist_mbid, album_mbid),
                FOREIGN KEY(artist_mbid) REFERENCES artist(mbid) ON DELETE CASCADE,
                FOREIGN KEY(album_mbid) REFERENCES album(mbid) ON DELETE CASCADE
            );
            
            -- External links
            CREATE TABLE IF NOT EXISTS external_link (
                id BIGSERIAL PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                type TEXT NOT NULL,
                url TEXT NOT NULL,
                UNIQUE(entity_type, entity_id, type)
            );
            
            -- Track-Artist junction
            CREATE TABLE IF NOT EXISTS track_artist (
                track_id BIGINT,
                artist_mbid TEXT,
                PRIMARY KEY (track_id, artist_mbid),
                FOREIGN KEY(track_id) REFERENCES track(id) ON DELETE CASCADE,
                FOREIGN KEY(artist_mbid) REFERENCES artist(mbid) ON DELETE CASCADE
            );
            
            -- Artwork
            CREATE TABLE IF NOT EXISTS artwork (
                id BIGSERIAL PRIMARY KEY,
                sha1 TEXT UNIQUE NOT NULL,
                type TEXT,
                mime TEXT,
                width INTEGER,
                height INTEGER,
                path_on_disk TEXT,
                filesize_bytes BIGINT,
                image_format TEXT,
                source TEXT,
                source_url TEXT,
                checked_at TIMESTAMPTZ,
                check_errors TEXT
            );
            
            -- Image mapping
            CREATE TABLE IF NOT EXISTS image_map (
                artwork_id BIGINT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                image_type TEXT NOT NULL,
                score DOUBLE PRECISION,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (entity_type, entity_id, image_type),
                FOREIGN KEY(artwork_id) REFERENCES artwork(id) ON DELETE CASCADE
            );
            
            -- Renderers (UPnP devices)
            CREATE TABLE IF NOT EXISTS renderer (
                id BIGSERIAL PRIMARY KEY,
                friendly_name TEXT,
                udn TEXT UNIQUE NOT NULL,
                location_url TEXT,
                ip TEXT,
                control_url TEXT,
                rendering_control_url TEXT,
                device_type TEXT,
                manufacturer TEXT,
                model_name TEXT,
                model_number TEXT,
                serial_number TEXT,
                firmware_version TEXT,
                event_subscription_sid TEXT,
                supports_events BOOLEAN DEFAULT FALSE,
                supports_gapless BOOLEAN DEFAULT FALSE,
                supported_mime_types TEXT,
                icon_url TEXT,
                icon_mime TEXT,
                icon_width INTEGER,
                icon_height INTEGER,
                last_seen_at TIMESTAMPTZ DEFAULT NOW()
            );
            
            -- Client sessions
            CREATE TABLE IF NOT EXISTS client_session (
                client_id TEXT PRIMARY KEY,
                active_renderer_udn TEXT,
                last_seen_at TIMESTAMPTZ DEFAULT NOW()
            );
            
            -- Renderer state
            CREATE TABLE IF NOT EXISTS renderer_state (
                renderer_udn TEXT PRIMARY KEY,
                queue TEXT DEFAULT '[]',
                current_index INTEGER DEFAULT -1,
                position_seconds DOUBLE PRECISION DEFAULT 0,
                is_playing BOOLEAN DEFAULT FALSE,
                transport_state TEXT DEFAULT 'STOPPED',
                volume INTEGER,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            
            -- Playback history
            CREATE TABLE IF NOT EXISTS playback_history (
                id BIGSERIAL PRIMARY KEY,
                track_id BIGINT NOT NULL,
                timestamp TIMESTAMPTZ DEFAULT NOW(),
                client_ip TEXT,
                hostname TEXT,
                client_id TEXT,
                user_id BIGINT,
                FOREIGN KEY(track_id) REFERENCES track(id) ON DELETE CASCADE
            );
            
            -- Users (with citext for username and email)
            CREATE TABLE IF NOT EXISTS "user" (
                id BIGSERIAL PRIMARY KEY,
                username citext UNIQUE NOT NULL,
                email citext UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                last_login_at TIMESTAMPTZ,
                is_active BOOLEAN DEFAULT TRUE,
                accent_color TEXT DEFAULT '#ff006e',
                theme_mode TEXT DEFAULT 'dark',
                lastfm_username TEXT,
                lastfm_session_key TEXT,
                lastfm_enabled BOOLEAN DEFAULT TRUE,
                lastfm_connected_at TIMESTAMPTZ
            );
            
            -- Sessions
            CREATE TABLE IF NOT EXISTS session (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                token TEXT UNIQUE NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                expires_at TIMESTAMPTZ NOT NULL,
                user_agent TEXT,
                ip TEXT,
                FOREIGN KEY(user_id) REFERENCES "user"(id) ON DELETE CASCADE
            );
            
            -- Top tracks
            CREATE TABLE IF NOT EXISTS top_track (
                id BIGSERIAL PRIMARY KEY,
                artist_mbid TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('top', 'single')),
                track_id BIGINT,
                external_name TEXT NOT NULL,
                external_album TEXT,
                external_date TEXT,
                external_duration_ms INTEGER,
                external_mbid TEXT,
                popularity INTEGER,
                rank INTEGER,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                FOREIGN KEY(artist_mbid) REFERENCES artist(mbid) ON DELETE CASCADE,
                FOREIGN KEY(track_id) REFERENCES track(id) ON DELETE SET NULL,
                UNIQUE(artist_mbid, type, external_name, external_album),
                UNIQUE(artist_mbid, type, rank),
                UNIQUE(artist_mbid, type, external_mbid)
            );
            
            -- Similar artists
            CREATE TABLE IF NOT EXISTS similar_artist (
                artist_mbid TEXT NOT NULL,
                similar_artist_name TEXT NOT NULL,
                similar_artist_mbid TEXT,
                rank INTEGER,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (artist_mbid, similar_artist_name),
                FOREIGN KEY(artist_mbid) REFERENCES artist(mbid) ON DELETE CASCADE
            );
            
            -- Artist genres
            CREATE TABLE IF NOT EXISTS artist_genre (
                artist_mbid TEXT NOT NULL,
                genre TEXT NOT NULL,
                count INTEGER DEFAULT 0,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (artist_mbid, genre),
                FOREIGN KEY(artist_mbid) REFERENCES artist(mbid) ON DELETE CASCADE
            );
            
            -- Missing albums
            CREATE TABLE IF NOT EXISTS missing_album (
                id BIGSERIAL PRIMARY KEY,
                artist_mbid TEXT NOT NULL,
                release_group_mbid TEXT NOT NULL,
                title TEXT NOT NULL,
                release_date TEXT,
                primary_type TEXT,
                musicbrainz_url TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(artist_mbid, release_group_mbid),
                FOREIGN KEY(artist_mbid) REFERENCES artist(mbid) ON DELETE CASCADE
            );

            -- Playlists
            CREATE TABLE IF NOT EXISTS playlist (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                is_public     BOOLEAN NOT NULL DEFAULT FALSE,
                updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                FOREIGN KEY (user_id) REFERENCES "user"(id) ON DELETE CASCADE
            );

            -- Playlist Tracks
            CREATE TABLE IF NOT EXISTS playlist_track (
                id BIGSERIAL PRIMARY KEY,
                playlist_id BIGINT NOT NULL,
                track_id BIGINT NOT NULL,
                position INTEGER NOT NULL,
                FOREIGN KEY(playlist_id) REFERENCES playlist(id) ON DELETE CASCADE,
                FOREIGN KEY(track_id) REFERENCES track(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_playlist_track_playlist_pos ON playlist_track(playlist_id, position);

            -- Chart Album table
            CREATE TABLE IF NOT EXISTS chart_album (
                position INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                last_week TEXT,
                peak TEXT,
                weeks TEXT,
                status TEXT,
                release_mbid TEXT,
                release_group_mbid TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_chart_album_rg_mbid ON chart_album(release_group_mbid);
        """)

        # Create indexes
        await conn.execute("""
            -- FTS index
            CREATE INDEX IF NOT EXISTS idx_track_fts ON track USING GIN(fts_vector);
            
            -- Image map index
            CREATE INDEX IF NOT EXISTS idx_image_map_artwork ON image_map(artwork_id);
            
            -- Session indexes
            CREATE INDEX IF NOT EXISTS idx_session_token ON session(token);
            CREATE INDEX IF NOT EXISTS idx_session_user ON session(user_id);
            
            -- Integrity & joins indexes
            CREATE INDEX IF NOT EXISTS idx_track_artwork ON track(artwork_id);
            CREATE INDEX IF NOT EXISTS idx_track_artist_mbid ON track(artist_mbid);
            CREATE INDEX IF NOT EXISTS idx_track_release_mbid ON track(release_mbid);
            CREATE INDEX IF NOT EXISTS idx_track_release_group_mbid ON track(release_group_mbid);
            CREATE INDEX IF NOT EXISTS idx_link_entity ON external_link(entity_type, entity_id);
            
            -- Browsing indexes
            CREATE INDEX IF NOT EXISTS idx_track_nav ON track(artist, album, disc_no, track_no);
            CREATE INDEX IF NOT EXISTS idx_track_album ON track(album, disc_no, track_no);
            CREATE INDEX IF NOT EXISTS idx_artist_name ON artist(name);
            CREATE INDEX IF NOT EXISTS idx_artist_letter ON artist(letter);
            
            -- Maintenance index
            CREATE INDEX IF NOT EXISTS idx_track_updated ON track(updated_at);
            
            -- Top tracks indexes
            CREATE INDEX IF NOT EXISTS idx_top_track_artist ON top_track(artist_mbid, type);
            CREATE INDEX IF NOT EXISTS idx_top_track_track ON top_track(track_id);
            
            -- Similar artist indexes
            CREATE INDEX IF NOT EXISTS idx_similar_artist_main ON similar_artist(artist_mbid);
            CREATE INDEX IF NOT EXISTS idx_similar_artist_related ON similar_artist(similar_artist_mbid);
            
            -- Artist genre index
            CREATE INDEX IF NOT EXISTS idx_artist_genre_artist ON artist_genre(artist_mbid);
            
            -- Missing album index
            CREATE INDEX IF NOT EXISTS idx_missing_album_artist ON missing_album(artist_mbid);
            
            -- Performance optimization indexes
            CREATE INDEX IF NOT EXISTS idx_track_artist_map_mbid ON track_artist(artist_mbid);
            CREATE INDEX IF NOT EXISTS idx_track_artist_map_track ON track_artist(track_id);
            CREATE INDEX IF NOT EXISTS idx_artist_album_map_album ON artist_album(album_mbid);
            CREATE INDEX IF NOT EXISTS idx_artist_album_map_artist_type ON artist_album(artist_mbid, type);
            CREATE INDEX IF NOT EXISTS idx_album_release_group_mbid ON album(release_group_mbid);
            CREATE INDEX IF NOT EXISTS idx_link_entity_type ON external_link(entity_type, entity_id, type);
            CREATE INDEX IF NOT EXISTS idx_playback_history_ts ON playback_history(timestamp);
            CREATE INDEX IF NOT EXISTS idx_playback_history_user_ts ON playback_history(user_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_playback_history_track_ts ON playback_history(track_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_artwork_source ON artwork(source);

            -- Search Optimization Indexes (Trigram)
            CREATE INDEX IF NOT EXISTS idx_artist_name_trgm ON artist USING GIN (name gin_trgm_ops);
        """)

        # Create FTS trigger function
        await conn.execute("""
            CREATE OR REPLACE FUNCTION track_fts_trigger() RETURNS trigger AS $$
            BEGIN
                NEW.fts_vector := 
                    setweight(to_tsvector('english', COALESCE(NEW.title, '')), 'A') ||
                    setweight(to_tsvector('english', COALESCE(NEW.artist, '')), 'B') ||
                    setweight(to_tsvector('english', COALESCE(NEW.album, '')), 'C') ||
                    setweight(to_tsvector('english', COALESCE(NEW.album_artist, '')), 'C');
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)

        # Create FTS trigger (disabled by default for bulk operations)
        await conn.execute("""
            DROP TRIGGER IF EXISTS track_fts_update ON track;
            CREATE TRIGGER track_fts_update 
                BEFORE INSERT OR UPDATE ON track
                FOR EACH ROW EXECUTE FUNCTION track_fts_trigger();
        """)

        # Enable trigger (ensure it is active)
        await conn.execute("ALTER TABLE track ENABLE TRIGGER track_fts_update")

        # Backfill FTS vector if missing
        # This fixes tracks that were imported while the trigger was disabled
        await conn.execute("""
            UPDATE track 
            SET fts_vector = 
                setweight(to_tsvector('english', COALESCE(title, '')), 'A') ||
                setweight(to_tsvector('english', COALESCE(artist, '')), 'B') ||
                setweight(to_tsvector('english', COALESCE(album, '')), 'C') ||
                setweight(to_tsvector('english', COALESCE(album_artist, '')), 'C')
            WHERE fts_vector IS NULL;
        """)

        print("✅ PostgreSQL database initialized successfully")


async def close_db():
    """
    Close the database connection pool.
    """
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def optimize_db():
    """
    Runs database optimization commands (VACUUM, ANALYZE).
    """
    async with _pool.acquire() as conn:
        # VACUUM cannot run inside a transaction block
        # We need to use a separate connection with autocommit
        await conn.execute("VACUUM")
        await conn.execute("ANALYZE")
