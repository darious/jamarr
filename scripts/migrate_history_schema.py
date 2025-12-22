import aiosqlite
from app.db import DB_PATH
import asyncio
import os

async def migrate():
    print(f"Migrating database at {DB_PATH}")
    async with aiosqlite.connect(DB_PATH) as db:
        # Check current schema
        async with db.execute("PRAGMA table_info(playback_history)") as cursor:
            columns = await cursor.fetchall()
            col_names = [c[1] for c in columns]
            print(f"Current columns: {col_names}")
            
            if "client_id" in col_names and "hostname" not in col_names:
                print("Migration already applied.")
                return

        # 1. Rename old table
        print("Renaming old table...")
        await db.execute("ALTER TABLE playback_history RENAME TO playback_history_old")
        
        # 2. Create new table
        print("Creating new table...")
        await db.execute("""
            CREATE TABLE playback_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id INTEGER NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                client_ip TEXT,
                client_id TEXT,
                FOREIGN KEY (track_id) REFERENCES tracks (id)
            )
        """)
        
        # 3. Copy data
        # We map 'hostname' (server IP) to NULL or ignore it. 
        # We initialize client_id to NULL for old records.
        # SQLite columns are matched by order in INSERT unless specified.
        print("Copying data...")
        await db.execute("""
            INSERT INTO playback_history (id, track_id, timestamp, client_ip, client_id)
            SELECT id, track_id, timestamp, client_ip, NULL FROM playback_history_old
        """)
        
        # 4. Verify count
        async with db.execute("SELECT count(*) FROM playback_history") as c1:
            count_new = (await c1.fetchone())[0]
        async with db.execute("SELECT count(*) FROM playback_history_old") as c2:
            count_old = (await c2.fetchone())[0]
            
        print(f"Copied {count_new} records (Old: {count_old})")
        
        if count_new == count_old:
            print("Dropping old table...")
            await db.execute("DROP TABLE playback_history_old")
            await db.commit()
            print("Migration successful.")
        else:
            print("Row count mismatch! Rolling back (manually restore table needed if commit happened, but we haven't committed yet)")
            # In aiosqlite context manager, commit is manual usually, but let's be safe.
            # We haven't committed the DROP.
            # But the CREATE and INSERT within transaction? 
            # We should probably rollback.
            await db.rollback()

if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        # Fallback if running from root without app context?
        # DB_PATH in app.db relies on relative or absolute?
        # Let's assume the script run from root works if app.db imports correct config.
        pass
    
    asyncio.run(migrate())
