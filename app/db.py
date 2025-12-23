import aiosqlite
import os

DB_PATH = "cache/library.sqlite"

INIT_SCRIPT = """
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    mtime REAL,
    title TEXT,
    artist TEXT,
    album TEXT,
    album_artist TEXT,
    track_no INTEGER,
    disc_no INTEGER,
    date TEXT,
    genre TEXT,
    duration_seconds REAL,
    codec TEXT,
    sample_rate_hz INTEGER,
    bit_depth INTEGER,
    bitrate INTEGER,
    channels INTEGER,
    label TEXT,
    mb_artist_id TEXT,
    mb_album_artist_id TEXT,
    mb_track_id TEXT,
    mb_release_track_id TEXT,
    mb_release_id TEXT,
    mb_release_group_id TEXT,
    art_id INTEGER,
    FOREIGN KEY(art_id) REFERENCES artwork(id)
);

CREATE TABLE IF NOT EXISTS artists (
    mbid TEXT PRIMARY KEY,
    name TEXT,
    sort_name TEXT,
    bio TEXT,
    image_url TEXT,
    art_id INTEGER,
    last_updated REAL,
    -- Normalized data moved to linked tables
    FOREIGN KEY(art_id) REFERENCES artwork(id)
);

CREATE TABLE IF NOT EXISTS albums (
    mbid TEXT PRIMARY KEY,
    title TEXT,
    release_date TEXT,
    primary_type TEXT,
    secondary_types TEXT,
    art_id INTEGER,
    last_updated REAL,
    FOREIGN KEY(art_id) REFERENCES artwork(id)
);

CREATE TABLE IF NOT EXISTS artist_albums (
    artist_mbid TEXT,
    album_mbid TEXT,
    type TEXT, -- 'primary', 'featured', etc.
    PRIMARY KEY (artist_mbid, album_mbid),
    FOREIGN KEY(artist_mbid) REFERENCES artists(mbid),
    FOREIGN KEY(album_mbid) REFERENCES albums(mbid)
);

CREATE TABLE IF NOT EXISTS external_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL, -- 'artist', 'album'
    entity_id TEXT NOT NULL, -- mbid
    type TEXT NOT NULL, -- 'spotify', 'tidal', 'qobuz', 'wikipedia', 'homepage'
    url TEXT NOT NULL,
    UNIQUE(entity_type, entity_id, type)
);

CREATE TABLE IF NOT EXISTS track_artists (
    track_id INTEGER,
    mbid TEXT,
    PRIMARY KEY (track_id, mbid),
    FOREIGN KEY(track_id) REFERENCES tracks(id),
    FOREIGN KEY(mbid) REFERENCES artists(mbid)
);

CREATE TABLE IF NOT EXISTS artwork (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha1 TEXT UNIQUE NOT NULL,
    type TEXT,
    mime TEXT,
    width INTEGER,
    height INTEGER,
    path_on_disk TEXT,
    filesize_bytes INTEGER,
    image_format TEXT,
    checked_at REAL,
    check_errors TEXT
);

CREATE TABLE IF NOT EXISTS renderers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    friendly_name TEXT,
    udn TEXT UNIQUE NOT NULL,
    location_url TEXT,
    ip TEXT,
    control_url TEXT,
    rendering_control_url TEXT,
    last_seen REAL
);

CREATE TABLE IF NOT EXISTS client_sessions (
    client_id TEXT PRIMARY KEY,
    active_renderer_udn TEXT,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS renderer_states (
    renderer_udn TEXT PRIMARY KEY,
    queue TEXT DEFAULT '[]',
    current_index INTEGER DEFAULT -1,
    position_seconds REAL DEFAULT 0,
    is_playing BOOLEAN DEFAULT 0,
    transport_state TEXT DEFAULT 'STOPPED',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS playback_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    client_ip TEXT,
    hostname TEXT,
    client_id TEXT,
    user_id INTEGER,
    FOREIGN KEY(track_id) REFERENCES tracks(id)
);

CREATE TABLE IF NOT EXISTS media_quality_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    issue_code TEXT NOT NULL,
    details TEXT,
    created_at REAL DEFAULT (strftime('%s','now')),
    resolved_at REAL
);

CREATE INDEX IF NOT EXISTS idx_media_quality_open ON media_quality_issues(entity_type, issue_code) WHERE resolved_at IS NULL;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_login DATETIME,
    is_active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token TEXT UNIQUE NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    user_agent TEXT,
    ip TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

-- Indexes for integrity & joins
CREATE INDEX IF NOT EXISTS idx_tracks_art_id ON tracks(art_id);
CREATE INDEX IF NOT EXISTS idx_tracks_mb_artist_id ON tracks(mb_artist_id);
CREATE INDEX IF NOT EXISTS idx_links_entity ON external_links(entity_type, entity_id);

-- Indexes for browsing (artist → album → tracks)
CREATE INDEX IF NOT EXISTS idx_tracks_artist_album ON tracks(artist COLLATE NOCASE, album COLLATE NOCASE, disc_no, track_no);
CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album COLLATE NOCASE, disc_no, track_no);
CREATE INDEX IF NOT EXISTS idx_artists_name ON artists(name COLLATE NOCASE);

-- Index for maintenance / library updates
CREATE INDEX IF NOT EXISTS idx_tracks_mtime ON tracks(mtime);

-- FTS5 virtual table for full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts USING fts5(
    title,
    artist,
    album,
    album_artist,
    content=tracks,
    content_rowid=id
);

-- Triggers to keep FTS5 in sync with tracks table
CREATE TRIGGER IF NOT EXISTS tracks_fts_insert AFTER INSERT ON tracks BEGIN
    INSERT INTO tracks_fts(rowid, title, artist, album, album_artist)
    VALUES (new.id, new.title, new.artist, new.album, new.album_artist);
END;

CREATE TRIGGER IF NOT EXISTS tracks_fts_delete AFTER DELETE ON tracks BEGIN
    DELETE FROM tracks_fts WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS tracks_fts_update AFTER UPDATE ON tracks BEGIN
    DELETE FROM tracks_fts WHERE rowid = old.id;
    INSERT INTO tracks_fts(rowid, title, artist, album, album_artist)
    VALUES (new.id, new.title, new.artist, new.album, new.album_artist);
END;
"""

