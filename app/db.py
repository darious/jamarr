import aiosqlite
import os

DB_PATH = "cache/library.sqlite"

INIT_SCRIPT = """
CREATE TABLE IF NOT EXISTS track (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    updated_at INTEGER, -- mtime of file on disk
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
    artist_mbid TEXT,
    album_artist_mbid TEXT,
    track_mbid TEXT,
    release_track_mbid TEXT,
    release_mbid TEXT,
    release_group_mbid TEXT,
    artwork_id INTEGER,
    FOREIGN KEY(artwork_id) REFERENCES artwork(id)
);

CREATE TABLE IF NOT EXISTS artist (
    mbid TEXT PRIMARY KEY,
    name TEXT,
    sort_name TEXT,
    bio TEXT,
    image_url TEXT,
    artwork_id INTEGER,
    updated_at INTEGER,
    FOREIGN KEY(artwork_id) REFERENCES artwork(id)
);

CREATE TABLE IF NOT EXISTS album (
    mbid TEXT PRIMARY KEY,
    title TEXT,
    release_date TEXT,
    primary_type TEXT,
    secondary_types TEXT,
    artwork_id INTEGER,
    updated_at INTEGER,
    FOREIGN KEY(artwork_id) REFERENCES artwork(id)
);

CREATE TABLE IF NOT EXISTS artist_album (
    artist_mbid TEXT,
    album_mbid TEXT,
    type TEXT, -- 'primary', 'featured', etc.
    PRIMARY KEY (artist_mbid, album_mbid),
    FOREIGN KEY(artist_mbid) REFERENCES artist(mbid),
    FOREIGN KEY(album_mbid) REFERENCES album(mbid)
);

CREATE TABLE IF NOT EXISTS external_link (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL, -- 'artist', 'album'
    entity_id TEXT NOT NULL, -- mbid
    type TEXT NOT NULL, -- 'spotify', 'tidal', 'qobuz', 'wikipedia', 'homepage'
    url TEXT NOT NULL,
    UNIQUE(entity_type, entity_id, type)
);

CREATE TABLE IF NOT EXISTS track_artist (
    track_id INTEGER,
    artist_mbid TEXT,
    PRIMARY KEY (track_id, artist_mbid),
    FOREIGN KEY(track_id) REFERENCES track(id),
    FOREIGN KEY(artist_mbid) REFERENCES artist(mbid)
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
    source TEXT,
    source_url TEXT,
    checked_at INTEGER,
    check_errors TEXT
);

CREATE TABLE IF NOT EXISTS image_map (
    artwork_id INTEGER NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    image_type TEXT NOT NULL,
    score REAL,
    created_at INTEGER DEFAULT (CAST(strftime('%s','now') AS INTEGER)),
    PRIMARY KEY (entity_type, entity_id, image_type),
    FOREIGN KEY(artwork_id) REFERENCES artwork(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_image_map_artwork ON image_map(artwork_id);

CREATE TABLE IF NOT EXISTS renderer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    supports_events BOOLEAN DEFAULT 0,
    supports_gapless BOOLEAN DEFAULT 0,
    last_seen_at INTEGER
);

CREATE TABLE IF NOT EXISTS client_session (
    client_id TEXT PRIMARY KEY,
    active_renderer_udn TEXT,
    last_seen_at INTEGER DEFAULT (CAST(strftime('%s','now') AS INTEGER))
);

CREATE TABLE IF NOT EXISTS renderer_state (
    renderer_udn TEXT PRIMARY KEY,
    queue TEXT DEFAULT '[]',
    current_index INTEGER DEFAULT -1,
    position_seconds REAL DEFAULT 0,
    is_playing BOOLEAN DEFAULT 0,
    transport_state TEXT DEFAULT 'STOPPED',
    volume INTEGER,
    updated_at INTEGER DEFAULT (CAST(strftime('%s','now') AS INTEGER))
);

CREATE TABLE IF NOT EXISTS playback_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER NOT NULL,
    timestamp INTEGER DEFAULT (CAST(strftime('%s','now') AS INTEGER)),
    client_ip TEXT,
    hostname TEXT,
    client_id TEXT,
    user_id INTEGER,
    FOREIGN KEY(track_id) REFERENCES track(id)
);

CREATE TABLE IF NOT EXISTS user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    created_at INTEGER DEFAULT (CAST(strftime('%s','now') AS INTEGER)),
    last_login_at INTEGER,
    is_active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS session (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token TEXT UNIQUE NOT NULL,
    created_at INTEGER DEFAULT (CAST(strftime('%s','now') AS INTEGER)),
    expires_at INTEGER NOT NULL,
    user_agent TEXT,
    ip TEXT,
    FOREIGN KEY(user_id) REFERENCES user(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_session_token ON session(token);
CREATE INDEX IF NOT EXISTS idx_session_user ON session(user_id);

-- Indexes for integrity & joins
CREATE INDEX IF NOT EXISTS idx_track_artwork ON track(artwork_id);
CREATE INDEX IF NOT EXISTS idx_track_artist_mbid ON track(artist_mbid);
CREATE INDEX IF NOT EXISTS idx_link_entity ON external_link(entity_type, entity_id);

-- Indexes for browsing (artist -> album -> tracks)
CREATE INDEX IF NOT EXISTS idx_track_nav ON track(artist COLLATE NOCASE, album COLLATE NOCASE, disc_no, track_no);
CREATE INDEX IF NOT EXISTS idx_track_album ON track(album COLLATE NOCASE, disc_no, track_no);
CREATE INDEX IF NOT EXISTS idx_artist_name ON artist(name COLLATE NOCASE);

-- Index for maintenance / library updates
CREATE INDEX IF NOT EXISTS idx_track_updated ON track(updated_at);

-- FTS5 virtual table for full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS track_fts USING fts5(
    title,
    artist,
    album,
    album_artist,
    content=track,
    content_rowid=id
);

-- Triggers to keep FTS5 in sync with track table
CREATE TRIGGER IF NOT EXISTS track_fts_insert AFTER INSERT ON track BEGIN
    INSERT INTO track_fts(rowid, title, artist, album, album_artist)
    VALUES (new.id, new.title, new.artist, new.album, new.album_artist);
END;

CREATE TRIGGER IF NOT EXISTS track_fts_delete AFTER DELETE ON track BEGIN
    DELETE FROM track_fts WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS track_fts_update AFTER UPDATE ON track BEGIN
    DELETE FROM track_fts WHERE rowid = old.id;
    INSERT INTO track_fts(rowid, title, artist, album, album_artist)
    VALUES (new.id, new.title, new.artist, new.album, new.album_artist);
END;

CREATE TABLE IF NOT EXISTS top_track (
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
    updated_at INTEGER,
    FOREIGN KEY(artist_mbid) REFERENCES artist(mbid),
    FOREIGN KEY(track_id) REFERENCES track(id) ON DELETE SET NULL,
    UNIQUE(artist_mbid, type, external_name, external_album)
);

CREATE INDEX IF NOT EXISTS idx_top_track_artist ON top_track(artist_mbid, type);
CREATE INDEX IF NOT EXISTS idx_top_track_track ON top_track(track_id);

CREATE TABLE IF NOT EXISTS similar_artist (
    artist_mbid TEXT NOT NULL,
    similar_artist_name TEXT NOT NULL,
    similar_artist_mbid TEXT,
    rank INTEGER,
    updated_at INTEGER,
    PRIMARY KEY (artist_mbid, similar_artist_name),
    FOREIGN KEY(artist_mbid) REFERENCES artist(mbid),
    FOREIGN KEY(similar_artist_mbid) REFERENCES artist(mbid) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_similar_artist_main ON similar_artist(artist_mbid);
CREATE INDEX IF NOT EXISTS idx_similar_artist_related ON similar_artist(similar_artist_mbid);

CREATE TABLE IF NOT EXISTS artist_genre (
    artist_mbid TEXT NOT NULL,
    genre TEXT NOT NULL,
    count INTEGER DEFAULT 0,
    updated_at INTEGER,
    PRIMARY KEY (artist_mbid, genre),
    FOREIGN KEY(artist_mbid) REFERENCES artist(mbid)
);

CREATE INDEX IF NOT EXISTS idx_artist_genre_artist ON artist_genre(artist_mbid);

CREATE TABLE IF NOT EXISTS missing_album (
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
    updated_at INTEGER,
    UNIQUE(artist_mbid, release_group_mbid),
    FOREIGN KEY(artist_mbid) REFERENCES artist(mbid)
);

CREATE INDEX IF NOT EXISTS idx_missing_album_artist ON missing_album(artist_mbid);

-- Performance Optimizations
CREATE INDEX IF NOT EXISTS idx_track_artist_map_mbid ON track_artist(artist_mbid);
CREATE INDEX IF NOT EXISTS idx_artist_album_map_album ON artist_album(album_mbid);
CREATE INDEX IF NOT EXISTS idx_link_entity_type ON external_link(entity_type, entity_id, type);
CREATE INDEX IF NOT EXISTS idx_playback_history_ts ON playback_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_playback_history_user_ts ON playback_history(user_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_playback_history_track_ts ON playback_history(track_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_track_missing_art ON track(id) WHERE artwork_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_artist_missing_image ON artist(mbid) WHERE image_url IS NULL OR image_url = '';
CREATE INDEX IF NOT EXISTS idx_artwork_source ON artwork(source);
"""

