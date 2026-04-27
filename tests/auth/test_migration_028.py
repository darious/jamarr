from pathlib import Path

import pytest
import asyncpg

from app.auth import hash_password
from migrations.apply_migrations import _split_statements


@pytest.mark.asyncio
async def test_migration_028_creates_user_favorite_tables(db: asyncpg.Connection):
    migration = Path("migrations/028_user_favorites.sql")
    statements = _split_statements(migration.read_text())

    tx = db.transaction()
    await tx.start()
    try:
        await db.execute(
            """
            INSERT INTO "user" (username, email, password_hash, display_name, created_at)
            VALUES ('fav_migration_user', 'fav_migration_user@example.com', $1, 'Fav Migration User', NOW())
            ON CONFLICT (username) DO NOTHING
            """,
            hash_password("password123"),
        )
        await db.execute(
            """
            INSERT INTO artist (mbid, name, sort_name, letter)
            VALUES ('migration-artist', 'Migration Artist', 'Migration Artist', 'M')
            ON CONFLICT (mbid) DO NOTHING
            """
        )
        await db.execute(
            """
            INSERT INTO album (mbid, release_group_mbid, title, release_date)
            VALUES ('migration-release', 'migration-rg', 'Migration Release', '2024-01-01')
            ON CONFLICT (mbid) DO NOTHING
            """
        )

        for statement in statements:
            await db.execute(statement)

        user = await db.fetchrow(
            'SELECT id FROM "user" WHERE username = $1',
            "fav_migration_user",
        )
        await db.execute(
            """
            INSERT INTO favorite_artist (user_id, artist_mbid)
            VALUES ($1, $2)
            """,
            user["id"],
            "migration-artist",
        )
        await db.execute(
            """
            INSERT INTO favorite_release (user_id, album_mbid)
            VALUES ($1, $2)
            """,
            user["id"],
            "migration-release",
        )

        artist_favorite = await db.fetchval(
            """
            SELECT COUNT(*)
            FROM favorite_artist
            WHERE user_id = $1 AND artist_mbid = $2
            """,
            user["id"],
            "migration-artist",
        )
        release_favorite = await db.fetchval(
            """
            SELECT COUNT(*)
            FROM favorite_release
            WHERE user_id = $1 AND album_mbid = $2
            """,
            user["id"],
            "migration-release",
        )

        assert artist_favorite == 1
        assert release_favorite == 1
    finally:
        await tx.rollback()
