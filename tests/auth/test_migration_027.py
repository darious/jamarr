"""Test migration 027 - user admin flag."""
from pathlib import Path

import pytest
import asyncpg

from app.auth import hash_password
from scripts.apply_migrations import _split_statements


@pytest.mark.asyncio
async def test_migration_027_marks_only_chris_admin(db: asyncpg.Connection):
    migration = Path("scripts/migrations/027_user_admin_flag.sql")
    statements = _split_statements(migration.read_text())

    tx = db.transaction()
    await tx.start()
    try:
        await db.execute('DELETE FROM "user" WHERE username IN ($1, $2)', "chris", "not_chris")
        await db.execute(
            """
            INSERT INTO "user" (username, email, password_hash, display_name, is_admin, created_at)
            VALUES
                ('chris', 'chris@example.com', $1, 'Chris', FALSE, NOW()),
                ('not_chris', 'not_chris@example.com', $1, 'Not Chris', TRUE, NOW())
            """,
            hash_password("password123"),
        )

        for statement in statements:
            await db.execute(statement)

        rows = await db.fetch(
            'SELECT username, is_admin FROM "user" WHERE username IN ($1, $2)',
            "chris",
            "not_chris",
        )
        flags = {row["username"]: row["is_admin"] for row in rows}
        assert flags == {"chris": True, "not_chris": False}
    finally:
        await tx.rollback()


@pytest.mark.asyncio
async def test_user_is_admin_column_exists(db: asyncpg.Connection):
    column = await db.fetchrow(
        """
        SELECT data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = 'user' AND column_name = 'is_admin'
        """
    )
    assert column is not None
    assert column["data_type"] == "boolean"
    assert column["is_nullable"] == "NO"
    assert column["column_default"] == "false"