async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA temp_store=MEMORY")

        await db.execute("PRAGMA busy_timeout=5000")
        db.row_factory = aiosqlite.Row
        yield db

async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        # Enable WAL mode for better concurrency
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA temp_store=MEMORY")
        await db.execute("PRAGMA busy_timeout=5000")
        
        # 1. Run Init Script to create new tables if they don't exist
        await db.executescript(INIT_SCRIPT)
        
        # 2. Check for legacy tables and migrate if found
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tracks'") as cursor:
            legacy_exists = await cursor.fetchone()
            
        if legacy_exists:
            print("Migrating database from v1 (plural) to v2 (singular)...")
            await _migrate_v1_to_v2(db)
            
        # Consolidate artwork paths into unified cache/art/{sha1[:2]}/{sha1}
        try:
            await _unify_artwork_cache(db)
        except Exception:
            pass
            
        await db.commit()

async def _migrate_v1_to_v2(db):
    """
    Migrate data from old plural tables to new singular tables.
    Standardizes timestamps to INTEGER (seconds).
    Renames columns (mb_* -> *_mbid, etc).
    """
    import time
    
    await db.execute("PRAGMA foreign_keys=OFF")
    
    existing_tables = []
    async with db.execute("SELECT name FROM sqlite_master WHERE type='table'") as cursor:
        rows = await cursor.fetchall()
        existing_tables = [r[0] for r in rows]

    # Helper to rename if exists
    async def rename_legacy(name):
        legacy_name = f"legacy_{name}"
        if name in existing_tables and legacy_name not in existing_tables:
            await db.execute(f"ALTER TABLE {name} RENAME TO {legacy_name}")
            return True
        return False
    
    # We will rename tables to legacy_*, run INIT, then copy back.
    # Note: external_links -> legacy_external_links
    
    tables_to_migrate = [ 
        "tracks", "artists", "albums", "artist_albums", "external_links", 
        "track_artists", "artwork", "image_mapping", "renderers", 
        "client_sessions", "renderer_states", "playback_history", 
        "users", "sessions", "media_quality_issues", "similar_artists",
        "artist_genres", "missing_albums", "tracks_top"
    ]
    
    # If tracks exists, we assume migration needed.
    if "tracks" in existing_tables:
        
        # 1. Rename ALL matching old tables
        # If 'artwork' exists, rename it. 
        # Note: INIT_SCRIPT assumes new names.
        
        for tbl in tables_to_migrate:
            await rename_legacy(tbl)

        # 2. Rerun INIT_SCRIPT to ensure NEW tables are created fresh
        await db.executescript(INIT_SCRIPT)
        
        # 3. Migrate Data
        
        # Artwork
        if "legacy_artwork" in existing_tables:
            await db.execute("""
                INSERT INTO artwork (id, sha1, type, mime, width, height, path_on_disk, 
                                   filesize_bytes, image_format, source, source_url, checked_at, check_errors)
                SELECT id, sha1, type, mime, width, height, path_on_disk, 
                       filesize_bytes, image_format, source, source_url, CAST(checked_at AS INTEGER), check_errors
                FROM legacy_artwork
            """)

        # Users
        if "legacy_users" in existing_tables:
            await db.execute("""
                INSERT INTO user (id, username, email, password_hash, display_name, created_at, last_login_at, is_active)
                SELECT id, username, email, password_hash, display_name, 
                       CAST(strftime('%s', created_at) AS INTEGER), 
                       CAST(strftime('%s', last_login) AS INTEGER), 
                       is_active
                FROM legacy_users
            """)
        
        # Artists
        if "legacy_artists" in existing_tables:
            await db.execute("""
                INSERT INTO artist (mbid, name, sort_name, bio, image_url, artwork_id, updated_at)
                SELECT mbid, name, sort_name, bio, image_url, art_id, CAST(last_updated AS INTEGER)
                FROM legacy_artists
            """)

        # Albums
        if "legacy_albums" in existing_tables:
            await db.execute("""
                INSERT INTO album (mbid, title, release_date, primary_type, secondary_types, artwork_id, updated_at)
                SELECT mbid, title, release_date, primary_type, secondary_types, art_id, CAST(last_updated AS INTEGER)
                FROM legacy_albums
            """)

        # Tracks
        if "legacy_tracks" in existing_tables:
            await db.execute("""
                INSERT INTO track (id, path, updated_at, title, artist, album, album_artist, 
                                 track_no, disc_no, date, genre, duration_seconds, codec, 
                                 sample_rate_hz, bit_depth, bitrate, channels, label, 
                                 artist_mbid, album_artist_mbid, track_mbid, 
                                 release_track_mbid, release_mbid, release_group_mbid, artwork_id)
                SELECT id, path, CAST(mtime AS INTEGER), title, artist, album, album_artist, 
                       track_no, disc_no, date, genre, duration_seconds, codec, 
                       sample_rate_hz, bit_depth, bitrate, channels, label, 
                       mb_artist_id, mb_album_artist_id, mb_track_id, 
                       mb_release_track_id, mb_release_id, mb_release_group_id, art_id
                FROM legacy_tracks
            """)

        # Artist Albums
        if "legacy_artist_albums" in existing_tables:
            await db.execute("""
                INSERT INTO artist_album (artist_mbid, album_mbid, type)
                SELECT artist_mbid, album_mbid, type FROM legacy_artist_albums
            """)
        
        if "legacy_track_artists" in existing_tables:
            await db.execute("""
                INSERT INTO track_artist (track_id, artist_mbid)
                SELECT track_id, mbid FROM legacy_track_artists
            """)
        
        # External Links
        if "legacy_external_links" in existing_tables:
            await db.execute("""
                INSERT INTO external_link (id, entity_type, entity_id, type, url)
                SELECT id, entity_type, entity_id, type, url FROM legacy_external_links
            """)

        # Image Mapping -> Image Map
        if "legacy_image_mapping" in existing_tables:
            await db.execute("""
                INSERT INTO image_map (artwork_id, entity_type, entity_id, image_type, score, created_at)
                SELECT artwork_id, entity_type, entity_id, image_type, score, CAST(created_at AS INTEGER)
                FROM legacy_image_mapping
            """)

        # Top Tracks
        if "legacy_tracks_top" in existing_tables:
             await db.execute("""
                INSERT INTO top_track (id, artist_mbid, type, track_id, external_name, external_album, 
                                     external_date, external_duration_ms, external_mbid, popularity, rank, updated_at)
                SELECT id, artist_mbid, type, track_id, external_name, external_album, 
                       external_date, external_duration_ms, external_mbid, popularity, rank, CAST(last_updated AS INTEGER)
                FROM legacy_tracks_top
             """)

        # Similar Artists
        if "legacy_similar_artists" in existing_tables:
             await db.execute("""
                INSERT INTO similar_artist (artist_mbid, similar_artist_name, similar_artist_mbid, rank, updated_at)
                SELECT artist_mbid, similar_artist_name, similar_artist_mbid, rank, CAST(last_updated AS INTEGER)
                FROM legacy_similar_artists
             """)
        
        # Artist Genres
        if "legacy_artist_genres" in existing_tables:
             await db.execute("""
                INSERT INTO artist_genre (artist_mbid, genre, count, updated_at)
                SELECT artist_mbid, genre, count, CAST(last_updated AS INTEGER)
                FROM legacy_artist_genres
             """)

        # Missing Albums
        if "legacy_missing_albums" in existing_tables:
             await db.execute("""
                INSERT INTO missing_album (id, artist_mbid, release_group_mbid, title, release_date, 
                                         primary_type, image_url, musicbrainz_url, tidal_url, qobuz_url, updated_at)
                SELECT id, artist_mbid, release_group_mbid, title, release_date, 
                       primary_type, image_url, musicbrainz_url, tidal_url, qobuz_url, CAST(last_updated AS INTEGER)
                FROM legacy_missing_albums
             """)

        # Playback History (if needed, map to proper table names if they changed)
        if "legacy_playback_history" in existing_tables:
             # Assuming structure same just table name changed
             await db.execute("""
                INSERT INTO playback_history (id, track_id, timestamp, client_ip, hostname, client_id, user_id)
                SELECT id, track_id, CAST(strftime('%s', timestamp) AS INTEGER), client_ip, hostname, client_id, user_id
                FROM legacy_playback_history
             """)
             
        # Cleanup
        for tbl in tables_to_migrate:
            legacy_name = f"legacy_{tbl}"
            await db.execute(f"DROP TABLE IF EXISTS {legacy_name}")
        
        # Drop legacy_artwork if not covered loop
        await db.execute("DROP TABLE IF EXISTS legacy_artwork")

    await db.execute("PRAGMA foreign_keys=ON")


