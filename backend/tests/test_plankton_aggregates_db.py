# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""build_aggregates / validate_aggregates on the stage-1 fixture plus edge rows (real PostGIS).
The expected buckets are computed in PYTHON (_decade/_band), independently of decade_sql/band_sql."""
import re
from collections import Counter
from datetime import datetime, timezone

import asyncpg
import pytest

from ingestion import plankton_aggregates as agg
from plankton_helpers import conn, insert_staged, needs_db, row, stage_fixture  # noqa: F401
from schema.plankton import GRID_RES

SRC = "plankton_occurrences_new"


def _decade(year, cutoff):
    if year is None or year > cutoff:
        return -1
    if year < 1950:
        return 1940
    return year // 10 * 10


def _band(depth):
    if depth is None:
        return 3
    if depth <= 200:
        return 0
    if depth <= 1000:
        return 1
    return 2


def _edge_rows(cutoff):
    return [
        row("copepoda", 1.0, 1.0, year=None, depth=None),
        row("copepoda", 1.0, 1.0, year=cutoff + 1, depth=200.0),
        row("copepoda", 1.0, 1.0, year=cutoff, depth=200.5),
        row("diatoms", 2.0, 2.0, year=1949, depth=1000.0),
        row("diatoms", 2.0, 2.0, year=1950, depth=1000.5),
        row("euphausiacea", 180.0, 90.0, year=2015, depth=10.0),
        row("coccolithophores", -180.0, -90.0, year=2015, depth=10.0),
        row("dinoflagellates", 10.0000001, 20.0, year=2015, edna=True),
        row("dinoflagellates", 10.0000004, 20.0, year=2015, edna=True),
    ]


async def _built(conn, tmp_path):
    cutoff = datetime.now(timezone.utc).year
    await stage_fixture(conn, tmp_path)
    await insert_staged(conn, _edge_rows(cutoff))
    async with conn.transaction():
        version = await agg.build_aggregates(conn, SRC)
    return cutoff, version


async def _place(conn, key):
    return {(r[0], r[1]): r[2] for r in await conn.fetch(
        "SELECT f.decade, f.depth_band, sum(f.n) FROM plankton_site_facets_new f "
        "JOIN plankton_sites_new s USING (site_id) WHERE s.site_key = $1 GROUP BY 1, 2", key)}


def test_version_is_sortable_unique_and_path_safe():
    a, b = agg.new_version(), agg.new_version()
    assert re.fullmatch(r"\d{14}-[0-9a-f]{6}", a) and a != b


@needs_db
async def test_every_facet_combination_sums_to_the_matching_row_count(conn, tmp_path):
    cutoff, _ = await _built(conn, tmp_path)
    want = Counter()
    for r in await conn.fetch(f"SELECT taxon_group, year, depth_m, is_edna FROM {SRC}"):
        want[(r["taxon_group"], _decade(r["year"], cutoff), _band(r["depth_m"]), r["is_edna"])] += 1
    assert sum(want.values()) > len(_edge_rows(cutoff))       # the fixture rows are in it too
    sites = {(r[0], r[1], r[2], r[3]): r[4] for r in await conn.fetch(
        "SELECT taxon_group, decade, depth_band, is_edna, sum(n) FROM plankton_site_facets_new GROUP BY 1, 2, 3, 4")}
    assert sites == dict(want)
    for res in GRID_RES:
        grid = {(r[0], r[1], r[2], r[3]): r[4] for r in await conn.fetch(
            "SELECT taxon_group, decade, depth_band, is_edna, sum(n) FROM plankton_grid_facets_new "
            "WHERE res = $1::real GROUP BY 1, 2, 3, 4", res)}
        assert grid == dict(want), res
    assert await agg.validate_aggregates(conn, SRC) == []


@needs_db
async def test_missing_and_future_values_land_in_their_own_buckets(conn, tmp_path):
    cutoff, _ = await _built(conn, tmp_path)
    assert await _place(conn, "1.000000,1.000000") == {(-1, 3): 1, (-1, 0): 1, (cutoff // 10 * 10, 1): 1}
    assert await _place(conn, "2.000000,2.000000") == {(1940, 1): 1, (1950, 2): 1}


@needs_db
async def test_a_record_of_2031_buckets_to_2030_and_the_build_passes_once_the_cutoff_reaches_it(conn, tmp_path, monkeypatch):
    """From 2030 the cutoff (the current year) admits 2030s rows: the decade CHECK must take them."""
    monkeypatch.setattr(agg, "CUTOFF_NOW_SQL", "2031")
    await stage_fixture(conn, tmp_path)
    await insert_staged(conn, [row("copepoda", 5.0, 5.0, year=2031, depth=10.0),
                               row("copepoda", 5.0, 5.0, year=2032, depth=10.0)])
    async with conn.transaction():
        await agg.build_aggregates(conn, SRC)
    assert await _place(conn, "5.000000,5.000000") == {(2030, 0): 1, (-1, 0): 1}
    assert await agg.validate_aggregates(conn, SRC) == []


@needs_db
async def test_the_map_edges_fall_into_the_last_cell_not_outside_the_world(conn, tmp_path):
    await _built(conn, tmp_path)
    cells = {(r[0], r[1], r[2]) for r in await conn.fetch(
        "SELECT res, ST_X(geom), ST_Y(geom) FROM plankton_grid_facets_new "
        "WHERE taxon_group IN ('euphausiacea', 'coccolithophores') AND decade = 2010")}
    assert {(1.0, 179.5, 89.5), (1.0, -179.5, -89.5), (0.25, 179.875, 89.875), (0.25, -179.875, -89.875)} <= cells
    assert await conn.fetchval(
        "SELECT count(*) FROM plankton_grid_facets_new WHERE abs(ST_X(geom)) > 180 OR abs(ST_Y(geom)) > 90") == 0
    assert await conn.fetchval(
        "SELECT count(*) FROM plankton_sites_new WHERE NOT ST_IsValid(geom_3857) "
        "OR abs(ST_Y(geom_3857)) > 20037509") == 0


@needs_db
async def test_a_place_is_lon_lat_rounded_to_six_decimals(conn, tmp_path):
    await _built(conn, tmp_path)
    got = await conn.fetch(
        "SELECT s.site_key, s.lon, s.lat, sum(f.n) AS n FROM plankton_sites_new s "
        "JOIN plankton_site_facets_new f USING (site_id) WHERE s.site_key = '10.000000,20.000000' GROUP BY 1, 2, 3")
    assert [(r["site_key"], r["lon"], r["lat"], r["n"]) for r in got] == [("10.000000,20.000000", 10.0, 20.0, 2)]
    assert await conn.fetchval("SELECT count(*) FROM plankton_sites_new") == await conn.fetchval(
        f"SELECT count(DISTINCT (round(lon::numeric, 6), round(lat::numeric, 6))) FROM {SRC}")


@needs_db
async def test_a_lost_facet_row_is_a_reason_not_a_silent_undercount(conn, tmp_path):
    await _built(conn, tmp_path)
    await conn.execute("DELETE FROM plankton_site_facets_new "
                       "WHERE ctid = (SELECT ctid FROM plankton_site_facets_new LIMIT 1)")
    await conn.execute("DELETE FROM plankton_tile_version_new")
    reasons = await agg.validate_aggregates(conn, SRC)
    assert any(r.startswith("aggregates: site facets hold") for r in reasons)
    assert "aggregates: no tile version" in reasons


@needs_db
async def test_require_valid_aggregates_raises_the_distinct_type_with_the_reasons(conn, tmp_path):
    await _built(conn, tmp_path)
    await agg.require_valid_aggregates(conn, SRC)          # clean build: silent
    await conn.execute("DELETE FROM plankton_grid_facets_new "
                       "WHERE ctid = (SELECT ctid FROM plankton_grid_facets_new LIMIT 1)")
    with pytest.raises(agg.AggregatesInvalid) as exc:
        await agg.require_valid_aggregates(conn, SRC)
    assert exc.value.reasons and all(r.startswith("aggregates: ") for r in exc.value.reasons)


@needs_db
async def test_an_infrastructure_error_propagates_unchanged_out_of_the_build(conn, tmp_path):
    await stage_fixture(conn, tmp_path)
    with pytest.raises(asyncpg.UndefinedTableError):       # not AggregatesInvalid, not swallowed
        async with conn.transaction():
            await agg.build_aggregates(conn, "plankton_no_such_table")
