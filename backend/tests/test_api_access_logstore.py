# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import os
from datetime import date, datetime, timezone

import pytest

from backend.api_access.logstore import (
    daily_partition_name,
    daily_partition_bounds,
    parse_partition_end,
)

TEST_DB = os.getenv("TEST_DATABASE_URL")


# ── pure helpers ──────────────────────────────────────────────────────────────
def test_daily_partition_name():
    assert daily_partition_name(date(2026, 6, 20)) == "request_log_20260620"


def test_daily_partition_bounds_is_one_utc_day():
    start, end = daily_partition_bounds(date(2026, 6, 20))
    assert start == datetime(2026, 6, 20, tzinfo=timezone.utc)
    assert end == datetime(2026, 6, 21, tzinfo=timezone.utc)


def test_parse_partition_end_reads_to_bound():
    expr = "FOR VALUES FROM ('2026-06-20 00:00:00+00') TO ('2026-06-21 00:00:00+00')"
    assert parse_partition_end(expr) == datetime(2026, 6, 21, tzinfo=timezone.utc)


def test_parse_partition_end_bad_input_is_none():
    assert parse_partition_end("garbage") is None


# ── DB-gated schema + retention ───────────────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")
async def test_ensure_log_schema_and_partition_drop():
    import asyncpg
    from backend.api_access.logstore import (
        ensure_log_schema, ensure_daily_partitions, drop_expired_log_partitions,
    )
    pool = await asyncpg.create_pool(TEST_DB, min_size=1, max_size=2)
    try:
        # api_access schema must exist (Phase 1). Create it for the test DB if the
        # role is allowed; ignore failure (CI DB may pre-create it).
        try:
            await pool.execute("CREATE SCHEMA IF NOT EXISTS api_access")
        except Exception:
            pass
        await ensure_log_schema(pool)
        await ensure_log_schema(pool)  # idempotent
        rows = await pool.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='api_access'"
        )
        names = {r["table_name"] for r in rows}
        assert {"request_log", "usage_rollup", "rollup_state"} <= names

        # create an old partition by hand, confirm retention drops it
        await pool.execute(
            "CREATE TABLE IF NOT EXISTS api_access.request_log_20000101 "
            "PARTITION OF api_access.request_log "
            "FOR VALUES FROM ('2000-01-01 00:00:00+00') TO ('2000-01-02 00:00:00+00')"
        )
        dropped = await drop_expired_log_partitions(pool, retention_days=90)
        assert dropped >= 1
        still = await pool.fetchval(
            "SELECT to_regclass('api_access.request_log_20000101')"
        )
        assert still is None
    finally:
        await pool.close()
