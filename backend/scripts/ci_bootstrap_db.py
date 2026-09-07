# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Create the full schema in an empty database, for CI.

⛔ This must stay a thin caller of the SAME three ensure_* functions that
`main.lifespan()` runs, in the SAME order. Do not inline DDL here and do not
"simplify" the order: order is semantics — an index or ALTER ahead of its
CREATE TABLE fails at boot, which is precisely the class of bug a CI schema
step exists to catch. If lifespan gains a fourth step, add it here too.

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

    from domains.land.schema_orchestrator import ensure_land_schema
    from ais_sync import ensure_ais_schema
    from schema import ensure_schema

    steps = [
        (ensure_schema, "ensure_schema"),
        (ensure_land_schema, "ensure_land_schema"),
        (ensure_ais_schema, "ensure_ais_schema"),
    ]

    failed = 0
    for fn, name in steps:
        try:
            await fn()
            print(f"ci_bootstrap_db: {name} OK")
        except Exception as exc:                      # noqa: BLE001 — report every step
            failed += 1
            print(f"ci_bootstrap_db: {name} FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)

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
