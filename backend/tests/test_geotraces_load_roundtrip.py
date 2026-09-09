# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""load() must actually execute against Postgres, with every column it names.

⛔ Found in production 2026-09-09, on the first full run and after four code
reviews: the geotraces_samples INSERT named 39 target columns and supplied 38
expressions ($1..$37 plus ST_SetSRID). Postgres answered

    asyncpg.exceptions.PostgresSyntaxError:
    INSERT has more target columns than expressions

The missing placeholder was $38 — `csv_row`, which is the join key
geotraces_values depends on. Nothing in the suite executed this statement, so
the defect survived every static check: the column list and the argument
tuple were both correct and both complete. Only the VALUES list was short,
and only Postgres can see that.

This test drives the real load() against real PostGIS with one sample.
"""
import json
import os
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)


def _sample(csv_row: int) -> dict:
    return {
        "station_id": "TEST-STN-1", "cruise": "TEST-CRUISE", "station": "1",
        "sample_time": datetime(2015, 6, 1, tzinfo=timezone.utc),
        "lat": 10.5, "lon": -20.25, "depth_m": 100.0, "bottom_depth_m": 4000.0,
        "mn_d": 1.1, "fe_d": 2.2, "co_d": None, "ni_d": None, "cu_d": 5.5,
        "mn_d_qc": 1, "fe_d_qc": 1, "co_d_qc": None, "ni_d_qc": None, "cu_d_qc": 2,
        "params": {"mn_d_sd": 0.1},
        "geotraces_sample_id": "", "sampling_device": "GO-FLO",
        "cast_identifier": "C1", "bodc_event_number": 4001,
        "bodc_bottle_number": 5001, "rosette_bottle_number": 7,
        "bottle_flag": "1", "ship_name": "RV Test", "cruise_period": "2015",
        "chief_scientist": "A. Person", "geotraces_scientist": "B. Person",
        "operators_cruise_name": "TST-01", "cruise_information_link": "https://example.org",
        "bodc_cruise_number": 12345, "ncbi_metagenome_biosample": None,
        "ncbi_single_cell_genome_bioproject": None, "ncbi_rrna_biosample": None,
        "embl_ebi_metagenome_analysis": None,
        "csv_row": csv_row,
    }


def _station() -> dict:
    return {
        "station_id": "TEST-STN-1", "cruise": "TEST-CRUISE", "station": "1",
        "sample_time": datetime(2015, 6, 1, tzinfo=timezone.utc),
        "lat": 10.5, "lon": -20.25, "decade": 2010, "n_samples": 2,
        "min_depth_m": 100.0, "max_depth_m": 200.0, "bottom_depth_m": 4000.0,
        "has_mn": True, "has_fe": True, "has_co": False, "has_ni": False, "has_cu": True,
        "mn_max": 1.1, "fe_max": 2.2, "co_max": None, "ni_max": None, "cu_max": 5.5,
    }


@pytest.fixture
async def pool():
    import asyncpg
    import db as _db
    import schema

    _db.pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    await schema.ensure_schema()
    yield _db.pool
    async with _db.pool.acquire() as c:
        await c.execute("TRUNCATE geotraces_samples, geotraces_stations, "
                        "geotraces_param_units, geotraces_params, geotraces_values")
    await _db.pool.close()


@pytest.mark.asyncio
async def test_load_executes_and_writes_csv_row(pool):
    """The whole point: run the statement Postgres will actually parse."""
    from ingestion import geotraces_ingest as gt

    samples = [_sample(11), _sample(12)]
    samples[1]["depth_m"] = 200.0
    params_meta = [{"param_code": "Fe_D_CONC", "unit": "nmol/kg", "family": "metals"}]

    inserted = await gt.load(pool, samples, [_station()], {"Fe_D_CONC": "nmol/kg"}, params_meta)
    assert inserted == 2

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT csv_row, ship_name, chief_scientist, bodc_cruise_number, params, "
            "       bodc_event_number, rosette_bottle_number, "
            "       ST_X(geom) lon, ST_Y(geom) lat "
            "FROM geotraces_samples ORDER BY csv_row")

    assert [r["csv_row"] for r in rows] == [11, 12], (
        "csv_row did not survive the INSERT. It is the join key geotraces_values "
        "uses; without it every measurement is orphaned."
    )
    # The 17 provenance columns are written by the same statement — if the
    # placeholder list ever slips again, these shift by one and land wrong.
    assert rows[0]["ship_name"] == "RV Test"
    assert rows[0]["chief_scientist"] == "A. Person"
    assert rows[0]["bodc_cruise_number"] == 12345
    assert rows[0]["bodc_event_number"] == 4001
    assert rows[0]["rosette_bottle_number"] == 7
    assert json.loads(rows[0]["params"]) == {"mn_d_sd": 0.1}
    assert rows[0]["lon"] == pytest.approx(-20.25)
    assert rows[0]["lat"] == pytest.approx(10.5)


@pytest.mark.asyncio
async def test_values_join_back_to_the_samples_load_wrote(pool):
    """geotraces_values.sample_id references geotraces_samples.csv_row."""
    from ingestion import geotraces_ingest as gt

    await gt.load(pool, [_sample(11)], [_station()], {}, None)

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO geotraces_values(sample_id, param_code, value, qc_flag) "
            "VALUES (11, 'Fe_D_CONC', 2.2, 1)")
        joined = await conn.fetchval(
            "SELECT count(*) FROM geotraces_values v "
            "JOIN geotraces_samples s ON s.csv_row = v.sample_id")

    assert joined == 1, (
        "a measurement did not join back to its bottle — csv_row is either "
        "missing or holds something other than the CSV row ordinal"
    )
