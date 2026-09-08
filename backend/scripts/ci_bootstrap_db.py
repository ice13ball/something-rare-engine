# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Create the full schema in an empty database, for CI.

⛔ This must stay a thin caller of the SAME sixteen steps that `main.lifespan()`
runs, in the SAME order — both import `schema_steps.SCHEMA_STEPS`, the single
source of truth. Do not inline DDL here and do not "simplify" the order: order
is semantics — an index or ALTER ahead of its CREATE TABLE fails at boot, which
is precisely the class of bug a CI schema step exists to catch. A new step
belongs in `schema_steps.py`, not here.

Why a role is created first: `profiles.py` issues
`ALTER TABLE startup_profiles OWNER TO abyssal_user`, so a database without
that role cannot complete the schema. Production has the role; a fresh CI
container does not.

Usage (from the repository root):
    DATABASE_URL=postgresql://... python3 backend/scripts/ci_bootstrap_db.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import asyncpg  # noqa: E402

import db as _db  # noqa: E402


async def main() -> int:
    url = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    if not url:
        print("ci_bootstrap_db: neither DATABASE_URL nor TEST_DATABASE_URL is set", file=sys.stderr)
        return 2

    # A freshly-created Postgres container restarts its server once, after initdb,
    # so a connection opened in that window dies with ConnectionResetError even
    # though the port already answers and pg_isready already said yes. Measured:
    # the database accepted `SELECT 1` at t+3s and still reset the pool afterwards.
    # Retrying is the fix; waiting longer before the first attempt is not, because
    # the restart is not on a fixed schedule.
    pool = None
    last: Exception | None = None
    for attempt in range(1, 11):
        try:
            pool = await asyncpg.create_pool(url, min_size=1, max_size=4)
            async with pool.acquire() as conn:
                await conn.execute("SELECT 1")
            break
        except (OSError, asyncpg.PostgresError) as exc:
            last = exc
            if pool is not None:
                await pool.close()
                pool = None
            print(f"ci_bootstrap_db: database not ready (attempt {attempt}/10): "
                  f"{type(exc).__name__}", file=sys.stderr)
            await asyncio.sleep(2)
    if pool is None:
        print(f"ci_bootstrap_db: could not connect after 10 attempts: {last}", file=sys.stderr)
        return 2
    _db.pool = pool

    async with pool.acquire() as conn:
        # Idempotent: DO block, because CREATE ROLE has no IF NOT EXISTS.
        await conn.execute(
            "DO $$ BEGIN "
            "  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'abyssal_user') THEN "
            "    CREATE ROLE abyssal_user; "
            "  END IF; "
            "END $$;"
        )
        await conn.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

    from schema_steps import (
        SCHEMA_STEPS,
        resolve_git_sha,
        ensure_schema_migrations_table,
        record_schema_migration,
    )

    failed = 0
    for fn, name in SCHEMA_STEPS:
        try:
            await fn()
            print(f"ci_bootstrap_db: {name} OK")
        except Exception as exc:                      # noqa: BLE001 — report every step
            failed += 1
            print(f"ci_bootstrap_db: {name} FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)

    # Write the same schema_migrations row migrate.py writes (shared DDL + upsert
    # in schema_steps.py — a second copy of either is the defect this branch spent
    # commits removing). Without it, a fresh database never gets a row at all:
    # main.py's `_fetch_schema_migration_row` catches UndefinedTableError, returns
    # None, and classifies that as "stale" forever — the alarm stuck on in exactly
    # the environments (CI, any new env) where nothing is wrong. Only write it when
    # every step actually succeeded; a partially-provisioned database recording
    # itself as current would hide the failure instead of reporting it.
    if not failed:
        sha = resolve_git_sha() or "unknown"
        async with pool.acquire() as conn:
            await ensure_schema_migrations_table(conn)
            await record_schema_migration(conn, sha, len(SCHEMA_STEPS))
        print(f"ci_bootstrap_db: schema_migrations recorded ({sha[:12]})")

    async with pool.acquire() as conn:
        n = await conn.fetchval(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
        )
    print(f"ci_bootstrap_db: {n} tables in public")
    await pool.close()

    # A schema step that fails is a CI failure: the suite below it would then be
    # testing an incomplete database and reporting misses as passes.
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
