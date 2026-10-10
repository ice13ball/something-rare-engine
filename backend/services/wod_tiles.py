# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""WOD23 cast tiles: the tile SQL, the cell lookup SQL and the disk cache (plankton's pure helpers).

No FastAPI here: the API route (domains/wod_casts.py) and the import worker's pre-bake share it.
⛔ Never import the loader (`ingestion.wod_casts`), the parser or the worker, and never netCDF4: this runs in the
9G-capped API process.

Below POINT_MIN_ZOOM a tile is drawn from `wod_cells` (LOD level z // 2: 64 x 64 cells per tile at an even zoom,
32 x 32 at an odd one). From POINT_MIN_ZOOM up it is drawn from `wod_cast_points`: one feature per 256 x 256 cell
of the tile. Both are ranges of ONE Morton key (wod_casts_rules), so a feature, the cell lookup behind it and the
pre-bake agree on which casts a dot stands for. A feature's properties: q (cell in the tile), k (casts), id (a
real cast of the cell), a/b (first / last year), d0..d7 (the mean scaled pick of the variable at the 8 display
depths; a depth without a pick has no property).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path

import asyncpg

from ingestion import wod_casts_rules as R
from services import plankton_tiles as pt

# Re-exported for the route and the pre-bake: one set of cache helpers, plankton's.
VERSION_RE = pt.VERSION_RE
read_cached = pt.read_cached
write_cached = pt.write_cached
drop_other_versions = pt.drop_other_versions
prune = pt.prune
BakeVersionChanged, BakeNoVersion = pt.BakeVersionChanged, pt.BakeNoVersion
BakeStopped, BakeConsecutiveTimeouts = pt.BakeStopped, pt.BakeConsecutiveTimeouts

# plankton's KEY_RE admits only its own keys, so the path builder is ours: <var code>-all or <code>-<y0>-<y1>.
KEY_RE = re.compile(r"[tsopinx]-(?:all|[0-9]{4}-[0-9]{4})")
TILE_STATEMENT_TIMEOUT = "10s"      # a long reader would hold up the LOD swap's ACCESS EXCLUSIVE lock
ALL_YEARS = (0, 9999)               # smallint-safe bounds that cover every stored year
MVT_EXTENT, MVT_BUFFER = 4096, 64
DEFAULT_CACHE_CAP = 1024 ** 3


def cache_root() -> Path:
    """Read at call time, so the worker unit and the tests can point it elsewhere."""
    return Path(os.getenv("WOD_TILE_CACHE_DIR", R.TILE_CACHE_DIR))


def cache_cap() -> int:
    return int(os.getenv("WOD_TILE_CACHE_CAP_BYTES", str(DEFAULT_CACHE_CAP)))


def cache_key(var: str, years: tuple[int, int] | None) -> str:
    code = R.VAR_CODE[var]
    return f"{code}-all" if years is None else f"{code}-{years[0]:04d}-{years[1]:04d}"


def tile_path(root: Path, version: str, key: str, z: int, x: int, y: int) -> Path:
    if not pt.VERSION_RE.fullmatch(version) or not KEY_RE.fullmatch(key):
        raise ValueError("unsafe tile cache path component")
    return root / version / key / str(int(z)) / str(int(x)) / f"{int(y)}.pbf"


# ── address checks: R.tile_key_range / R.cell_key_range validate nothing ───────────────────────────────
def valid_tile(z: int, x: int, y: int) -> bool:
    return 0 <= z <= R.TILE_MAX_ZOOM and 0 <= x < (1 << z) and 0 <= y < (1 << z)


def cells_per_tile(z: int) -> int:
    """Number of cells a tile of zoom z is divided into (q runs 0..this-1)."""
    return 4 ** (R.cell_bits(z) - z)


def valid_cell(z: int, x: int, y: int, q: int) -> bool:
    return valid_tile(z, x, y) and 0 <= q < cells_per_tile(z)


