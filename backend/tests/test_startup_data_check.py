# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Regression: `_startup_data_check()` in main.py hard-codes a `tables` list that
must name REAL tables. Four entries drifted from the schema (`eez`,
`oceansites`, `onc_stations`, `chess_sites`) and logged a false "missing or
empty" WARNING on every single boot, forever, while the real tables
(`maritime_boundaries`, `oceansites_stations`, `onc_locations`,
`chess_occurrences`) were fully populated. Fixed 2026-09-09.

This test EXECUTES `_startup_data_check()` against a real schema (built by
`schema.ensure_schema()`), harvests the table name out of every log record it
actually emitted, and re-verifies each one with `to_regclass` against the
live connection — so the assertion is tied to what the function did at
runtime, not to a copy of the list pasted into the test.
"""

import logging
import os
import re

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_LOG_RE = re.compile(r"^startup check: (\S+)")


@pytest.fixture
async def pool():
    import asyncpg
    import db as _db
    import schema

    _db.pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    await schema.ensure_schema()
    yield _db.pool
    await _db.pool.close()


@pytest.mark.asyncio
async def test_every_startup_check_table_actually_exists(pool, caplog):
    import main

    main._pool = pool

    with caplog.at_level(logging.INFO, logger="main"):
        await main._startup_data_check()

    checked = [
        m.group(1)
        for r in caplog.records
        if r.name == "main" and (m := _LOG_RE.match(r.getMessage()))
    ]
    assert checked, "no 'startup check: ...' log lines were emitted — did the function run at all?"

    async with pool.acquire() as conn:
        offenders = []
        for name in checked:
            regclass = await conn.fetchval("SELECT to_regclass($1)", name)
            if regclass is None:
                offenders.append(name)

    assert not offenders, (
        f"_startup_data_check() names {len(offenders)} table(s) that do not "
        f"exist in the real schema: {offenders}. Every entry in its `tables` "
        "list must be a real table name — see backend/schema/ for the "
        "CREATE TABLE that proves the right one."
    )
