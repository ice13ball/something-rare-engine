# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A `sync_log` row that disagrees with its table is a lie with an audience.

The monitor classifies staleness from `last_synced_at` and the LegendPanel
"Dates & Freshness" tab shows that same date to users. When GOODD was replaced
by GDW v1.0 on 2026-09-11 the reload ran outside `_sync_dams`, so nothing called
`_log_land_sync`: the row kept saying `2026-04-11 / 38667` while the table held
41,145 rows.

`ensure_dams_sync_log_matches_live_table` corrects that. It carries four guard
clauses and there is one test per clause below — a clause no test binds is a
clause that can be deleted without anything going red.

⛔ Every test runs inside an explicit transaction that is ALWAYS rolled back, on
a connection to `TEST_DATABASE_URL` only, so nothing here is ever committed —
including the `DELETE FROM dams` that the empty-table guard needs in order to be
testable at all.
"""
import os
from datetime import datetime, timezone

import asyncpg
import pytest

import db
from domains.land import common

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_LOADED = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
_OLD_LOG = datetime(2026, 4, 11, 21, 33, tzinfo=timezone.utc)
_GOODD_COUNT = 38667          # what the stale row claimed
_SENTINEL = "TEST-DAMS-REPAIR"


class _Acquire:
    """Hands the step the very connection our transaction is open on, so the
    uncommitted seed is visible to it and the rollback undoes everything."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _PoolFromConn:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _Acquire(self._conn)


@pytest.fixture
async def conn():
    c = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    tx = c.transaction()
    await tx.start()
    previous = db.pool
    db.pool = _PoolFromConn(c)
    try:
        yield c
    finally:
        db.pool = previous
        await tx.rollback()
        await c.close()


async def _seed_dams(c, n, created_at=_LOADED):
    for i in range(n):
        await c.execute(
            "INSERT INTO dams (dam_name, created_at, geom) VALUES ($1, $2, "
            "ST_SetSRID(ST_MakePoint($3, 0), 4326))",
            f"{_SENTINEL}-{i}", created_at, float(i),
        )


async def _seed_log(c, total, source="dams", when=_OLD_LOG):
    await c.execute(
        "INSERT INTO sync_log (source, last_synced_at, records_added, total_records) "
        "VALUES ($1, $2, $3, $3) ON CONFLICT (source) DO UPDATE "
        "SET last_synced_at = $2, records_added = $3, total_records = $3",
        source, when, total,
    )


async def _log_row(c, source="dams"):
    return await c.fetchrow(
        "SELECT last_synced_at, records_added, total_records FROM sync_log "
        "WHERE source = $1", source,
    )


@pytest.mark.asyncio
async def test_a_stale_row_is_corrected_from_the_live_table(conn):
    """The repair itself: both values come from `dams`, not from a constant."""
    await _seed_dams(conn, 3)
    live = await conn.fetchval("SELECT count(*) FROM dams")
    await _seed_log(conn, _GOODD_COUNT)

    await common.ensure_dams_sync_log_matches_live_table()

    row = await _log_row(conn)
    assert row["total_records"] == live, "total_records must equal count(*)"
    assert row["records_added"] == live
    assert row["last_synced_at"] == _LOADED, "date must be the real load time"


@pytest.mark.asyncio
async def test_a_row_that_already_agrees_is_left_exactly_as_it_is(conn):
    """Binds `s.total_records <> d.n`. Without it the step would overwrite a
    healthy sync's own timestamp with the load time of the rows it left alone,
    every single restart."""
    await _seed_dams(conn, 3)
    live = await conn.fetchval("SELECT count(*) FROM dams")
    healthy = datetime(2026, 9, 12, 6, 0, tzinfo=timezone.utc)
    await _seed_log(conn, live, when=healthy)

    await common.ensure_dams_sync_log_matches_live_table()

    row = await _log_row(conn)
    assert row["last_synced_at"] == healthy, "an agreeing row must not be rewritten"
    assert row["total_records"] == live


@pytest.mark.asyncio
async def test_an_empty_dams_table_does_not_erase_a_truthful_row(conn):
    """Binds `d.loaded_at IS NOT NULL` — `max()` over zero rows is already NULL,
    which is what stops an empty table from overwriting a truthful record.

    ⛔ An `AND d.n > 0` clause used to sit beside it and this test stayed green
    when that clause was deleted: `d.n = 0` implies `d.loaded_at IS NULL`, so it
    could never fire alone. Two tests now bind the one clause that does the work
    (this and the NULL-`created_at` one below) — both go red if it is removed."""
    await conn.execute("DELETE FROM dams")   # inside the rolled-back transaction
    await _seed_log(conn, _GOODD_COUNT)

    await common.ensure_dams_sync_log_matches_live_table()

    row = await _log_row(conn)
    assert row["total_records"] == _GOODD_COUNT, "empty table must change nothing"
    assert row["last_synced_at"] == _OLD_LOG


@pytest.mark.asyncio
async def test_rows_without_created_at_do_not_null_the_sync_date(conn):
    """Binds `d.loaded_at IS NOT NULL`. `created_at` is defaulted, not enforced:
    rows predating the default would give `max(created_at) = NULL`, and a NULL
    `last_synced_at` reads to the monitor as a layer that never synced."""
    await conn.execute("DELETE FROM dams")
    await _seed_dams(conn, 3, created_at=None)
    assert await conn.fetchval("SELECT count(*) FROM dams") == 3
    await _seed_log(conn, _GOODD_COUNT)

    await common.ensure_dams_sync_log_matches_live_table()

    row = await _log_row(conn)
    assert row["last_synced_at"] == _OLD_LOG, "must not stamp NULL over a real date"
    assert row["total_records"] == _GOODD_COUNT


@pytest.mark.asyncio
async def test_another_layers_row_is_never_touched(conn):
    """Binds `s.source = 'dams'`. Without it the UPDATE joins every row in
    sync_log to the dams count and rewrites all ~98 sources at once."""
    other = f"{_SENTINEL}-other-layer"
    await _seed_dams(conn, 3)
    await _seed_log(conn, _GOODD_COUNT)
    await _seed_log(conn, 12345, source=other)

    await common.ensure_dams_sync_log_matches_live_table()

    row = await _log_row(conn, source=other)
    assert row["total_records"] == 12345, "only the dams row may be corrected"
    assert row["last_synced_at"] == _OLD_LOG
