from pathlib import Path

from migrations.apply_migrations import _split_statements


def test_migration_029_splits_cleanly():
    migration = Path("migrations/029_renderer_backend.sql")
    statements = _split_statements(migration.read_text())

    assert len(statements) >= 5
    assert any("ALTER TABLE renderer" in stmt for stmt in statements)
    assert any("active_renderer_id" in stmt for stmt in statements)


async def test_migration_029_columns_exist(db):
    renderer_cols = await db.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'renderer'
          AND column_name = ANY($1::text[])
        """,
        [
            "kind",
            "native_id",
            "renderer_id",
            "cast_uuid",
            "cast_type",
            "last_discovered_by",
            "available",
            "enabled_by_default",
            "renderer_metadata",
        ],
    )
    session_cols = await db.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'client_session'
          AND column_name = 'active_renderer_id'
        """
    )

    assert {row["column_name"] for row in renderer_cols} == {
        "kind",
        "native_id",
        "renderer_id",
        "cast_uuid",
        "cast_type",
        "last_discovered_by",
        "available",
        "enabled_by_default",
        "renderer_metadata",
    }
    assert len(session_cols) == 1


async def test_migration_029_renderer_id_has_upsert_compatible_unique_constraint(db):
    rows = await db.fetch(
        """
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_attribute a
          ON a.attrelid = t.oid
         AND a.attnum = ANY(c.conkey)
        WHERE t.relname = 'renderer'
          AND c.contype = 'u'
          AND a.attname = 'renderer_id'
        """
    )

    assert rows
