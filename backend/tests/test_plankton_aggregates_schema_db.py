# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Stage-2 aggregate tables: created by ensure_plankton, vocabulary enforced by CHECKs (real PostGIS)."""
import asyncpg
import pytest

from plankton_helpers import conn, needs_db  # noqa: F401  (conn is a fixture)
from schema.plankton import AGG_TABLES, DECADES, DEPTH_BANDS, GROUP_BITS, GROUPS, ensure_plankton


async def _fresh(conn):
    for t in AGG_TABLES:
        await conn.execute(f"DROP TABLE IF EXISTS {t}")
    await ensure_plankton(conn)


async def _rejected(conn, sql, *args):
    with pytest.raises(asyncpg.CheckViolationError):
        async with conn.transaction():
            await conn.execute(sql, *args)


def test_vocabulary_is_the_spec_vocabulary():
    assert DECADES == (-1, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020)
    assert DEPTH_BANDS == (0, 1, 2, 3)
    assert [GROUP_BITS[g] for g in GROUPS] == [1, 2, 4, 8, 16]


@needs_db
async def test_ensure_plankton_creates_the_four_aggregate_tables(conn):
    await _fresh(conn)
    for t in AGG_TABLES:
        assert await conn.fetchval("SELECT to_regclass($1)", t) is not None, t
    idx = {r[0] for r in await conn.fetch(
        "SELECT indexname FROM pg_indexes WHERE tablename = ANY($1::text[])", list(AGG_TABLES))}
    assert {"plankton_sites_geom3857_gix", "plankton_grid_facets_geom3857_gix"} <= idx


@needs_db
async def test_facet_checks_reject_values_outside_the_vocabulary(conn):
    await _fresh(conn)
    ins = ("INSERT INTO plankton_site_facets (site_id, taxon_group, decade, depth_band, is_edna, n) "
           "VALUES (1, $1, $2, $3, false, $4)")
    await conn.execute(ins, "copepoda", -1, 3, 1)        # no date, no depth: their own buckets
    await conn.execute(ins, "diatoms", 1940, 0, 1)
    await _rejected(conn, ins, "copepoda", 1930, 0, 1)
    await conn.execute(ins, "copepoda", 2030, 0, 1)      # future decades are valid once the cutoff reaches them
    await _rejected(conn, ins, "copepoda", 2110, 0, 1)
    await _rejected(conn, ins, "copepoda", 1930, 0, 1)
    await _rejected(conn, ins, "copepoda", 1955, 0, 1)
    await _rejected(conn, ins, "copepoda", 2010, 4, 1)
    await _rejected(conn, ins, "copepoda", 2010, 0, 0)
    await _rejected(conn, ins, "jellyfish", 2010, 0, 1)


@needs_db
async def test_tile_version_holds_one_well_formed_row(conn):
    await _fresh(conn)
    await conn.execute("INSERT INTO plankton_tile_version (id, version) VALUES (1, '20261007120000-a1b2c3')")
    with pytest.raises(asyncpg.UniqueViolationError):
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO plankton_tile_version (id, version) VALUES (1, '20261007120001-a1b2c3')")
    await _rejected(conn, "INSERT INTO plankton_tile_version (id, version) VALUES (2, '20261007120001-a1b2c3')")
    await _rejected(conn, "UPDATE plankton_tile_version SET version = '../etc'")
