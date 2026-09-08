# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Executes GET /v2/spatial/geotraces/by-id and /v2/spatial/geotraces/params
against real PostGIS (2026-09-08 additive expansion — geotraces_params +
geotraces_values). Confirms the legacy by-id keys are untouched while the new
"measurements"/"params"/"truncated" keys are populated, and that an unknown
station still 404s.
"""
import os

import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_STATION = "test-geotraces-by-id-station-1"


@pytest.fixture
async def pool_and_router():
    import asyncpg
    import db
    from schema import geochem
    from routers import spatial_v2

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    async with pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        await geochem.ensure_geotraces(conn)

    original_pool = db.pool
    db.pool = pool

    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO geotraces_stations
                 (station_id, cruise, station, lat, lon, decade,
                  has_mn, has_fe, has_co, has_ni, has_cu,
                  mn_max, fe_max, co_max, ni_max, cu_max, geom)
               VALUES
                 ($1, 'TEST-CRUISE', 'ST1', 10.0, 20.0, 2020,
                  TRUE, TRUE, FALSE, FALSE, FALSE,
                  5.0, 3.0, NULL, NULL, NULL,
                  ST_SetSRID(ST_MakePoint(20.0, 10.0), 4326))
               ON CONFLICT (station_id) DO NOTHING""",
            _STATION,
        )
        await conn.execute(
            """INSERT INTO geotraces_samples
                 (station_id, cruise, station, lat, lon, depth_m,
                  mn_d, fe_d, geotraces_sample_id, geom)
               VALUES
                 ($1, 'TEST-CRUISE', 'ST1', 10.0, 20.0, 10.0,
                  1.1, 2.2, 'GT-SAMPLE-1',
                  ST_SetSRID(ST_MakePoint(20.0, 10.0), 4326)),
                 ($1, 'TEST-CRUISE', 'ST1', 10.0, 20.0, 50.0,
                  1.3, 2.4, 'GT-SAMPLE-2',
                  ST_SetSRID(ST_MakePoint(20.0, 10.0), 4326))""",
            _STATION,
        )
        await conn.execute(
            """INSERT INTO geotraces_params (param_code, label, unit, family, n_values)
               VALUES
                 ('Mn_D_CONC_BOTTLE', 'Dissolved Mn', 'nmol/kg', 'trace metal', 100),
                 ('Fe_D_CONC_BOTTLE', 'Dissolved Fe', 'nmol/kg', 'trace metal', 90),
                 ('Cd_D_CONC_BOTTLE', 'Dissolved Cd', 'pmol/kg', 'trace metal', 50)
               ON CONFLICT (param_code) DO NOTHING"""
        )
        await conn.execute(
            """INSERT INTO geotraces_values (sample_id, param_code, value, stddev, qc_flag)
               VALUES
                 ('GT-SAMPLE-1', 'Mn_D_CONC_BOTTLE', 1.1, 0.05, 1),
                 ('GT-SAMPLE-1', 'Fe_D_CONC_BOTTLE', 2.2, NULL, 2),
                 ('GT-SAMPLE-2', 'Mn_D_CONC_BOTTLE', 1.3, 0.02, 1),
                 ('GT-SAMPLE-2', 'Cd_D_CONC_BOTTLE', 0.4, NULL, 1)
               ON CONFLICT (sample_id, param_code) DO NOTHING"""
        )

    try:
        yield spatial_v2
    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM geotraces_values WHERE sample_id IN ('GT-SAMPLE-1', 'GT-SAMPLE-2')"
            )
            await conn.execute(
                "DELETE FROM geotraces_params WHERE param_code IN "
                "('Mn_D_CONC_BOTTLE', 'Fe_D_CONC_BOTTLE', 'Cd_D_CONC_BOTTLE')"
            )
            await conn.execute(
                "DELETE FROM geotraces_samples WHERE station_id = $1", _STATION
            )
            await conn.execute(
                "DELETE FROM geotraces_stations WHERE station_id = $1", _STATION
            )
        db.pool = original_pool
        await pool.close()


@pytest.mark.asyncio
async def test_by_id_keeps_legacy_keys_and_adds_measurements_and_params(pool_and_router):
    spatial_v2 = pool_and_router
    resp = await spatial_v2.geotraces_by_id(_STATION)

    # Legacy keys, byte-for-byte shape unchanged.
    assert set(["station", "units", "samples"]).issubset(resp.keys())
    assert resp["station"]["station_id"] == _STATION
    assert isinstance(resp["units"], dict)
    assert len(resp["samples"]) == 2
    sample_ids = {str(s["sample_id"]) for s in resp["samples"]}
    for s in resp["samples"]:
        assert "mn_d" in s and "fe_d" in s and "co_d" in s and "ni_d" in s and "cu_d" in s

    # New keys.
    assert "measurements" in resp
    assert "params" in resp
    assert "truncated" in resp
    assert resp["truncated"] is False

    all_measurements = [m for sid in sample_ids for m in resp["measurements"][sid]]
    codes = {m["param_code"] for m in all_measurements}
    assert codes == {"Mn_D_CONC_BOTTLE", "Fe_D_CONC_BOTTLE", "Cd_D_CONC_BOTTLE"}

    param_codes = {p["param_code"] for p in resp["params"]}
    assert param_codes == codes
    for p in resp["params"]:
        assert set(["param_code", "label", "unit", "family", "n_values"]).issubset(p.keys())


@pytest.mark.asyncio
async def test_by_id_404s_for_unknown_station(pool_and_router):
    spatial_v2 = pool_and_router
    with pytest.raises(HTTPException) as exc_info:
        await spatial_v2.geotraces_by_id("does-not-exist-" + _STATION)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_params_endpoint_returns_catalogue_ordered_by_n_values(pool_and_router):
    spatial_v2 = pool_and_router
    resp = await spatial_v2.geotraces_params()
    codes = [p["param_code"] for p in resp["params"]]
    assert "Mn_D_CONC_BOTTLE" in codes
    assert "Fe_D_CONC_BOTTLE" in codes
    assert "Cd_D_CONC_BOTTLE" in codes
    idx = {c: i for i, c in enumerate(codes)}
    assert idx["Mn_D_CONC_BOTTLE"] < idx["Fe_D_CONC_BOTTLE"] < idx["Cd_D_CONC_BOTTLE"]
