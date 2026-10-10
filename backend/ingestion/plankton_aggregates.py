# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Stage-2 aggregates of plankton_occurrences: places, per-place facets, a 1° and a 0.25° grid, and the
tile version.

Built into `<table>_new` from any table with the plankton_occurrences shape (the import's
`plankton_occurrences_new`, or the live table for `--aggregates-only`) and swapped in by
ingestion/plankton_obis.py in the SAME transaction as the occurrences, so the map can never mix new counts
with an old grid. A missing value is its own bucket (decade -1, depth band 3), never 0 and never "surface".
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from schema.plankton import (
    AGG_DDL, AGG_TABLES, CUTOFF_NOW_SQL, GRID_FACETS, GRID_RES, MERC_LAT, SITE_FACETS, SITES, TILE_VERSION,
    aggregates_index_ddl, band_sql, decade_sql)

TMP = "plankton_facets_tmp"


def new_version() -> str:
    """`YYYYMMDDHHMMSS-xxxxxx` (UTC): sortable, unique per build, safe as a directory name."""
    return f"{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{secrets.token_hex(3)}"


def _merc(lon: str, lat: str) -> str:
    return (f"ST_Transform(ST_SetSRID(ST_MakePoint({lon}, "
            f"greatest(-{MERC_LAT}, least({MERC_LAT}, {lat}))), 4326), 3857)")


async def drop_aggregates(conn, suffix: str = "_new") -> None:
    for t in AGG_TABLES:
        await conn.execute(f"DROP TABLE IF EXISTS {t}{suffix}")


async def build_aggregates(conn, source: str) -> str:
    """Create and fill the four `_new` aggregate tables from `source`; return the new version.
    ⛔ Call it inside a transaction: a failure must leave no half-built `_new` table and no temp table."""
    await drop_aggregates(conn)
    for table, ddl in AGG_DDL:
        for sql in ddl(f"{table}_new"):
            await conn.execute(sql)
    await conn.execute(f"DROP TABLE IF EXISTS pg_temp.{TMP}")
    # One pass over the source: per rounded place x group x decade x depth band x eDNA.
    await conn.execute(f"""
        CREATE TEMP TABLE {TMP} AS
        SELECT round(lon::numeric, 6) AS rlon, round(lat::numeric, 6) AS rlat, taxon_group,
               {decade_sql('year', CUTOFF_NOW_SQL)} AS decade, {band_sql('depth_m')} AS depth_band,
               is_edna, count(*)::int AS n
        FROM {source}
        GROUP BY 1, 2, 3, 4, 5, 6""")
    await conn.execute(f"""
        INSERT INTO {SITES}_new (site_id, site_key, lon, lat, geom, geom_3857)
        SELECT (row_number() OVER (ORDER BY rlon, rlat))::int, rlon::text || ',' || rlat::text,
               rlon::float8, rlat::float8,
               ST_SetSRID(ST_MakePoint(rlon::float8, rlat::float8), 4326),
               {_merc('rlon::float8', 'rlat::float8')}
        FROM (SELECT DISTINCT rlon, rlat FROM {TMP}) d""")
    await conn.execute(f"""
        INSERT INTO {SITE_FACETS}_new (site_id, taxon_group, decade, depth_band, is_edna, n)
        SELECT s.site_id, t.taxon_group, t.decade, t.depth_band, t.is_edna, t.n
        FROM {TMP} t JOIN {SITES}_new s ON s.site_key = t.rlon::text || ',' || t.rlat::text""")
    for res in GRID_RES:
        r = repr(float(res))
        # lon 180 / lat 90 would open a cell outside the world: clamp them into the last cell.
        cx = f"least(floor(rlon::float8 / {r}), 180 / {r} - 1)::int"
        cy = f"least(floor(rlat::float8 / {r}), 90 / {r} - 1)::int"
        x, y = f"((c.cx + 0.5) * {r})::float8", f"((c.cy + 0.5) * {r})::float8"
        await conn.execute(f"""
            INSERT INTO {GRID_FACETS}_new
                (res, cell_x, cell_y, geom, geom_3857, taxon_group, decade, depth_band, is_edna, n)
            SELECT {r}::real, c.cx, c.cy, ST_SetSRID(ST_MakePoint({x}, {y}), 4326), {_merc(x, y)},
                   c.taxon_group, c.decade, c.depth_band, c.is_edna, sum(c.n)::int
            FROM (SELECT {cx} AS cx, {cy} AS cy, taxon_group, decade, depth_band, is_edna, n FROM {TMP}) c
            GROUP BY c.cx, c.cy, c.taxon_group, c.decade, c.depth_band, c.is_edna""")
    await conn.execute(f"DROP TABLE IF EXISTS pg_temp.{TMP}")
    version = new_version()
    await conn.execute(f"INSERT INTO {TILE_VERSION}_new (id, version) VALUES (1, $1)", version)
    for sql in aggregates_index_ddl("_new"):
        await conn.execute(sql)
    for t in (SITES, SITE_FACETS, GRID_FACETS):
        await conn.execute(f"ANALYZE {t}_new")
    return version


class AggregatesInvalid(Exception):
    """validate_aggregates returned reasons; `.reasons` carries them. The only failure the swap may treat as
    "discard the staging": infrastructure errors (asyncpg, cancellation) are never converted into this."""

    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


async def require_valid_aggregates(conn, source: str) -> None:
    reasons = await validate_aggregates(conn, source)
    if reasons:
        raise AggregatesInvalid(reasons)


async def validate_aggregates(conn, source: str) -> list[str]:
    """Reasons the `_new` aggregates must not go live (empty = OK): every row of `source` is counted
    exactly once in the place facets and in each grid, every facet has a place, and there is a version."""
    rows = await conn.fetchval(f"SELECT count(*) FROM {source}")
    reasons: list[str] = []
    held = await conn.fetchval(f"SELECT coalesce(sum(n), 0) FROM {SITE_FACETS}_new")
    if held != rows:
        reasons.append(f"aggregates: site facets hold {held} of {rows} rows")
    for res in GRID_RES:
        held = await conn.fetchval(
            f"SELECT coalesce(sum(n), 0) FROM {GRID_FACETS}_new WHERE res = {float(res)!r}::real")
        if held != rows:
            reasons.append(f"aggregates: {res} degree grid holds {held} of {rows} rows")
    orphans = await conn.fetchval(
        f"SELECT count(*) FROM {SITE_FACETS}_new f "
        f"WHERE NOT EXISTS (SELECT 1 FROM {SITES}_new s WHERE s.site_id = f.site_id)")
    if orphans:
        reasons.append(f"aggregates: {orphans} facets without a place")
    if await conn.fetchval(f"SELECT count(*) FROM {TILE_VERSION}_new") != 1:
        reasons.append("aggregates: no tile version")
    return reasons