# ── the tile ─────────────────────────────────────────────────────────────────────────────────────────────
def _slots(var: str) -> list[int]:
    """1-based array positions of the variable's display depths in the 56-slot arrays."""
    return [R.slot(var, d) + 1 for d in range(len(R.DEPTHS))]


_HEAD = ("SELECT (SELECT tile_version FROM wod_casts_source WHERE id = 1) AS version, "
         f"(SELECT ST_AsMVT(m, 'wod', {MVT_EXTENT}, 'geom') FROM (")
_GEOM = ("ST_AsMVTGeom(ST_SetSRID(ST_MakePoint(g.mx, g.my), 3857), ST_TileEnvelope($6::int, $7::int, $8::int), "
         f"{MVT_EXTENT}, {MVT_BUFFER}, true) AS geom")
_PROPS = "g.q, g.k, g.id, g.a, g.b, " + ", ".join(f"g.d{k}" for k in range(len(R.DEPTHS)))


def lod_sql(var: str) -> str:
    """Parameters: $1 level, $2/$3 first / last+1 cell of the tile, $4/$5 year range, $6/$7/$8 z/x/y."""
    d = ", ".join(f"round(sum(r.s[{i}]) / nullif(sum(r.c[{i}]), 0))::int AS d{k}" for k, i in enumerate(_slots(var)))
    return f"""WITH r AS (SELECT * FROM wod_cells WHERE level = $1::smallint AND cell >= $2::int AND cell < $3::int
                         AND year BETWEEN $4::int AND $5::int),
      g AS (SELECT (r.cell - $2::int) AS q, sum(r.n)::int AS k, max(r.rep) AS id, min(r.year)::int AS a,
                   max(r.year)::int AS b, sum(r.sx) / sum(r.n) AS mx, sum(r.sy) / sum(r.n) AS my, {d}
            FROM r GROUP BY r.cell)
      {_HEAD} SELECT {_PROPS}, {_GEOM} FROM g) m) AS mvt"""


def points_sql(var: str, z: int) -> str:
    """Parameters: $1/$2 first / last+1 key of the tile, $3 the tile's first cell, $4/$5 year range, $6/$7/$8 z/x/y."""
    shift = 2 * (R.GRID_BITS - R.cell_bits(z))
    d = ", ".join(f"round(avg(p.picks[{i}]))::int AS d{k}" for k, i in enumerate(_slots(var)))
    return f"""WITH p AS (SELECT cast_id, year, key, x, y, picks FROM wod_cast_points
                         WHERE key >= $1::bigint AND key < $2::bigint AND year BETWEEN $4::int AND $5::int),
      g AS (SELECT ((p.key >> {shift}) - $3::bigint)::int AS q, count(*)::int AS k, max(p.cast_id) AS id,
                   min(p.year)::int AS a, max(p.year)::int AS b, avg(p.x) AS mx, avg(p.y) AS my, {d}
            FROM p GROUP BY 1)
      {_HEAD} SELECT {_PROPS}, {_GEOM} FROM g) m) AS mvt"""


def _clean(version: str | None) -> str | None:
    return version if version and VERSION_RE.fullmatch(version) else None


async def render(conn, var: str, z: int, x: int, y: int, years: tuple[int, int] | None,
                 timeout: str = TILE_STATEMENT_TIMEOUT) -> tuple[str | None, bytes]:
    """(version, MVT bytes) from ONE statement: the tile and the version it is filed under come from one
    snapshot, even if a swap commits in between. The statement timeout is SET LOCAL inside a transaction
    (outside one it is a no-op). Past it asyncpg.QueryCanceledError propagates and the caller must cache
    nothing. The caller has validated var and the address (`valid_tile`)."""
    y0, y1 = years or ALL_YEARS
    lo, hi = R.tile_key_range(z, x, y)
    if z >= R.POINT_MIN_ZOOM:
        shift = 2 * (R.GRID_BITS - R.cell_bits(z))
        sql, args = points_sql(var, z), (lo, hi, lo >> shift, y0, y1, z, x, y)
    else:
        lv = R.lod_level(z)
        s = 2 * (R.GRID_BITS - R.level_bits(lv))
        sql, args = lod_sql(var), (lv, lo >> s, hi >> s, y0, y1, z, x, y)
    async with conn.transaction():
        await conn.execute(f"SET LOCAL statement_timeout = '{timeout}'")
        row = await conn.fetchrow(sql, *args)
    return _clean(row["version"]), bytes(row["mvt"] or b"")


