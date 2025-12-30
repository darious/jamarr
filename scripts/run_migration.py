import asyncio
import sys

# Add root to path so we can import app
sys.path.append("/app")

from app.db import init_db, get_pool, close_db

SQL = """
-- Create playlists table
CREATE TABLE IF NOT EXISTS playlists (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL,
    name          TEXT NOT NULL,
    description   TEXT,
    is_public     BOOLEAN NOT NULL DEFAULT FALSE,
    last_updated  DOUBLE PRECISION NOT NULL,

    FOREIGN KEY (user_id) REFERENCES "user"(id) ON DELETE CASCADE
);

-- Create playlist_tracks table
-- track_id is NOT unique per playlist to allow duplicates as requested
CREATE TABLE IF NOT EXISTS playlist_tracks (
    id           BIGSERIAL PRIMARY KEY,
    playlist_id  BIGINT NOT NULL,
    track_id     BIGINT NOT NULL,
    position     INTEGER NOT NULL,

    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
    FOREIGN KEY (track_id) REFERENCES track(id) ON DELETE CASCADE
);

-- Index for efficient ordering
CREATE INDEX IF NOT EXISTS idx_playlist_tracks_pos ON playlist_tracks(playlist_id, position);
"""

async def run_migration():
    print("Initializing DB...")
    await init_db()
    pool = get_pool()
    
    print("Executing SQL...")
    async with pool.acquire() as conn:
        await conn.execute(SQL)
        
    print("Done!")
    await close_db()

if __name__ == "__main__":
    asyncio.run(run_migration())