async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db

async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        # Enable WAL mode for better concurrency
        await db.execute("PRAGMA journal_mode=WAL")
        
        await db.executescript(INIT_SCRIPT)
        
        # Migrations for existing DBs
        migrations = [
            "ALTER TABLE artists ADD COLUMN wikipedia_url TEXT",
            "ALTER TABLE artists ADD COLUMN qobuz_url TEXT",
            "ALTER TABLE artists ADD COLUMN tidal_url TEXT",
            "ALTER TABLE artists ADD COLUMN musicbrainz_url TEXT",
            "ALTER TABLE artists ADD COLUMN art_id INTEGER REFERENCES artwork(id)",
            "ALTER TABLE artists ADD COLUMN singles TEXT",
            "ALTER TABLE artists ADD COLUMN albums TEXT",
            "ALTER TABLE tracks ADD COLUMN mb_release_id TEXT",
            "ALTER TABLE tracks ADD COLUMN mb_release_group_id TEXT",
            "ALTER TABLE artwork ADD COLUMN path_on_disk TEXT",
            "ALTER TABLE artwork ADD COLUMN filesize_bytes INTEGER",
            "ALTER TABLE artwork ADD COLUMN image_format TEXT",
            "ALTER TABLE artwork ADD COLUMN checked_at REAL",
            "ALTER TABLE artwork ADD COLUMN check_errors TEXT",
            # Normalization Migration
            """CREATE TABLE IF NOT EXISTS albums (
                mbid TEXT PRIMARY KEY,
                title TEXT,
                release_date TEXT,
                primary_type TEXT,
                secondary_types TEXT,
                art_id INTEGER,
                last_updated REAL,
                FOREIGN KEY(art_id) REFERENCES artwork(id)
            )""",
            """CREATE TABLE IF NOT EXISTS artist_albums (
                artist_mbid TEXT,
                album_mbid TEXT,
                type TEXT,
                PRIMARY KEY (artist_mbid, album_mbid),
                FOREIGN KEY(artist_mbid) REFERENCES artists(mbid),
                FOREIGN KEY(album_mbid) REFERENCES albums(mbid)
            )""",
            """CREATE TABLE IF NOT EXISTS external_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                type TEXT NOT NULL,
                url TEXT NOT NULL,
                UNIQUE(entity_type, entity_id, type)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_links_entity ON external_links(entity_type, entity_id)",
            # Top Tracks & Singles table
            """CREATE TABLE IF NOT EXISTS tracks_top (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist_mbid TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('top', 'single')),
                track_id INTEGER,
                external_name TEXT NOT NULL,
                external_album TEXT,
                external_date TEXT,
                external_duration_ms INTEGER,
                external_mbid TEXT,
                popularity INTEGER,
                rank INTEGER,
                last_updated REAL,
                FOREIGN KEY(artist_mbid) REFERENCES artists(mbid),
                FOREIGN KEY(track_id) REFERENCES tracks(id) ON DELETE SET NULL,
                UNIQUE(artist_mbid, type, external_name, external_album)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_tracks_top_artist ON tracks_top(artist_mbid, type)",
            "CREATE INDEX IF NOT EXISTS idx_tracks_top_track ON tracks_top(track_id)",
            # Similar Artists table
            """CREATE TABLE IF NOT EXISTS similar_artists (
                artist_mbid TEXT NOT NULL,
                similar_artist_name TEXT NOT NULL,
                similar_artist_mbid TEXT,
                rank INTEGER,
                last_updated REAL,
                PRIMARY KEY (artist_mbid, similar_artist_name),
                FOREIGN KEY(artist_mbid) REFERENCES artists(mbid),
                FOREIGN KEY(similar_artist_mbid) REFERENCES artists(mbid) ON DELETE SET NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_similar_artists_artist ON similar_artists(artist_mbid)",
            "CREATE INDEX IF NOT EXISTS idx_similar_artists_similar ON similar_artists(similar_artist_mbid)"
            "CREATE INDEX IF NOT EXISTS idx_similar_artists_artist ON similar_artists(artist_mbid)",
            "CREATE INDEX IF NOT EXISTS idx_similar_artists_similar ON similar_artists(similar_artist_mbid)",
            # Missing Albums table
            """CREATE TABLE IF NOT EXISTS missing_albums (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist_mbid TEXT NOT NULL,
                release_group_mbid TEXT NOT NULL,
                title TEXT NOT NULL,
                release_date TEXT,
                primary_type TEXT,
                image_url TEXT,
                musicbrainz_url TEXT,
                tidal_url TEXT,
                qobuz_url TEXT,
                last_updated REAL,
                UNIQUE(artist_mbid, release_group_mbid),
                FOREIGN KEY(artist_mbid) REFERENCES artists(mbid)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_missing_albums_artist ON missing_albums(artist_mbid)",
            """CREATE TABLE IF NOT EXISTS media_quality_issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                issue_code TEXT NOT NULL,
                details TEXT,
                created_at REAL DEFAULT (strftime('%s','now')),
                resolved_at REAL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_media_quality_open ON media_quality_issues(entity_type, issue_code) WHERE resolved_at IS NULL"
        ]
        
        for sql in migrations:
            try:
                await db.execute(sql)
            except Exception:
                pass # Column likely exists
            
        try:
             await db.execute("ALTER TABLE artwork ADD COLUMN type TEXT")
        except Exception:
            pass # Column likely exists

        # Migration: Add renderer columns
        for col in ["control_url", "rendering_control_url", "ip"]:
             try:
                 await db.execute(f"ALTER TABLE renderers ADD COLUMN {col} TEXT")
             except:
                 pass

        # Playback State (Single row enforced) - DEPRECATED in favor of renderer_states
        # Kept for backward compat or migration if needed, but we will use renderer_states now.
        # await db.execute("""
        #     CREATE TABLE IF NOT EXISTS playback_state (
        #         id INTEGER PRIMARY KEY CHECK (id = 1),
        #         queue TEXT DEFAULT '[]',
        #         current_index INTEGER DEFAULT 0,
        #         position_seconds REAL DEFAULT 0,
        #         is_playing BOOLEAN DEFAULT 0
        #     )
        # """)
        
        # Ensure the single row exists
        # await db.execute("INSERT OR IGNORE INTO playback_state (id) VALUES (1)")
        
        # --- Multi-User & Renderer State Tables ---
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS client_sessions (
                client_id TEXT PRIMARY KEY,
                active_renderer_udn TEXT,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS renderer_states (
                renderer_udn TEXT PRIMARY KEY,
                queue TEXT DEFAULT '[]',
                current_index INTEGER DEFAULT -1,
                position_seconds REAL DEFAULT 0,
                is_playing BOOLEAN DEFAULT 0,
                transport_state TEXT DEFAULT 'STOPPED',
                volume INTEGER,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migration: Add transport_state if missing
        try:
             await db.execute("ALTER TABLE renderer_states ADD COLUMN transport_state TEXT")
             await db.commit()
        except:
             pass

        # Migration: Add volume if missing
        try:
             await db.execute("ALTER TABLE renderer_states ADD COLUMN volume INTEGER")
             await db.commit()
        except:
             pass

        # Playback History
        await db.execute("""
            CREATE TABLE IF NOT EXISTS playback_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id INTEGER NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                client_ip TEXT,
                hostname TEXT,
                client_id TEXT,
                user_id INTEGER,
                FOREIGN KEY(track_id) REFERENCES tracks(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_login DATETIME,
                is_active BOOLEAN DEFAULT 1
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token TEXT UNIQUE NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                user_agent TEXT,
                ip TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
        
        # Migration: Add hostname column if it doesn't exist
        try:
            await db.execute("ALTER TABLE playback_history ADD COLUMN hostname TEXT")
            await db.commit()
        except Exception:
            pass  # Column likely exists
        try:
            await db.execute("ALTER TABLE playback_history ADD COLUMN client_id TEXT")
            await db.commit()
        except Exception:
            pass  # Column likely exists
        try:
            await db.execute("ALTER TABLE playback_history ADD COLUMN user_id INTEGER")
            await db.commit()
        except Exception:
            pass  # Column likely exists

        # --- Cleanup Migrations (Normalization) ---
        # Dropping legacy columns from artists table
        legacy_cols = ["spotify_url", "homepage", "wikipedia_url", "qobuz_url", "tidal_url", "musicbrainz_url", "singles", "albums"]
        for col in legacy_cols:
            try:
                await db.execute(f"ALTER TABLE artists DROP COLUMN {col}")
            except Exception:
                pass # Column likely already dropped or sqlite version too old (requires 3.35+)
        
        # Drop deprecated playback_state table
        await db.execute("DROP TABLE IF EXISTS playback_state")
        
        await db.commit()
