# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""The tables ARE the parser: one column per source position, same order, same
kind — plus the version key, the source row number, raw cells and geometry."""
from ingestion import coastdom, greenland_pp
from pangaea_water_helpers import conn, needs_db  # noqa: F401  (conn is a fixture)

pytestmark = needs_db

_PG = {"text": "text", "date": "date", "float": "double precision", "flag": "smallint"}


async def _columns(conn, table):
    rows = await conn.fetch(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = $1 ORDER BY ordinal_position", table)
    return [(r["column_name"], r["data_type"]) for r in rows]


async def test_coastdom_samples_mirrors_the_49_source_columns(conn):
    want = ([("version_id", "bigint"), ("row_no", "integer")]
            + [(n, _PG[k]) for n, k in coastdom.COLUMNS]
            + [("raw", "ARRAY"), ("geom", "USER-DEFINED")])
    assert await _columns(conn, "coastdom_samples") == want


async def test_greenland_pp_stations_mirrors_the_6_source_columns(conn):
    want = ([("version_id", "bigint"), ("row_no", "integer")]
            + [(n, _PG[k]) for n, k in greenland_pp.COLUMNS]
            + [("raw", "ARRAY"), ("geom", "USER-DEFINED")])
    assert await _columns(conn, "greenland_pp_stations") == want


async def test_the_version_table_has_one_current_row_per_layer_at_most(conn):
    names = [r["indexname"] for r in await conn.fetch(
        "SELECT indexname FROM pg_indexes WHERE tablename = 'pangaea_dataset_version'")]
    assert "pangaea_dataset_version_one_current" in names


async def test_owner_is_abyssal_user_and_ensure_is_idempotent(conn):
    from schema.pangaea_water import ensure_pangaea_water
    await ensure_pangaea_water(conn)
    await ensure_pangaea_water(conn)
    owners = {r["tablename"]: r["tableowner"] for r in await conn.fetch(
        "SELECT tablename, tableowner FROM pg_tables WHERE tablename = ANY($1::text[])",
        ["pangaea_dataset_version", "coastdom_samples", "greenland_pp_stations"])}
    assert owners == dict.fromkeys(owners, "abyssal_user") and len(owners) == 3
    views = {r["viewname"]: r["viewowner"] for r in await conn.fetch(
        "SELECT viewname, viewowner FROM pg_views WHERE viewname = ANY($1::text[])",
        ["coastdom_samples_current", "greenland_pp_stations_current"])}
    assert views == {"coastdom_samples_current": "abyssal_user",
                     "greenland_pp_stations_current": "abyssal_user"}
