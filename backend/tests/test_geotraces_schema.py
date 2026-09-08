# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Executes ensure_geotraces() DDL against real PostGIS.

Guards the additive contract from the 2026-09-08 GEOTRACES full-parameter
audit: the new geotraces_params / geotraces_values tables and the new
geotraces_samples metadata columns must appear WITHOUT dropping, renaming or
altering the type of any legacy column the rest of the platform depends on
(MVT tiles, /v2/spatial/geotraces/by-id, export registry, nearest_obs,
GeotracesStationPanel.tsx, the element picker).
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)


async def _make_pool():
    import asyncpg

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    async with pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        await conn.execute("DROP TABLE IF EXISTS geotraces_values")
        await conn.execute("DROP TABLE IF EXISTS geotraces_params")
        await conn.execute("DROP TABLE IF EXISTS geotraces_samples")
        await conn.execute("DROP TABLE IF EXISTS geotraces_stations")
        await conn.execute("DROP TABLE IF EXISTS geotraces_param_units")
    return pool


async def _cols(conn, table):
    rows = await conn.fetch(
        """SELECT column_name, data_type FROM information_schema.columns
           WHERE table_name = $1""",
        table,
    )
    return {r["column_name"]: r["data_type"] for r in rows}


@pytest.mark.asyncio
async def test_new_tables_and_columns_created():
    from schema.geochem import ensure_geotraces

    pool = await _make_pool()
    try:
        async with pool.acquire() as conn:
            await ensure_geotraces(conn)

            params_cols = await _cols(conn, "geotraces_params")
            assert params_cols["param_code"] == "text"
            assert params_cols["label"] == "text"
            assert params_cols["unit"] == "text"
            assert params_cols["family"] == "text"
            assert params_cols["n_values"] == "integer"

            values_cols = await _cols(conn, "geotraces_values")
            assert values_cols["sample_id"] == "text"
            assert values_cols["param_code"] == "text"
            assert values_cols["value"] == "double precision"
            assert values_cols["stddev"] == "double precision"
            assert values_cols["qc_flag"] == "smallint"

            # primary key is (sample_id, param_code)
            pk_cols = await conn.fetch(
                """SELECT a.attname FROM pg_index i
                   JOIN pg_attribute a ON a.attrelid = i.indrelid
                        AND a.attnum = ANY(i.indkey)
                   WHERE i.indrelid = 'geotraces_values'::regclass
                     AND i.indisprimary
                   ORDER BY a.attname"""
            )
            assert {r["attname"] for r in pk_cols} == {"sample_id", "param_code"}

            # index on param_code for "which stations measured X"
            idx = await conn.fetch(
                """SELECT indexname FROM pg_indexes
                   WHERE tablename = 'geotraces_values'"""
            )
            assert any("param" in r["indexname"] for r in idx)

            samples_cols = await _cols(conn, "geotraces_samples")
            new_meta_cols = {
                "geotraces_sample_id": "text",
                "sampling_device": "text",
                "cast_identifier": "text",
                "bodc_event_number": "integer",
                "bodc_bottle_number": "integer",
                "rosette_bottle_number": "integer",
                "bottle_flag": "text",
                "ship_name": "text",
                "cruise_period": "text",
                "chief_scientist": "text",
                "geotraces_scientist": "text",
                "operators_cruise_name": "text",
                "cruise_information_link": "text",
                "bodc_cruise_number": "integer",
                "ncbi_metagenome_biosample": "text",
                "ncbi_single_cell_genome_bioproject": "text",
                "ncbi_rrna_biosample": "text",
                "embl_ebi_metagenome_analysis": "text",
            }
            for col, expected_type in new_meta_cols.items():
                assert col in samples_cols, f"missing column {col}"
                assert samples_cols[col] == expected_type, (
                    f"{col} is {samples_cols[col]}, expected {expected_type}"
                )
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_ddl_is_idempotent():
    from schema.geochem import ensure_geotraces

    pool = await _make_pool()
    try:
        async with pool.acquire() as conn:
            await ensure_geotraces(conn)
            await ensure_geotraces(conn)  # must not raise
            cols = await _cols(conn, "geotraces_samples")
            assert "geotraces_sample_id" in cols
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_legacy_columns_still_present():
    """Regression guard for the additive contract: nothing consumer code
    depends on may be dropped or renamed."""
    from schema.geochem import ensure_geotraces

    pool = await _make_pool()
    try:
        async with pool.acquire() as conn:
            await ensure_geotraces(conn)

            samples_cols = await _cols(conn, "geotraces_samples")
            for col in (
                "sample_id", "mn_d", "fe_d", "co_d", "ni_d", "cu_d",
                "mn_d_qc", "fe_d_qc", "co_d_qc", "ni_d_qc", "cu_d_qc", "params",
            ):
                assert col in samples_cols, f"legacy column {col} missing"
            # legacy PK type must not have moved
            assert samples_cols["sample_id"] == "bigint"

            stations_cols = await _cols(conn, "geotraces_stations")
            for col in (
                "has_mn", "has_fe", "has_co", "has_ni", "has_cu",
                "mn_max", "fe_max", "co_max", "ni_max", "cu_max",
            ):
                assert col in stations_cols, f"legacy station column {col} missing"
    finally:
        await pool.close()