async def current_version(conn) -> str | None:
    """The live tile version, or None (nothing built yet, a purge, or the table is missing)."""
    try:
        async with conn.transaction():
            v = await conn.fetchval("SELECT tile_version FROM wod_casts_source WHERE id = 1")
    except asyncpg.UndefinedTableError:
        return None
    return _clean(v)


# ── the click lookup: which casts one feature stands for ────────────────────────────────────────────────
_CELL_SQL = f"""
WITH c AS MATERIALIZED (SELECT cast_id, year FROM wod_cast_points
                        WHERE key >= $1::bigint AND key < $2::bigint AND year BETWEEN $3::int AND $4::int)
SELECT (SELECT tile_version FROM wod_casts_source WHERE id = 1) AS version,
       (SELECT count(*) FROM c)::int AS n_casts,
       (SELECT min(year) FROM c)::int AS year_min, (SELECT max(year) FROM c)::int AS year_max,
       (SELECT coalesce(json_agg(json_build_object(
           'cast_id', t.cast_id, 'instrument', t.instrument, 'dataset', t.dataset,
           'date', to_char(t.cast_date, 'YYYY-MM-DD'), 'time_precision', t.time_precision, 'year', t.year,
           'cruise', t.cruise, 'wmo_id', t.wmo_id, 'platform', t.platform, 'vehicle', t.vehicle,
           'lat', t.lat, 'lon', t.lon) ORDER BY t.year DESC, t.cast_id DESC), '[]'::json)::text
        FROM (SELECT c.cast_id, c.year, w.instrument, w.dataset, w.cast_date, w.time_precision, w.cruise, w.wmo_id,
                     w.platform, w.vehicle, w.lat, w.lon
              FROM c JOIN wod_casts w ON w.cast_id = c.cast_id
              ORDER BY c.year DESC, c.cast_id DESC LIMIT {R.CAP_LIST}) t) AS casts"""


async def cell_lookup(conn, z: int, x: int, y: int, q: int, years: tuple[int, int] | None,
                      timeout: str = TILE_STATEMENT_TIMEOUT) -> dict:
    """The casts behind one feature: {version, n_casts, year_min, year_max, casts} with `casts` parsed, newest
    first and capped at CAP_LIST (n_casts stays exact). The caller has validated the address (`valid_cell`).
    QueryCanceledError propagates."""
    y0, y1 = years or ALL_YEARS
    lo, hi = R.cell_key_range(z, x, y, q)
    async with conn.transaction():
        await conn.execute(f"SET LOCAL statement_timeout = '{timeout}'")
        row = await conn.fetchrow(_CELL_SQL, lo, hi, y0, y1)
    return {"version": _clean(row["version"]), "n_casts": row["n_casts"], "year_min": row["year_min"],
            "year_max": row["year_max"], "casts": json.loads(row["casts"])}


# ── pre-bake (the import worker only, after a swap, still holding advisory lock 4242001) ────────────────
_HEAVY_SHIFT = 2 * (R.GRID_BITS - R.PREBAKE_HEAVY_MAX_ZOOM)
_HEAVY_SQL = f"SELECT (key >> {_HEAVY_SHIFT})::bigint AS t, count(*)::bigint AS n FROM wod_cast_points GROUP BY 1"


