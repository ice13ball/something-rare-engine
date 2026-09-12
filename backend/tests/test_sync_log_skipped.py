# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A sync that could not run must say so without claiming it ran.

Two failure modes this guards, both found in the live code on 2026-09-12:

1. **Silence.** Five ONC syncs returned 0 on a missing token with only a log
   line, so nothing reached `sync_log`. `sbma-cook-islands` does the same on an
   unreachable upstream and has no row at all — "never ran" and "ran, could not
   reach the service" look identical from outside. The engine rule in CLAUDE.md
   already said every early return needs a log entry.

2. **A convenient lie.** The sixth ONC sync called `log_sync(src, 0, 0)`, which
   stamps `last_synced_at = NOW()`. A layer with no API token configured then
   reads as freshly synced forever — to the staleness monitor and to the
   LegendPanel "Dates & Freshness" tab a user sees. That is worse than silence,
   because silence at least ages.

⛔ Every assertion below must be reachable by deleting one clause of the SQL.
Each test is annotated with the clause it binds.
"""
import os
from datetime import datetime, timezone

import asyncpg
import pytest

import db
import sync_log

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_SOURCE = "TEST-SKIPPED-GUARD"
_OTHER = "TEST-SKIPPED-GUARD-other"
_SYNCED_AT = datetime(2026, 4, 11, 21, 33, tzinfo=timezone.utc)


class _Acquire:
    """Hands the helper the connection our transaction is open on, so the
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
        await tx.rollback()      # nothing here is ever committed
        await c.close()


async def _seed(c, source=_SOURCE, when=_SYNCED_AT, total=1234):
    await c.execute(
        """INSERT INTO sync_log (source, last_synced_at, records_added, total_records)
           VALUES ($1, $2, 99, $3)
           ON CONFLICT (source) DO UPDATE
           SET last_synced_at = $2, records_added = 99, total_records = $3""",
        source, when, total,
    )


async def _row(c, source=_SOURCE):
    return await c.fetchrow(
        """SELECT last_synced_at, records_added, total_records,
                  skipped_reason, skipped_at
             FROM sync_log WHERE source = $1""",
        source,
    )


@pytest.mark.asyncio
async def test_a_skip_does_not_advance_the_freshness_clock(conn):
    """Binds `ON CONFLICT ... SET` NOT listing `last_synced_at`.

    This is the whole point. If the helper stamped NOW() — the way
    `log_sync(src, 0, 0)` does — an unconfigured layer would look freshly
    synced on every pass and never age into the monitor's stale bucket.
    """
    await _seed(conn)

    await sync_log.log_sync_skipped(_SOURCE, "ONC_TOKEN not configured")

    row = await _row(conn)
    assert row["last_synced_at"] == _SYNCED_AT, "a skip must not claim freshness"


@pytest.mark.asyncio
async def test_a_skip_does_not_rewrite_what_is_being_served(conn):
    """Binds `ON CONFLICT ... SET` NOT listing `total_records`.

    A skipped run did not empty the table. Writing 0 would replace one lie with
    another: the layer may hold perfectly good data from when the token was
    configured, and the monitor's row-count check reads this column.
    """
    await _seed(conn, total=1234)

    await sync_log.log_sync_skipped(_SOURCE, "upstream unreachable")

    row = await _row(conn)
    assert row["total_records"] == 1234, "a skip must not claim the table is empty"


@pytest.mark.asyncio
async def test_a_skip_records_that_it_happened_and_why(conn):
    """Binds the `skipped_reason` / `skipped_at` columns.

    Without these the row is indistinguishable from one written by a successful
    sync that happened to import nothing.
    """
    await _seed(conn)

    await sync_log.log_sync_skipped(_SOURCE, "ONC_TOKEN not configured")

    row = await _row(conn)
    assert row["skipped_reason"] == "ONC_TOKEN not configured"
    assert row["skipped_at"] is not None
    assert row["records_added"] == 0, "nothing was imported, so say zero"


@pytest.mark.asyncio
async def test_a_first_ever_skip_creates_a_row_that_never_claims_a_sync(conn):
    """Binds the INSERT branch, and its literal NULL.

    The sbma-cook-islands case: no row existed at all. After this the source is
    visible with `last_synced_at IS NULL` — "has never completed" — instead of
    being absent, which reads as "nobody ever wired this up".
    """
    assert await _row(conn) is None, "fixture problem: the source must start absent"

    await sync_log.log_sync_skipped(_SOURCE, "no Landfolio base responded")

    row = await _row(conn)
    assert row is not None, "a skip must leave a trace even on the first run"
    assert row["last_synced_at"] is None, "a run that never completed has no date"
    assert row["skipped_reason"] == "no Landfolio base responded"


@pytest.mark.asyncio
async def test_a_skip_touches_only_its_own_source(conn):
    """Binds `WHERE`/conflict-target scoping to the one source."""
    await _seed(conn, source=_OTHER, total=777)

    await sync_log.log_sync_skipped(_SOURCE, "ONC_TOKEN not configured")

    other = await _row(conn, source=_OTHER)
    assert other["total_records"] == 777
    assert other["skipped_reason"] is None
    assert other["last_synced_at"] == _SYNCED_AT


@pytest.mark.asyncio
async def test_a_later_real_sync_clears_the_skip_marker(conn):
    """⛔ Without this the fix is half-done: a source that skipped once would
    carry `skipped_reason` forever, and a reader could not tell a currently
    broken layer from one that recovered three months ago."""
    await sync_log.log_sync_skipped(_SOURCE, "ONC_TOKEN not configured")

    await sync_log.log_sync(_SOURCE, 5, 5)

    row = await _row(conn)
    assert row["last_synced_at"] is not None
    assert row["total_records"] == 5
    assert row["skipped_reason"] is None, "a successful sync must clear the reason"
    assert row["skipped_at"] is None
