# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Runs the three production hex-density-histogram queries (memento, geotraces,
mosaic) against real PostGIS, in a private `hex_sql_exec` schema whose fixture
tables carry only the columns the SQL touches.

The production tables (`density_hex_cells`, `memento_casts`, ...) are not
populated in CI, and `density_hex_cells` is a global hex grid that is far too
expensive to build for a test. So instead: build small fixture tables with the
same column names/types as the real DDL, point `search_path` at a scratch
schema, and let the UNMODIFIED production SQL constants (imported from the
leaf module `domains/geochem_sql.py`, which cannot trip the circular import
that used to force these tests into source-slicing) resolve against the
fixtures. `public` stays on the search_path too, so PostGIS functions
(ST_Centroid, ST_Intersects, ...) are still reachable unqualified.
"""
import datetime
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

SCHEMA = "hex_sql_exec"

# Two hexes (small squares) far enough apart that neither's bbox touches the
# other's. Hex A centroid ~(10, 60); hex B centroid ~(20, 60).
_HEX_A_WKT = "POLYGON((9.5 59.5, 10.5 59.5, 10.5 60.5, 9.5 60.5, 9.5 59.5))"
_HEX_B_WKT = "POLYGON((19.5 59.5, 20.5 59.5, 20.5 60.5, 19.5 60.5, 19.5 59.5))"
_PT_A = (10.0, 60.0)
_PT_B = (20.0, 60.0)


async def _setup_schema(conn):
    await conn.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
    # Pre-drop, not just post-drop: a hard crash (or a killed CI job) leaves the
    # scratch schema behind, and then CREATE TABLE fails with "already exists" —
    # a red build whose cause is the previous run, not the code under test.
    await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    await conn.execute(f"CREATE SCHEMA {SCHEMA}")
    await conn.execute(f"SET search_path TO {SCHEMA}, public")

    await conn.execute(
        """CREATE TABLE density_hex_cells (
               geom geometry(Polygon,4326)
           )"""
    )
    await conn.execute(
        """CREATE TABLE memento_casts (
               decade INTEGER,
               sample_time TIMESTAMPTZ,
               geom geometry(Point,4326)
           )"""
    )
    await conn.execute(
        """CREATE TABLE geotraces_stations (
               decade INTEGER,
               sample_time TIMESTAMPTZ,
               geom geometry(Point,4326)
           )"""
    )
    await conn.execute(
        """CREATE TABLE mosaic_cores (
               decade INTEGER,
               sampling_year INTEGER,
               geom geometry(Point,4326)
           )"""
    )

    await conn.execute(
        "INSERT INTO density_hex_cells (geom) VALUES "
        "(ST_GeomFromText($1, 4326)), (ST_GeomFromText($2, 4326))",
        _HEX_A_WKT, _HEX_B_WKT,
    )


async def _seed_sample_time_table(conn, table: str):
    """Seeds memento_casts / geotraces_stations: decade + sample_time rows."""
    lon_a, lat_a = _PT_A
    lon_b, lat_b = _PT_B
    def dt(y: int) -> datetime.datetime:
        return datetime.datetime(y, 6, 1, tzinfo=datetime.timezone.utc)

    rows = [
        # Hex A: 3 rows decade 1980 (1983, 1985, 1987)
        (1980, dt(1983), lon_a, lat_a),
        (1980, dt(1985), lon_a, lat_a),
        (1980, dt(1987), lon_a, lat_a),
        # Hex A: 2 rows decade 1990 (1994, 1996)
        (1990, dt(1994), lon_a, lat_a),
        (1990, dt(1996), lon_a, lat_a),
        # Hex A: 1 row decade NULL, no date
        (None, None, lon_a, lat_a),
        # Hex B: 2 rows decade NULL, no date
        (None, None, lon_b, lat_b),
        (None, None, lon_b, lat_b),
    ]
    await conn.executemany(
        f"""INSERT INTO {table} (decade, sample_time, geom)
            VALUES ($1, $2, ST_SetSRID(ST_MakePoint($3, $4), 4326))""",
        rows,
    )


async def _seed_mosaic(conn):
    lon_a, lat_a = _PT_A
    lon_b, lat_b = _PT_B
    rows = [
        # Hex A: 3 rows decade 1980 (years 1983, 1985, 1987)
        (1980, 1983, lon_a, lat_a),
        (1980, 1985, lon_a, lat_a),
        (1980, 1987, lon_a, lat_a),
        # Hex A: 2 rows decade 1990 (years 1994, 1996)
        (1990, 1994, lon_a, lat_a),
        (1990, 1996, lon_a, lat_a),
        # Hex A: 1 row decade NULL, no year
        (None, None, lon_a, lat_a),
        # Hex B: 2 rows decade NULL, no year
        (None, None, lon_b, lat_b),
        (None, None, lon_b, lat_b),
    ]
    await conn.executemany(
        """INSERT INTO mosaic_cores (decade, sampling_year, geom)
           VALUES ($1, $2, ST_SetSRID(ST_MakePoint($3, $4), 4326))""",
        rows,
    )


def _by_lon(fc: dict) -> dict:
    """Index features by rounded lon so hex A/B can be told apart without
    relying on GROUP BY row order, which is not guaranteed."""
    out = {}
    for feat in fc["features"]:
        lon = round(feat["properties"]["lon"])
        out[lon] = feat
    return out


def _assert_hex_invariants(fc: dict):
    assert len(fc["features"]) == 2

    by_lon = _by_lon(fc)
    assert set(by_lon.keys()) == {10, 20}

    hex_a = by_lon[10]["properties"]
    hex_b = by_lon[20]["properties"]

    assert hex_a["count"] == 6
    assert hex_a["by_decade"] == {"1980": 3, "1990": 2}
    assert hex_a["n_undated"] == 1
    assert hex_a["year_min"] == 1983
    assert hex_a["year_max"] == 1996

    assert hex_b["count"] == 2
    assert hex_b["by_decade"] == {}
    assert hex_b["n_undated"] == 2
    assert hex_b["year_min"] is None
    assert hex_b["year_max"] is None

    for feat in fc["features"]:
        props = feat["properties"]
        assert isinstance(props["by_decade"], dict), (
            "by_decade came back as something other than a dict — asyncpg "
            "hands JSONB back as str, and json.loads() must be applied"
        )
        assert sum(props["by_decade"].values()) + props["n_undated"] == props["count"]
        for key in props["by_decade"]:
            assert key not in ("None", "null"), (
                f"by_decade carries a {key!r} key — the FILTER (WHERE decade "
                "IS NOT NULL) clause is not excluding NULL decades"
            )


@pytest.mark.asyncio
async def test_memento_hexes_sql_produces_correct_histogram():
    import asyncpg
    from domains.geochem_sql import MEMENTO_HEX_SQL, hex_feature_collection

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    try:
        async with pool.acquire() as conn:
            await _setup_schema(conn)
            await _seed_sample_time_table(conn, "memento_casts")
            rows = await conn.fetch(MEMENTO_HEX_SQL)
        fc = hex_feature_collection(rows)
        _assert_hex_invariants(fc)
    finally:
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        await pool.close()


@pytest.mark.asyncio
async def test_geotraces_hexes_sql_produces_correct_histogram():
    import asyncpg
    from domains.geochem_sql import GEOTRACES_HEX_SQL, hex_feature_collection

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    try:
        async with pool.acquire() as conn:
            await _setup_schema(conn)
            await _seed_sample_time_table(conn, "geotraces_stations")
            rows = await conn.fetch(GEOTRACES_HEX_SQL)
        fc = hex_feature_collection(rows)
        _assert_hex_invariants(fc)
    finally:
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        await pool.close()


@pytest.mark.asyncio
async def test_mosaic_hexes_sql_produces_correct_histogram():
    import asyncpg
    from domains.geochem_sql import MOSAIC_HEX_SQL, hex_feature_collection

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    try:
        async with pool.acquire() as conn:
            await _setup_schema(conn)
            await _seed_mosaic(conn)
            rows = await conn.fetch(MOSAIC_HEX_SQL)
        fc = hex_feature_collection(rows)
        _assert_hex_invariants(fc)
    finally:
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        await pool.close()
