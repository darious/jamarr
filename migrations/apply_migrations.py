import asyncio
import hashlib
import os
from pathlib import Path
from typing import Dict, List

import asyncpg


MIGRATIONS_DIR = Path(__file__).resolve().parent
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


def _connect_kwargs() -> Dict[str, object]:
    """Read DB connection settings from the environment (only needed when
    apply_migrations opens its own connection, e.g. the CLI / deploy.sh path)."""
    return dict(
        host=_required_env("DB_HOST"),
        port=int(_required_env("DB_PORT")),
        user=_required_env("DB_USER"),
        password=_required_env("DB_PASS"),
        database=_required_env("DB_NAME"),
    )


def _has_executable_sql(stmt: str) -> bool:
    """True if a statement has any non-comment, non-blank line. A statement made
    up entirely of `--` comments / whitespace is an empty query to Postgres and
    makes asyncpg raise; those must be dropped before execution."""
    return any(
        line.strip() and not line.strip().startswith("--")
        for line in stmt.splitlines()
    )


def _split_statements(sql: str) -> List[str]:
    """
    Statement splitter that respects dollar-quoted blocks (e.g., DO $$ ... $$;)
    and `--` line comments. Splits on semicolons only when not inside a $$ block
    or a line comment — a stray `;` inside a comment must NOT split the file —
    and drops comment/whitespace-only statements.
    """
    statements: List[str] = []
    current: List[str] = []
    in_dollar = False
    in_line_comment = False
    i = 0
    length = len(sql)

    while i < length:
        if not in_line_comment and sql.startswith("$$", i):
            in_dollar = not in_dollar
            current.append("$$")
            i += 2
            continue

        ch = sql[i]

        if in_line_comment:
            current.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        # Start of a line comment (outside dollar blocks): consume `;` as text.
        if not in_dollar and ch == "-" and i + 1 < length and sql[i + 1] == "-":
            in_line_comment = True
            current.append("--")
            i += 2
            continue

        if ch == ";" and not in_dollar:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
        else:
            current.append(ch)
        i += 1

    # Add trailing statement if present
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)

    return [s for s in statements if _has_executable_sql(s)]


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


async def apply_migrations(conn: asyncpg.Connection = None) -> None:
    """Apply any pending migrations. Idempotent and advisory-locked.

    Pass an existing connection (e.g. from the app pool on startup) to reuse it;
    otherwise a dedicated connection is opened from the environment and closed
    afterwards (the CLI / deploy.sh path).
    """
    if not MIGRATIONS_DIR.exists():
        raise SystemExit(f"Migration directory not found: {MIGRATIONS_DIR}")

    own_conn = conn is None
    if own_conn:
        conn = await asyncpg.connect(**_connect_kwargs())
    try:
        await conn.execute("SELECT pg_advisory_lock($1)", LOCK_ID)
        await _ensure_table(conn)

        applied = await _get_applied(conn)
        migrations = sorted(MIGRATIONS_DIR.glob("*.sql"))

        if not migrations:
            print("No migrations found.")
            return

        # Baseline-on-adopt: if nothing is recorded yet but the schema is already
        # current (init_db just built it — the "user" table exists), record every
        # migration as a baseline instead of re-running historical migrations
        # against a schema they were never written for (an old migration may e.g.
        # regex a column that is no longer TEXT). Only a genuinely empty database
        # (no core tables) runs the full history from scratch.
        if not applied:
            initialized = await conn.fetchval('SELECT to_regclass(\'public."user"\')')
            if initialized is not None:
                for path in migrations:
                    version = path.name.split("_", 1)[0]
                    await conn.execute(
                        f"INSERT INTO {MIGRATION_TABLE} (version, checksum) "
                        "VALUES ($1, $2) ON CONFLICT (version) DO NOTHING",
                        version,
                        _checksum(path),
                    )
                print(
                    f"Baselined {len(migrations)} migrations "
                    "(existing current schema, nothing to replay)."
                )
                return

        for path in migrations:
            version = path.name.split("_", 1)[0]
            checksum = _checksum(path)

            if version in applied:
                if applied[version] != checksum:
                    print(
                        f"Checksum mismatch for migration {path.name}. "
                        "Continuing anyway (DEV OVERRIDE)."
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
        if own_conn:
            await conn.close()


if __name__ == "__main__":
    asyncio.run(apply_migrations())
