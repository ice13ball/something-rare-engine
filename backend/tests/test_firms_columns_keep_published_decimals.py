# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""FIRMS numbers come back out exactly as NASA published them.

On 2026-09-23 scan, track and bright_ti5 were first added as REAL. NASA's
scan 0.35 was stored as float4 and the export served 0.3499999940395355.
ensure_land_schema must create them as DOUBLE PRECISION and convert any REAL
left by that first cut through text, so an already stored 0.35 stays 0.35.
"""
import os

import asyncpg
import pytest

import db as _db
from domains.land import schema_orchestrator
import schema

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)


@pytest.mark.asyncio
async def test_a_real_column_left_by_the_first_cut_is_converted_without_drift():
    original = _db.pool
    _db.pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    try:
        await schema.ensure_schema()
        await schema_orchestrator.ensure_land_schema()
        async with _db.pool.acquire() as c:
            # Recreate the state production was in after the first cut.
            await c.execute("DELETE FROM active_fires WHERE confidence = 'test-decimals'")
            for col in ("scan", "track", "bright_ti5"):
                await c.execute(f"ALTER TABLE active_fires ALTER COLUMN {col} TYPE REAL")
            await c.execute("""
                INSERT INTO active_fires (latitude, longitude, confidence, scan, track, bright_ti5, geom)
                VALUES (1, 2, 'test-decimals', 0.35, 0.57, 285.44, ST_SetSRID(ST_MakePoint(2, 1), 4326))
            """)

        await schema_orchestrator.ensure_land_schema()

        async with _db.pool.acquire() as c:
            types = dict(await c.fetch("""
                SELECT column_name, data_type FROM information_schema.columns
                WHERE table_name = 'active_fires' AND column_name IN ('scan', 'track', 'bright_ti5')
            """))
            row = await c.fetchrow(
                "SELECT scan, track, bright_ti5 FROM active_fires WHERE confidence = 'test-decimals'"
            )
            await c.execute("DELETE FROM active_fires WHERE confidence = 'test-decimals'")
        assert types == {"scan": "double precision", "track": "double precision",
                         "bright_ti5": "double precision"}
        assert (row["scan"], row["track"], row["bright_ti5"]) == (0.35, 0.57, 285.44)
    finally:
        await _db.pool.close()
        _db.pool = original
