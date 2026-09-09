# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Regression: air_quality_params must key on (location_id, sensor_id,
parameter). One OpenAQ location can carry several sensors reporting the SAME
parameter (reference-grade + low-cost both measuring pm25 is the ordinary
case). Under the old key (location_id, parameter) a second sensor's row
silently overwrote the first. Verified 2026-09-09.
"""

import os
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)


@pytest.fixture
async def pool():
    import asyncpg
    import db as _db
    from domains.land.schema_orchestrator import ensure_land_schema

    _db.pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    await ensure_land_schema()
    async with _db.pool.acquire() as c:
        await c.execute("DELETE FROM air_quality_params WHERE location_id = 900001")
        await c.execute("DELETE FROM air_quality_stations WHERE location_id = 900001")
    yield _db.pool
    async with _db.pool.acquire() as c:
        await c.execute("DELETE FROM air_quality_params WHERE location_id = 900001")
        await c.execute("DELETE FROM air_quality_stations WHERE location_id = 900001")
    await _db.pool.close()


async def _insert_two_sensors(pool, loc_id: int):
    """Two sensors at one location, same parameter, different values/dates."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO air_quality_params
                (location_id, sensor_id, parameter, value, unit, last_updated,
                 datetime_first, datetime_last)
            VALUES ($1, $2, $3, $4, $5, NOW(), $6, $7)
            ON CONFLICT (location_id, sensor_id, parameter) DO UPDATE
            SET value = EXCLUDED.value, unit = EXCLUDED.unit, last_updated = NOW(),
                datetime_first = EXCLUDED.datetime_first, datetime_last = EXCLUDED.datetime_last
            """,
            loc_id, 11001, "pm25", 8.4, "µg/m³",
            datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        await conn.execute(
            """
            INSERT INTO air_quality_params
                (location_id, sensor_id, parameter, value, unit, last_updated,
                 datetime_first, datetime_last)
            VALUES ($1, $2, $3, $4, $5, NOW(), $6, $7)
            ON CONFLICT (location_id, sensor_id, parameter) DO UPDATE
            SET value = EXCLUDED.value, unit = EXCLUDED.unit, last_updated = NOW(),
                datetime_first = EXCLUDED.datetime_first, datetime_last = EXCLUDED.datetime_last
            """,
            loc_id, 22002, "pm25", 11.9, "µg/m³",
            datetime(2025, 6, 1, tzinfo=timezone.utc), datetime(2026, 9, 8, tzinfo=timezone.utc),
        )


@pytest.mark.asyncio
async def test_two_sensors_same_parameter_both_survive(pool):
    loc_id = 900001
    await _insert_two_sensors(pool, loc_id)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT sensor_id, value, unit, datetime_first, datetime_last "
            "FROM air_quality_params WHERE location_id = $1 AND parameter = 'pm25' "
            "ORDER BY sensor_id",
            loc_id,
        )

    assert len(rows) == 2, f"expected 2 surviving sensor rows, got {len(rows)}: {rows}"
    assert rows[0]["sensor_id"] == 11001
    assert rows[0]["value"] == pytest.approx(8.4)
    assert rows[1]["sensor_id"] == 22002
    assert rows[1]["value"] == pytest.approx(11.9)
    # each sensor keeps its OWN datetime span
    assert rows[0]["datetime_last"] != rows[1]["datetime_last"]


@pytest.mark.asyncio
async def test_migration_actually_moves_the_table_off_the_old_key(pool):
    """Build the table under the PRE-FIX key, then run the migration for real.

    ⛔ The earlier version of this test inserted a row that already had
    sensor_id and re-ran ensure_land_schema — an idempotency check wearing a
    migration test's name. A reviewer commented out the whole DROP CONSTRAINT /
    ADD PRIMARY KEY block on 2026-09-09 and every test here still passed, while
    the regression it was meant to catch would have left every production row
    stuck on (location_id, parameter) forever, silently overwriting one
    sensor's readings with another's on every sync.

    This version starts from the old shape, so the migration branch is the only
    thing that can make it pass.
    """
    import db
    from domains.land.schema_orchestrator import ensure_land_schema

    async with db.pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS air_quality_params")
        await conn.execute("""
            CREATE TABLE air_quality_params (
                location_id  INTEGER NOT NULL,
                parameter    TEXT NOT NULL,
                value        DOUBLE PRECISION,
                unit         TEXT,
                last_updated TIMESTAMPTZ,
                PRIMARY KEY (location_id, parameter)
            )
        """)
        await conn.execute(
            "INSERT INTO air_quality_params (location_id, parameter, value, unit) "
            "VALUES (900123, 'no2', 5.5, 'ug/m3')"
        )
        before = await _pk_columns(conn)
        assert before == ["location_id", "parameter"], f"fixture did not build the old key: {before}"

    await ensure_land_schema()

    async with db.pool.acquire() as conn:

        after = await _pk_columns(conn)
        assert after == ["location_id", "parameter", "sensor_id"], (
            f"the primary key was not migrated — still {after}. Every existing "
            "row stays on the old key and one sensor keeps overwriting another."
        )
        row = await conn.fetchrow(
            "SELECT value, sensor_id FROM air_quality_params "
            "WHERE location_id = 900123 AND parameter = 'no2'")
        assert row is not None, "the migration dropped a pre-existing row"
        assert float(row["value"]) == 5.5, "the migration corrupted a pre-existing value"
        await conn.execute("DELETE FROM air_quality_params WHERE location_id = 900123")


async def _pk_columns(conn) -> list[str]:
    rows = await conn.fetch(
        """SELECT a.attname FROM pg_index i
           JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
           WHERE i.indrelid = 'air_quality_params'::regclass AND i.indisprimary
           ORDER BY a.attname"""
    )
    return sorted(r["attname"] for r in rows)


@pytest.mark.asyncio
async def test_migration_keeps_rows_from_old_key(pool):
    """
    A row inserted under the pre-fix shape (sensor_id defaults to 0, as the
    migration backfills for pre-existing data) must survive re-running
    ensure_land_schema — the migration must not delete or duplicate it.
    """
    loc_id = 900001
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO air_quality_params (location_id, sensor_id, parameter, value, unit, last_updated)
            VALUES ($1, 0, 'no2', 5.5, 'µg/m³', NOW())
            ON CONFLICT (location_id, sensor_id, parameter) DO UPDATE SET value = EXCLUDED.value
            """,
            loc_id,
        )

    from domains.land.schema_orchestrator import ensure_land_schema
    await ensure_land_schema()  # re-run: must be idempotent, must not touch this row

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT sensor_id, value FROM air_quality_params WHERE location_id = $1 AND parameter = 'no2'",
            loc_id,
        )
    assert len(rows) == 1
    assert rows[0]["sensor_id"] == 0
    assert rows[0]["value"] == pytest.approx(5.5)


@pytest.mark.asyncio
async def test_missing_unit_stores_null_never_invented(pool):
    loc_id = 900001
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO air_quality_params (location_id, sensor_id, parameter, value, unit, last_updated)
            VALUES ($1, 33003, 'um003', 1.0, NULL, NOW())
            ON CONFLICT (location_id, sensor_id, parameter) DO UPDATE SET value = EXCLUDED.value
            """,
            loc_id,
        )
        row = await conn.fetchrow(
            "SELECT unit FROM air_quality_params WHERE location_id = $1 AND sensor_id = 33003 AND parameter = 'um003'",
            loc_id,
        )
    assert row["unit"] is None
