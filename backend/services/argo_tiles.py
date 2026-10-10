# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""BGC-Argo O₂ map tiles, API side (design 2026-10-10): the tile SQL, the disk cache paths and the worker's pre-bake.

No FastAPI here: the route (domains/argo_oxygen_points.py) and the worker's pre-bake share it.
⛔ Never import the loader (ingestion.argo_doxy), the reader, the worker or netCDF4.
Below POINT_MIN_ZOOM a tile is drawn from argo_doxy_cells (LOD level z // 2): one feature per cell, at the centroid of
its profiles — properties n (profiles), k (a real profile of the cell), a/b (first / last year), d0..d7 (mean whole
µmol/kg at the 8 display depths). From POINT_MIN_ZOOM one feature per profile from argo_doxy_tile_points — k (profile
key), a (year), d0..d7. A depth without a value has NO property (ST_AsMVT drops NULLs): the client draws it grey.
Both are ranges of ONE Morton key (wod_casts_rules), so cell, tile and pre-bake agree on which profiles a dot covers."""
from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path

import asyncpg

from ingestion import argo_doxy_rules as A
from ingestion import wod_casts_rules as W
from services import plankton_tiles as pt

# One set of cache helpers, plankton's (shared with the WOD tiles).
VERSION_RE = pt.VERSION_RE
read_cached = pt.read_cached
write_cached = pt.write_cached
drop_other_versions = pt.drop_other_versions
prune = pt.prune
BakeVersionChanged, BakeNoVersion = pt.BakeVersionChanged, pt.BakeNoVersion
BakeStopped, BakeConsecutiveTimeouts = pt.BakeStopped, pt.BakeConsecutiveTimeouts

# plankton's KEY_RE admits only its filter keys, so the path builder is ours: `all` or `<y0>-<y1>`.
KEY_RE = re.compile(r"all|[0-9]{4}-[0-9]{4}")
TILE_STATEMENT_TIMEOUT = pt.TILE_STATEMENT_TIMEOUT    # read at call time by render (the verification overrides it)
ALL_YEARS = (0, 9999)                                  # smallint-safe bounds covering every stored year
MVT_EXTENT, MVT_BUFFER = pt.MVT_EXTENT, pt.MVT_BUFFER
_N = len(A.DISPLAY_DEPTHS)


def cache_root() -> Path:
    """Read at call time, so the worker unit and a verification run can point it elsewhere."""
    return Path(os.getenv("ARGO_TILE_CACHE_DIR", "/var/cache/abyssal-argo-tiles"))


def cache_cap() -> int:
    return int(os.getenv("ARGO_TILE_CACHE_CAP_BYTES", str(A.TILE_CACHE_CAP_BYTES)))


def cache_key(years: tuple[int, int] | None) -> str:
    return "all" if years is None else f"{years[0]:04d}-{years[1]:04d}"


def tile_path(root: Path, version: str, key: str, z: int, x: int, y: int) -> Path:
    if not VERSION_RE.fullmatch(version) or not KEY_RE.fullmatch(key):
        raise ValueError("unsafe tile cache path component")
    return root / version / key / str(int(z)) / str(int(x)) / f"{int(y)}.pbf"


def valid_tile(z: int, x: int, y: int) -> bool:
    return 0 <= z <= A.TILE_MAX_ZOOM and 0 <= x < (1 << z) and 0 <= y < (1 << z)


_VERSION = "(SELECT tile_version FROM argo_doxy_source WHERE id = 1) AS version"
_MEANS = ", ".join(f"round(sum(r.s[{i + 1}]) / nullif(sum(r.c[{i + 1}]), 0))::int AS d{i}" for i in range(_N))
_CELL_D = ", ".join(f"g.d{i}" for i in range(_N))
_POINT_D = ", ".join(f"p.d[{i + 1}]::int AS d{i}" for i in range(_N))

# $1 level, $2/$3 first / last+1 cell of the tile, $4/$5 years, $6/$7/$8 z/x/y
LOD_SQL = f"""
WITH r AS (SELECT * FROM argo_doxy_cells WHERE level = $1::smallint AND cell >= $2::int AND cell < $3::int
                                         AND year BETWEEN $4::int AND $5::int),
     g AS (SELECT sum(r.n)::int AS n, max(r.rep) AS k, min(r.year)::int AS a, max(r.year)::int AS b,
                  sum(r.sx) / sum(r.n) AS mx, sum(r.sy) / sum(r.n) AS my, {_MEANS}
           FROM r GROUP BY r.cell)
SELECT {_VERSION}, (SELECT ST_AsMVT(m, 'argo', {MVT_EXTENT}, 'geom') FROM (
  SELECT g.n, g.k, g.a, g.b, {_CELL_D},
         ST_AsMVTGeom(ST_SetSRID(ST_MakePoint(g.mx, g.my), 3857), ST_TileEnvelope($6::int, $7::int, $8::int),
                      {MVT_EXTENT}, {MVT_BUFFER}, true) AS geom
  FROM g) m) AS mvt"""

# $1/$2 first / last+1 key of the tile, $3/$4 years, $5/$6/$7 z/x/y
POINTS_SQL = f"""
SELECT {_VERSION}, (SELECT ST_AsMVT(m, 'argo', {MVT_EXTENT}, 'geom') FROM (
  SELECT p.profile_key AS k, p.year::int AS a, {_POINT_D},
         ST_AsMVTGeom(ST_SetSRID(ST_MakePoint(p.x, p.y), 3857), ST_TileEnvelope($5::int, $6::int, $7::int),
                      {MVT_EXTENT}, {MVT_BUFFER}, true) AS geom
  FROM argo_doxy_tile_points p
  WHERE p.key >= $1::bigint AND p.key < $2::bigint AND p.year BETWEEN $3::int AND $4::int) m) AS mvt"""


def _clean(version: str | None) -> str | None:
    return version if version and VERSION_RE.fullmatch(version) else None


async def render(conn, z: int, x: int, y: int, years: tuple[int, int] | None,
                 timeout: str | None = None) -> tuple[str | None, bytes]:
    """(version, MVT bytes) from ONE statement, so the bytes and the version they are filed under come from one
    snapshot even if a swap commits in between. SET LOCAL inside a transaction (outside one it is a no-op). Past the
    timeout asyncpg.QueryCanceledError propagates and the caller caches nothing. The caller validated the address."""
    y0, y1 = years or ALL_YEARS
    lo, hi = W.tile_key_range(z, x, y)
    if z >= A.POINT_MIN_ZOOM:
        sql, args = POINTS_SQL, (lo, hi, y0, y1, z, x, y)
    else:
        lv = W.lod_level(z)
        s = 2 * (W.GRID_BITS - W.level_bits(lv))
        sql, args = LOD_SQL, (lv, lo >> s, hi >> s, y0, y1, z, x, y)
    async with conn.transaction():
        await conn.execute(f"SET LOCAL statement_timeout = '{timeout or TILE_STATEMENT_TIMEOUT}'")
        row = await conn.fetchrow(sql, *args)
    return _clean(row["version"]), bytes(row["mvt"] or b"")


async def current_version(conn) -> str | None:
    """The live tile version, or None (nothing built yet, a purge, the table or column missing)."""
    try:
        async with conn.transaction():
            v = await conn.fetchval("SELECT tile_version FROM argo_doxy_source WHERE id = 1")
    except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError):
        return None
    return _clean(v)


async def prebake(pool, root: Path) -> tuple[int, int]:
    """After a swap, in the worker, still holding advisory lock 4242001: drop every other version's directory, bake
    z0..PREBAKE_MAX_ZOOM for all years into the CURRENT version, skip tiles already on disk, prune to the cap. A file
    is written only under the version render() returned WITH its bytes; a tile that times out is never written.
    Raises BakeVersionChanged, BakeNoVersion, BakeStopped (deadline), BakeConsecutiveTimeouts, OSError (cache not
    writable) or a DB error. Returns (tiles written, tiles skipped because they timed out)."""
    started = time.monotonic()
    written = skipped = streak = 0
    async with pool.acquire() as conn:
        version = await current_version(conn)
        if version is None:
            raise BakeNoVersion("no argo tile version to bake")
        drop_other_versions(root, version)
        for z in range(A.PREBAKE_MAX_ZOOM + 1):
            for x in range(1 << z):
                for y in range(1 << z):
                    path = tile_path(root, version, cache_key(None), z, x, y)
                    if path.exists():
                        continue
                    if time.monotonic() - started >= A.PREBAKE_DEADLINE_S:
                        raise BakeStopped("argo tile pre-bake deadline")
                    try:
                        got, data = await render(conn, z, x, y, None, A.PREBAKE_TIMEOUT)
                    except asyncpg.QueryCanceledError:
                        skipped += 1
                        streak += 1
                        if streak >= A.PREBAKE_MAX_CONSECUTIVE_TIMEOUTS:
                            raise BakeConsecutiveTimeouts("argo tile pre-bake: consecutive timeouts") from None
                        continue
                    streak = 0
                    if got is None:
                        raise BakeNoVersion("argo tile version missing during the bake")
                    if got != version:
                        raise BakeVersionChanged("argo tile version changed during the bake")
                    if not write_cached(path, data):
                        raise OSError("argo tile cache not writable")
                    written += 1
    await asyncio.to_thread(prune, root, cache_cap())
    return written, skipped


_pruner = pt.PruneCounter(cache_cap)
note_write = _pruner.note_write