async def _unify_artwork_cache(db):
    """
    Move legacy artwork files (artist/album folders) into unified cache/art/{sha1[:2]}/{sha1}
    and update path_on_disk. Leaves rows intact if files are missing.
    """
    import os
    import shutil

    async with db.execute("SELECT id, sha1, path_on_disk FROM artwork") as cursor:
        rows = await cursor.fetchall()

    for row in rows:
        artwork_id = row["id"]
        sha1 = row["sha1"]
        current_path = row["path_on_disk"]

        bucket = sha1[:2]
        unified_path = os.path.join("cache/art", bucket, sha1)

        candidates = [
            current_path,
            os.path.join("cache/art/artistthumb", bucket, sha1),
            os.path.join("cache/art/artist", bucket, sha1),
            os.path.join("cache/art/album", bucket, sha1),
        ]

        src_path = None
        for cand in candidates:
            if cand and os.path.exists(cand):
                src_path = cand
                break

        if src_path and os.path.abspath(src_path) != os.path.abspath(unified_path):
            os.makedirs(os.path.dirname(unified_path), exist_ok=True)
            try:
                shutil.move(src_path, unified_path)
            except Exception:
                try:
                    shutil.copyfile(src_path, unified_path)
                except Exception:
                    pass

        # Always normalize path_on_disk to the unified path, even if the file is missing.
        await db.execute(
            "UPDATE artwork SET path_on_disk=?, type=NULL WHERE id=?",
            (unified_path, artwork_id),
        )

async def optimize_db():
    """
    Runs database optimization commands (VACUUM, ANALYZE).
    This can take a while and might lock the DB.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # VACUUM rebuilds the DB file, repacking it into a minimal amount of disk space.
        await db.execute("VACUUM")
        # ANALYZE gathers statistics about indices to help the query planner.
        await db.execute("ANALYZE")
        # PRAGMA optimize is also good practice
        await db.execute("PRAGMA optimize")

