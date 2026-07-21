from pathlib import Path

from migrations.apply_migrations import _split_statements


def test_migration_031_splits_cleanly():
    migration = Path("migrations/031_refresh_session_lineage.sql")
    statements = _split_statements(migration.read_text())

    assert any("ADD COLUMN IF NOT EXISTS family_id" in stmt for stmt in statements)
    assert any("gen_random_uuid()" in stmt for stmt in statements)
    assert any("idx_auth_refresh_session_family" in stmt for stmt in statements)


async def test_migration_031_family_column_exists(db):
    cols = await db.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'auth_refresh_session'
          AND column_name = 'family_id'
        """
    )
    assert len(cols) == 1


async def test_migration_031_family_index_exists(db):
    idx = await db.fetch(
        """
        SELECT indexname
        FROM pg_indexes
        WHERE tablename = 'auth_refresh_session'
          AND indexname = 'idx_auth_refresh_session_family'
        """
    )
    assert len(idx) == 1


async def test_migration_031_backfills_existing_rows(db):
    """The backfill statement must give every pre-existing row its own family
    (exercises gen_random_uuid() on the target Postgres)."""
    await db.execute("DROP TABLE IF EXISTS _mig031_probe")
    await db.execute(
        "CREATE TABLE _mig031_probe (id BIGSERIAL PRIMARY KEY, token_hash TEXT)"
    )
    await db.execute(
        "INSERT INTO _mig031_probe (token_hash) VALUES ('a'), ('b'), ('c')"
    )
    try:
        # The two mutating statements from migration 031
        await db.execute(
            "ALTER TABLE _mig031_probe ADD COLUMN IF NOT EXISTS family_id UUID"
        )
        await db.execute(
            "UPDATE _mig031_probe SET family_id = gen_random_uuid() "
            "WHERE family_id IS NULL"
        )
        fams = [r["family_id"] for r in await db.fetch("SELECT family_id FROM _mig031_probe")]
        assert all(f is not None for f in fams)
        assert len(set(fams)) == 3  # each existing row becomes its own family
    finally:
        await db.execute("DROP TABLE IF EXISTS _mig031_probe")
