# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import os
from datetime import datetime, timezone

import pytest

TEST_DB = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")


@pytest.mark.asyncio
async def test_rollup_counts_each_row_once_and_is_idempotent():
    import asyncpg
    from backend.api_access.logstore import ensure_log_schema, ensure_daily_partitions
    from backend.api_access.rollup import rollup_new_rows

    pool = await asyncpg.create_pool(TEST_DB, min_size=1, max_size=2)
    try:
        try:
            await pool.execute("CREATE SCHEMA IF NOT EXISTS api_access")
        except Exception:
            pass
        await ensure_log_schema(pool)
        async with pool.acquire() as conn:
            await ensure_daily_partitions(conn)
        # clean slate for deterministic counts
        await pool.execute("DELETE FROM api_access.usage_rollup")
        await pool.execute("DELETE FROM api_access.request_log")
        await pool.execute("UPDATE api_access.rollup_state SET last_log_id = 0 WHERE name='request_log'")

        ts = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        # two rows same (key,hour,endpoint) + one error + one NULL-key row (skipped)
        await pool.executemany(
            "INSERT INTO api_access.request_log "
            "(key_id, org_id, ts, method, path, endpoint_label, status_code, response_bytes) "
            "VALUES ($1,$2,$3,'GET','/v1/x','/v1/x',$4,$5)",
            [(1, 1, ts, 200, 100), (1, 1, ts, 500, 50), (None, None, ts, 403, 0)],
        )

        n = await rollup_new_rows(pool)
        assert n == 3                       # 3 raw rows advanced past the watermark
        row = await pool.fetchrow(
            "SELECT request_count, error_count, total_bytes FROM api_access.usage_rollup "
            "WHERE key_id=1 AND endpoint_label='/v1/x'"
        )
        assert row["request_count"] == 2    # NULL-key row excluded
        assert row["error_count"] == 1
        assert row["total_bytes"] == 150

        assert await rollup_new_rows(pool) == 0   # nothing new → idempotent
        row2 = await pool.fetchval(
            "SELECT request_count FROM api_access.usage_rollup WHERE key_id=1 AND endpoint_label='/v1/x'"
        )
        assert row2 == 2                    # not double-counted
    finally:
        await pool.close()
