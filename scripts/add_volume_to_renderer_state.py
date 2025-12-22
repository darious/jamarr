import aiosqlite
from app.db import DB_PATH
import asyncio
import os

async def migrate():
    print(f"Migrating database at {DB_PATH}")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("PRAGMA table_info(renderer_states)") as cursor:
            columns = await cursor.fetchall()
            col_names = [c[1] for c in columns]
            print(f"Current columns: {col_names}")
            
            if "volume" in col_names:
                print("Migration already applied.")
                return

        print("Adding volume column...")
        # Add volume column, default to NULL (meaning unknown/unset, or use 0/20?)
        # Let's default to NULL so we know when it's fresh.
        await db.execute("ALTER TABLE renderer_states ADD COLUMN volume INTEGER")
        await db.commit()
        print("Migration successful.")

if __name__ == "__main__":
    asyncio.run(migrate())
