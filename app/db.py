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
    art_id INTEGER,
    FOREIGN KEY(art_id) REFERENCES artwork(id)
);

CREATE TABLE IF NOT EXISTS track_artists (
    track_id INTEGER,
    mbid TEXT,
    PRIMARY KEY (track_id, mbid),
    FOREIGN KEY(track_id) REFERENCES tracks(id),
    FOREIGN KEY(mbid) REFERENCES artists(mbid)
);

CREATE TABLE IF NOT EXISTS artists (
    mbid TEXT PRIMARY KEY,
    name TEXT,
    sort_name TEXT,
    bio TEXT,
    image_url TEXT,
    art_id INTEGER,
    spotify_url TEXT,
    homepage TEXT,
    similar_artists TEXT,
    top_tracks TEXT,
    singles TEXT,
    last_updated REAL,
    wikipedia_url TEXT,
    qobuz_url TEXT,
    musicbrainz_url TEXT,
    FOREIGN KEY(art_id) REFERENCES artwork(id)
);

CREATE TABLE IF NOT EXISTS artwork (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha1 TEXT UNIQUE NOT NULL,
    type TEXT,
    mime TEXT,
    width INTEGER,
    height INTEGER,
    path_on_disk TEXT
);

CREATE TABLE IF NOT EXISTS renderers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    friendly_name TEXT,
    udn TEXT UNIQUE NOT NULL,
    location_url TEXT,
    last_seen REAL
);

-- Indexes for integrity & joins
CREATE INDEX IF NOT EXISTS idx_tracks_art_id ON tracks(art_id);
CREATE INDEX IF NOT EXISTS idx_tracks_mb_artist_id ON tracks(mb_artist_id);

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
            "ALTER TABLE artists ADD COLUMN musicbrainz_url TEXT",
            "ALTER TABLE artists ADD COLUMN art_id INTEGER REFERENCES artwork(id)",
            "ALTER TABLE artists ADD COLUMN singles TEXT",
            "ALTER TABLE tracks ADD COLUMN mb_release_id TEXT"
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

        # Playback State (Single row enforced) - DEPRECATED in favor of renderer_states
        # Kept for backward compat or migration if needed, but we will use renderer_states now.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS playback_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                queue TEXT DEFAULT '[]',
                current_index INTEGER DEFAULT 0,
                position_seconds REAL DEFAULT 0,
                is_playing BOOLEAN DEFAULT 0
            )
        """)
        
        # Ensure the single row exists
        await db.execute("INSERT OR IGNORE INTO playback_state (id) VALUES (1)")
        
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
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Playback History
        await db.execute("""
            CREATE TABLE IF NOT EXISTS playback_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id INTEGER NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                client_ip TEXT,
                hostname TEXT,
                FOREIGN KEY(track_id) REFERENCES tracks(id)
            )
        """)
        
        # Migration: Add hostname column if it doesn't exist
        try:
            await db.execute("ALTER TABLE playback_history ADD COLUMN hostname TEXT")
            await db.commit()
        except Exception:
            pass  # Column likely exists

        await db.commit()
