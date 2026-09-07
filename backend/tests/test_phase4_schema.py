# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)


@pytest.mark.asyncio
async def test_leak_flags_table_created():
    import asyncpg
    from api_access.schema import ensure_api_access_schema

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    try:
        await ensure_api_access_schema(pool)
        async with pool.acquire() as conn:
            cols = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='api_access' AND table_name='leak_flags'"
            )
            names = {r["column_name"] for r in cols}
            assert {"id", "key_id", "flag_type", "detail",
                    "severity", "detected_at", "acknowledged_at"} <= names
            # partial unique index for debounce exists
            idx = await conn.fetchval(
                "SELECT 1 FROM pg_indexes WHERE schemaname='api_access' "
                "AND tablename='leak_flags' AND indexdef ILIKE '%acknowledged_at IS NULL%'"
            )
            assert idx == 1
    finally:
        await pool.close()
