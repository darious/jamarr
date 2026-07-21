"""The app lifespan runs apply_migrations() on startup (AUTO_MIGRATE), reusing
the app's DB connection.

These guard the auto-migrate path:
- a fresh, already-current schema (built by init_db) is *baselined* — all
  migrations recorded, none replayed. Replaying historical migrations against
  the current schema would raise (e.g. migration 005 regexes a column that is no
  longer TEXT), so reaching the assertions without raising proves we baselined.
- the whole thing is idempotent.
"""
from migrations.apply_migrations import apply_migrations


async def test_auto_migrate_baselines_current_schema(db):
    # Force the "adopt" path: no migrations recorded yet, but init_db already
    # built the current schema (the "user" table exists).
    await db.execute("DROP TABLE IF EXISTS schema_migration")

    await apply_migrations(db)  # must NOT raise (baselines instead of replaying)

    versions = {
        row["version"]
        for row in await db.fetch("SELECT version FROM schema_migration")
    }
    # Every migration recorded — including 005 (which would have errored if run).
    assert {"001", "005", "031"} <= versions


async def test_auto_migrate_is_idempotent(db):
    await apply_migrations(db)
    await apply_migrations(db)  # second run is a clean no-op

    col = await db.fetch(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'auth_refresh_session' AND column_name = 'family_id'
        """
    )
    assert len(col) == 1
