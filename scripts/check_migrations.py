#!/usr/bin/env python
"""Quick script to manually apply pending migrations."""
import asyncio
import asyncpg
import os
from pathlib import Path

async def main():
    conn = await asyncpg.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT')),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASS'),
        database=os.getenv('DB_NAME')
    )
    
    try:
        # Check what's applied
        rows = await conn.fetch("SELECT version FROM schema_migration ORDER BY version")
        applied = {row['version'] for row in rows}
        print(f"Applied migrations: {sorted(applied)}")
        
        # List all migrations
        migrations_dir = Path(__file__).parent / "migrations"
        all_migrations = sorted(migrations_dir.glob("*.sql"))
        
        for mig in all_migrations:
            version = mig.name.split('_', 1)[0]
            if version not in applied:
                print(f"\nPending: {mig.name}")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