async def heavy_tiles(conn, min_casts: int = R.PREBAKE_HEAVY_CASTS) -> list[tuple[int, int, int]]:
    """Every (z, x, y) with POINT_MIN_ZOOM <= z <= PREBAKE_HEAVY_MAX_ZOOM holding at least `min_casts` drawable
    casts, in (z, x, y) order. One pass over wod_cast_points counted at the finest zoom and rolled up.
    ⛔ No statement timeout: this is the worker's own session, not a request."""
    async with conn.transaction():
        await conn.execute("SET LOCAL statement_timeout = 0")
        rows = await conn.fetch(_HEAVY_SQL)
    counts: dict[tuple[int, int, int], int] = {}
    for r in rows:
        tx, ty = R._compact(r["t"]), R._compact(r["t"] >> 1)
        for z in range(R.POINT_MIN_ZOOM, R.PREBAKE_HEAVY_MAX_ZOOM + 1):
            shift = R.PREBAKE_HEAVY_MAX_ZOOM - z
            key = (z, tx >> shift, ty >> shift)
            counts[key] = counts.get(key, 0) + r["n"]
    return sorted(k for k, n in counts.items() if n >= min_casts)


async def prebake(pool, root: Path) -> tuple[int, int]:
    """After a swap: drop every other version's directory, bake z0..PREBAKE_ALL_ZOOM plus the heavy
    POINT_MIN_ZOOM..PREBAKE_HEAVY_MAX_ZOOM tiles (`heavy_tiles`), for every variable and the all-years key,
    each under PREBAKE_TIMEOUT, into the cache of the CURRENT version, then prune to the cap. Tiles already
    on disk are skipped. Files are written only under the version render() returned WITH the bytes; a tile that
    times out is skipped, never written. Raises BakeVersionChanged, BakeNoVersion, BakeStopped (past
    PREBAKE_DEADLINE_S), BakeConsecutiveTimeouts, OSError (cache not writable) or a DB error.
    Returns (tiles written, tiles skipped because they timed out)."""
    started = time.monotonic()
    written = skipped = streak = 0
    async with pool.acquire() as conn:
        version = await current_version(conn)
        if version is None:
            raise BakeNoVersion("no wod tile version to bake")
        drop_other_versions(root, version)
        grid = [(z, x, y) for z in range(R.PREBAKE_ALL_ZOOM + 1) for x in range(2 ** z) for y in range(2 ** z)]
        grid += await heavy_tiles(conn)
        wanted = [(var, z, x, y) for var in R.PICK_VARS for z, x, y in grid]
        for var, z, x, y in wanted:
            path = tile_path(root, version, cache_key(var, None), z, x, y)
            if path.exists():
                continue
            if time.monotonic() - started >= R.PREBAKE_DEADLINE_S:
                raise BakeStopped("wod tile pre-bake deadline")
            try:
                got, data = await render(conn, var, z, x, y, None, R.PREBAKE_TIMEOUT)
            except asyncpg.QueryCanceledError:
                skipped += 1
                streak += 1
                if streak >= R.PREBAKE_MAX_CONSECUTIVE_TIMEOUTS:
                    raise BakeConsecutiveTimeouts("wod tile pre-bake: consecutive timeouts")
                continue
            streak = 0
            if got is None:
                raise BakeNoVersion("wod tile version missing during the bake")
            if got != version:
                raise BakeVersionChanged("wod tile version changed during the bake")
            if not write_cached(path, data):
                raise OSError("wod tile cache not writable")
            written += 1
    await asyncio.to_thread(prune, root, cache_cap())
    return written, skipped


# ── API write counter → one background prune per PRUNE_EVERY writes ─────────────────────────────────────
_writes = 0
_prune_task: asyncio.Task | None = None


def note_write(root: Path) -> None:
    """Count API cache writes; every PRUNE_EVERY-th starts one background prune (never two at once)."""
    global _writes, _prune_task
    _writes += 1
    if _writes % pt.PRUNE_EVERY or (_prune_task is not None and not _prune_task.done()):
        return
    _prune_task = asyncio.get_running_loop().create_task(asyncio.to_thread(prune, root, cache_cap()))
