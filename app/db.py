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
    art_id INTEGER,
    FOREIGN KEY(art_id) REFERENCES artwork(id)
);

CREATE TABLE IF NOT EXISTS artists (
    mbid TEXT PRIMARY KEY,
    name TEXT,
    sort_name TEXT,
    bio TEXT,
    image_url TEXT,
    spotify_url TEXT,
    homepage TEXT,
    similar_artists TEXT,
    top_tracks TEXT,
    last_updated REAL
);

CREATE TABLE IF NOT EXISTS artwork (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha1 TEXT UNIQUE NOT NULL,
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
"""

async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db

async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(INIT_SCRIPT)
        await db.commit()
