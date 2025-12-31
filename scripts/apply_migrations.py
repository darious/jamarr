import asyncio
import hashlib
import os
from pathlib import Path
from typing import Dict, List

import asyncpg


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
LOCK_ID = 87412
MIGRATION_TABLE = "schema_migration"


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(
            f"Environment variable {name} is required. "
            "Set it in docker-compose.yml (jamarr service env) or export it before running."
        )
    return value


DB_HOST = _required_env("DB_HOST")
DB_PORT = int(_required_env("DB_PORT"))
DB_USER = _required_env("DB_USER")
DB_PASS = _required_env("DB_PASS")
DB_NAME = _required_env("DB_NAME")


def _split_statements(sql: str) -> List[str]:
    """
    Very small splitter that handles our simple migrations:
    - strips standalone line comments that start with --
    - splits on semicolons
    """
    lines = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        lines.append(line)

    filtered = "\n".join(lines)
    statements: List[str] = []
    for chunk in filtered.split(";"):
        stmt = chunk.strip()
        if stmt:
            statements.append(stmt)
    return statements


async def _ensure_table(conn: asyncpg.Connection) -> None:
    # If the old plural table exists, rename it to the new singular form
    await conn.execute(
        f"""
        DO $$
        BEGIN
            IF to_regclass('public.{MIGRATION_TABLE}') IS NULL
               AND to_regclass('public.{MIGRATION_TABLE}s') IS NOT NULL THEN
                EXECUTE format('ALTER TABLE %I RENAME TO %I', '{MIGRATION_TABLE}s', '{MIGRATION_TABLE}');
            END IF;
        END
        $$;
        """
    )

    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATION_TABLE} (
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )


async def _get_applied(conn: asyncpg.Connection) -> Dict[str, str]:
    rows = await conn.fetch(f"SELECT version, checksum FROM {MIGRATION_TABLE}")
    return {row["version"]: row["checksum"] for row in rows}


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def apply_migrations() -> None:
    if not MIGRATIONS_DIR.exists():
        raise SystemExit(f"Migration directory not found: {MIGRATIONS_DIR}")

    conn = await asyncpg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, database=DB_NAME
    )
    try:
        await conn.execute("SELECT pg_advisory_lock($1)", LOCK_ID)
        await _ensure_table(conn)

        applied = await _get_applied(conn)
        migrations = sorted(MIGRATIONS_DIR.glob("*.sql"))

        if not migrations:
            print("No migrations found.")
            return

        for path in migrations:
            version = path.name.split("_", 1)[0]
            checksum = _checksum(path)

            if version in applied:
                if applied[version] != checksum:
                    raise SystemExit(
                        f"Checksum mismatch for migration {path.name}. "
                        "Refusing to continue."
                    )
                print(f"Skipping already applied migration {path.name}")
                continue

            sql_text = path.read_text()
            statements = _split_statements(sql_text)
            if not statements:
                print(f"No statements in {path.name}, skipping.")
                continue

            print(f"Applying migration {path.name}...")
            async with conn.transaction():
                for statement in statements:
                    await conn.execute(statement)
                await conn.execute(
                    f"INSERT INTO {MIGRATION_TABLE} (version, checksum) VALUES ($1, $2)",
                    version,
                    checksum,
                )

        print("✅ Migrations applied")
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", LOCK_ID)
        await conn.close()


if __name__ == "__main__":
    asyncio.run(apply_migrations())
