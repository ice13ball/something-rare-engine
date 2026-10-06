# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import csv
import datetime
import json
import pathlib
from collections import defaultdict

import asyncpg
import pytest

from plankton_helpers import conn, needs_db  # noqa: F401
from ingestion.glodap_bottles_rules import build_cast
from schema.glodap_bottles import ensure_glodap_bottles, casts_ddl, casts_index_ddl, cruises_ddl, CAST_COLUMNS

@needs_db
async def test_ensure_creates_three_tables_and_is_idempotent(conn):
    for t in ("glodap_casts", "glodap_cruises", "glodap_bottle_source"):
        await conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    await ensure_glodap_bottles(conn)
    await ensure_glodap_bottles(conn)
    for t in ("glodap_casts", "glodap_cruises", "glodap_bottle_source"):
        assert await conn.fetchval("SELECT to_regclass($1)", t) is not None
    assert await conn.fetchval("SELECT count(*) FROM glodap_bottle_source") == 1


@needs_db
async def test_cast_key_is_unique_and_flags_are_arrays_beside_values(conn):
    await conn.execute("DROP TABLE IF EXISTS glodap_casts CASCADE")
    for sql in casts_ddl("glodap_casts"):
        await conn.execute(sql)
    cols = {r["column_name"]: r["udt_name"] for r in await conn.fetch(
        "SELECT column_name, udt_name FROM information_schema.columns WHERE table_name='glodap_casts'")}
    assert cols["tco2"] == "_float4" and cols["tco2_f"] == "_int2" and cols["tco2_qc"] == "int2"
    assert cols["phtsinsitutp_f"] == "_int2" and "phtsinsitutp_qc" not in cols
    assert cols["levels"] == "jsonb"
    assert set(CAST_COLUMNS) <= set(cols)
    row = dict.fromkeys(CAST_COLUMNS)
    row.update(cast_key="X_1_1", expocode="X", station="1", cast_no=1, lat=0.0, lon=0.0, year=2000,
               obs_date=datetime.date(2000, 1, 1), time_precision="day", region=1,
               n_samples=1, n_good=0, depth_m=[1.0], levels="{}", pos_spread_km=0.0)
    rec = tuple(row[c] for c in CAST_COLUMNS)
    await conn.copy_records_to_table("glodap_casts", records=[rec], columns=list(CAST_COLUMNS))
    with pytest.raises(asyncpg.UniqueViolationError):
        await conn.copy_records_to_table("glodap_casts", records=[rec], columns=list(CAST_COLUMNS))


FIXCSV = pathlib.Path(__file__).parent / "fixtures" / "glodap_v3" / "glodapv3_excerpt.csv"


def _fixture_casts() -> list[dict]:
    by = defaultdict(list)
    with FIXCSV.open(newline="") as f:
        for row in csv.DictReader(f):
            by[(row["expocode"], row["station"], row["cast"])].append(row)
    return [c for c in (build_cast(rows) for rows in by.values()) if c is not None]


def test_cast_columns_are_exactly_what_build_cast_returns():
    casts = _fixture_casts()
    assert casts
    for c in casts:
        assert set(c) == set(CAST_COLUMNS)


@needs_db
async def test_real_fixture_casts_round_trip_through_staging_ddl(conn):
    # The loader builds `<table>_new` from the same DDL, so exercise a non-live name end to end.
    await conn.execute("DROP TABLE IF EXISTS glodap_casts_new CASCADE")
    for sql in casts_ddl("glodap_casts_new") + casts_index_ddl("glodap_casts_new"):
        await conn.execute(sql)
    casts = _fixture_casts()
    records = [tuple(json.dumps(c[col]) if col == "levels" else c[col] for col in CAST_COLUMNS) for c in casts]
    await conn.copy_records_to_table("glodap_casts_new", records=records, columns=list(CAST_COLUMNS))
    assert await conn.fetchval("SELECT count(*) FROM glodap_casts_new") == len(casts)
    # geom is generated from lon/lat, never loaded
    assert await conn.fetchval(
        "SELECT count(*) FROM glodap_casts_new WHERE ST_X(geom) <> lon OR ST_Y(geom) <> lat") == 0
    # a flag array sits beside every value array, same length (arrays stay index-aligned)
    assert await conn.fetchval(
        "SELECT count(*) FROM glodap_casts_new WHERE cardinality(tco2) <> cardinality(tco2_f) "
        "OR cardinality(tco2) <> cardinality(depth_m)") == 0
    assert await conn.fetchval("SELECT count(*) FROM glodap_casts_new WHERE n_samples <> cardinality(depth_m)") == 0


@needs_db
async def test_staging_ddl_creates_independent_tables_and_enforces_checks(conn):
    for t in ("glodap_cruises_new", "glodap_casts_new"):
        await conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    for sql in cruises_ddl("glodap_cruises_new"):
        await conn.execute(sql)
    await conn.execute(
        "INSERT INTO glodap_cruises_new (expocode, first_date, last_date, n_casts, first_cast_key, lat, lon) "
        "VALUES ('X', '2000-01-01', '2000-01-02', 1, 'X_1_1', 0, 0)")
    with pytest.raises(asyncpg.UniqueViolationError):
        await conn.execute(
            "INSERT INTO glodap_cruises_new (expocode, first_date, last_date, n_casts, first_cast_key, lat, lon) "
            "VALUES ('X', '2000-01-01', '2000-01-02', 1, 'X_1_1', 0, 0)")


@needs_db
async def test_source_row_is_a_singleton(conn):
    await ensure_glodap_bottles(conn)
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute("INSERT INTO glodap_bottle_source (id) VALUES (2)")
