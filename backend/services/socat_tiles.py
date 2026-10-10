# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""SOCAT v2026 map tiles: the tile SQL, the cell lookup SQL and the disk cache (plankton's pure helpers).

No FastAPI here: the API route (domains/socat_points.py) and the import worker's pre-bake share it.
⛔ Never import the loader (`ingestion.socat_points`) or the worker: this runs in the 9G-capped API process.

Zooms below POINT_MIN_ZOOM draw LOD pieces (socat_lod). From POINT_MIN_ZOOM up a tile holds one feature per
(UTC year, 256x256 cell of the tile): see CELL_SQL. Every observation belongs to exactly ONE tile (half-open
envelope), so a cell id q is always 0..65535 and the click lookup (`cell_lookup`) can rebuild the same set.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import time
from pathlib import Path

import asyncpg

from ingestion import socat_points_rules as R
from services import plankton_tiles as pt

# Re-exported for the route and for the pre-bake (Task 6): one set of cache helpers, plankton's.
VERSION_RE = pt.VERSION_RE
read_cached = pt.read_cached
write_cached = pt.write_cached
drop_other_versions = pt.drop_other_versions
prune = pt.prune
# The pre-bake's give-up signals are plankton's (one vocabulary for both workers' sync_log outcomes).
BakeVersionChanged, BakeNoVersion = pt.BakeVersionChanged, pt.BakeNoVersion
BakeStopped, BakeConsecutiveTimeouts = pt.BakeStopped, pt.BakeConsecutiveTimeouts

KEY = "all"                         # the only cache key: variable, decade and year range are filtered client-side
TILE_MAX_ZOOM = 12                  # the map's MVTLayer maxZoom (the route refuses z > 12)
TILE_STATEMENT_TIMEOUT = "10s"      # a long reader would hold up the swap's ACCESS EXCLUSIVE lock
MVT_EXTENT, MVT_BUFFER = 4096, 64
_MARGIN = MVT_BUFFER / MVT_EXTENT   # the LOD envelope is the tile grown by the clip buffer, as ST_AsMVTGeom clips
CELLS = 256                         # cells per tile edge at z >= POINT_MIN_ZOOM
CELL_MAX_ZOOM_SPAN = (R.POINT_MIN_ZOOM, TILE_MAX_ZOOM)
CAP_CRUISES, CAP_OBSERVATIONS = 100, 1000
_LAT = repr(R.MERC_LAT)             # lat +-90 (06AQ20200801 reaches 90.0) is clamped before ST_Transform
_GOOD_QC = "('" + "','".join(sorted(R.GOOD_QC)) + "')"

WORLD = 20037508.342789244          # half the EPSG:3857 world, metres
_R_EARTH = 6378137.0


def cache_root() -> Path:
    """Read at call time, so the worker unit and the tests can point it elsewhere."""
    return Path(os.getenv("SOCAT_TILE_CACHE_DIR", "/var/cache/abyssal-socat-tiles"))


def tile_path(root: Path, version: str, z: int, x: int, y: int) -> Path:
    """<root>/<version>/all/<z>/<x>/<y>.pbf — plankton's checked path builder with our single key."""
    return pt.tile_path(root, version, KEY, z, x, y)


# ── cell grid ───────────────────────────────────────────────────────────────────────────────────────────
# ONE definition of "which cell is this observation in": cx/cy counted from the tile's west / NORTH edge
# (MVT y runs down), q = cy * 256 + cx. Used by the tile (grouping) and by the click lookup (filter).
CELL_SQL = ("(least(255, floor((o.x - ST_XMin(env.box)) / (ST_XMax(env.box) - ST_XMin(env.box)) * 256))::int"
            " + 256 * least(255, floor((ST_YMax(env.box) - o.y) / (ST_YMax(env.box) - ST_YMin(env.box)) * 256))::int)")


def cell_bounds_3857(z: int, x: int, y: int, q: int) -> tuple[float, float, float, float]:
    """(xmin, ymin, xmax, ymax) in metres of cell q of tile z/x/y: CELL_SQL inverted."""
    size = 2 * WORLD / (1 << z)
    w = size / CELLS
    cx, cy = q % CELLS, q // CELLS
    x0 = -WORLD + x * size + cx * w
    y1 = WORLD - y * size - cy * w
    return x0, y1 - w, x0 + w, y1


def to_lonlat(mx: float, my: float) -> tuple[float, float]:
    return (mx / WORLD * 180.0,
            math.degrees(2 * math.atan(math.exp(my / _R_EARTH)) - math.pi / 2))


# ── the observations of one tile (shared by the tile and by the cell lookup) ─────────────────────────────
# `{seg_extra}` is an extra segment-level predicate the cell lookup adds (its bbox and year prefilter).
# The LATERAL subquery carries OFFSET 0 so ST_Transform runs once per observation, not once per use.
_OBS_CTES = f"""
env AS (SELECT ST_TileEnvelope($1::int, $2::int, $3::int) AS box),
raw AS (
  SELECT s.expocode AS e, s.ord0 + o.i - 1 AS n, s.t0 + make_interval(secs => o.dt) AS ts,
         o.f, o.tc, o.sa, o.lon AS olon, o.lat AS olat, ST_X(o.g) AS x, ST_Y(o.g) AS y
  FROM env, socat_segments s
  CROSS JOIN LATERAL (
    SELECT u.*, ST_Transform(ST_SetSRID(ST_MakePoint(u.lon::float8, greatest(-{_LAT}::float8, least({_LAT}::float8, u.lat::float8))), 4326), 3857) AS g
    FROM unnest(s.lon, s.lat, s.dt_s, s.fco2, s.sst, s.sal, s.fco2_flag)
         WITH ORDINALITY AS u(lon, lat, dt, f, tc, sa, wf, i)
    OFFSET 0) o
  WHERE s.bbox && env.box AND s.qc_flag IN {_GOOD_QC} AND o.wf = 2 {{seg_extra}}
    AND ST_X(o.g) >= ST_XMin(env.box) AND ST_X(o.g) < ST_XMax(env.box)
    AND ST_Y(o.g) >  ST_YMin(env.box) AND ST_Y(o.g) <= ST_YMax(env.box))"""

_OBS_ALL = _OBS_CTES.format(seg_extra="")
_OBS_CELL = _OBS_CTES.format(
    seg_extra=("AND s.bbox && ST_MakeEnvelope($6::float8, $7::float8, $8::float8, $9::float8, 3857) "
               "AND s.year_min <= $5::int AND s.year_max >= $5::int"))

_YEAR = "extract(year FROM o.ts AT TIME ZONE 'UTC')::int"

_POINTS_SQL = f"""
WITH {_OBS_ALL},
cells AS (
  SELECT {_YEAR} AS y, {CELL_SQL} AS q,
         (array_agg(o.e ORDER BY o.ts, o.e, o.n))[1] AS e, (array_agg(o.n ORDER BY o.ts, o.e, o.n))[1] AS n,
         count(*) AS k, count(DISTINCT o.e) AS c, avg(o.f) AS f, avg(o.tc) AS tc, avg(o.sa) AS sa,
         avg(o.x) AS mx, avg(o.y) AS my
  FROM raw o, env GROUP BY 1, 2)
SELECT (SELECT tile_version FROM socat_points_source WHERE id = 1) AS version,
 (SELECT ST_AsMVT(m, 'socat', {MVT_EXTENT}, 'geom') FROM (
   SELECT c.e, c.n, c.k, c.c, c.q, round(c.f * 10)::int AS f, round(c.tc * 100)::int AS t,
          round(c.sa * 100)::int AS s, c.y,
          ST_AsMVTGeom(ST_SetSRID(ST_MakePoint(c.mx, c.my), 3857), env.box, {MVT_EXTENT}, {MVT_BUFFER}, true) AS geom
   FROM cells c, env) m) AS mvt"""


def _lod_sql(level: int) -> str:
    # The level is an int from lod_level(), written as a literal so the planner can use the partial index.
    return f"""
WITH env AS (SELECT ST_TileEnvelope($1::int, $2::int, $3::int) AS box,
                    ST_TileEnvelope($1::int, $2::int, $3::int, margin => {_MARGIN}) AS wide)
SELECT (SELECT tile_version FROM socat_points_source WHERE id = 1) AS version,
 (SELECT ST_AsMVT(m, 'socat', {MVT_EXTENT}, 'geom') FROM (
   SELECT l.expocode AS e, l.n0 AS n0, l.n_obs AS k, round(l.fco2 * 10)::int AS f, round(l.sst * 100)::int AS t,
          round(l.sal * 100)::int AS s, l.year AS y,
          ST_AsMVTGeom(l.geom, env.box, {MVT_EXTENT}, {MVT_BUFFER}, true) AS geom
   FROM env, socat_lod l
   WHERE l.level = {int(level)} AND l.qc_flag IN {_GOOD_QC} AND l.geom && env.wide) m) AS mvt"""


def _tile_sql(z: int) -> str:
    return _POINTS_SQL if z >= R.POINT_MIN_ZOOM else _lod_sql(R.lod_level(z))


def _clean(version: str | None) -> str | None:
    return version if version and VERSION_RE.fullmatch(version) else None


async def render(conn, z: int, x: int, y: int, timeout: str = TILE_STATEMENT_TIMEOUT) -> tuple[str | None, bytes]:
    """(version, MVT bytes) from ONE statement: the tile and the version it is filed under come from one
    snapshot, even if a swap commits in between. The statement timeout is SET LOCAL inside a transaction
    (outside one it is a no-op). Past it asyncpg.QueryCanceledError propagates and the caller must cache
    nothing. `timeout` is for the pre-bake (60 s, off the request path); a request keeps the default."""
    async with conn.transaction():
        await conn.execute(f"SET LOCAL statement_timeout = '{timeout}'")
        row = await conn.fetchrow(_tile_sql(z), z, x, y)
    return _clean(row["version"]), bytes(row["mvt"] or b"")


async def current_version(conn) -> str | None:
    """The live tile version, or None (nothing loaded yet, a purge, or the table is missing)."""
    try:
        async with conn.transaction():
            v = await conn.fetchval("SELECT tile_version FROM socat_points_source WHERE id = 1")
    except asyncpg.UndefinedTableError:
        return None
    return _clean(v)


# ── the click lookup: what one point feature stands for ───────────────────────────────────────────────────
_CELL_SQL = f"""
WITH {_OBS_CELL},
obs AS MATERIALIZED (
  SELECT o.* FROM raw o, env WHERE {_YEAR} = $5::int AND {CELL_SQL} = $4::int),
tot AS (SELECT count(*) AS n_obs, count(DISTINCT e) AS n_cruises, avg(f) AS f, avg(tc) AS tc, avg(sa) AS sa,
               min(ts) AS first_time, max(ts) AS last_time FROM obs),
cr AS (SELECT o.e, count(*) AS n_obs, (array_agg(o.n ORDER BY o.ts, o.n))[1] AS first_n,
              min(o.ts) AS first_time, max(o.ts) AS last_time FROM obs o GROUP BY o.e),
cr_top AS (SELECT cr.*, c.platform_name, c.qc_flag, c.dataset_name FROM cr JOIN socat_cruises c ON c.expocode = cr.e
           ORDER BY cr.n_obs DESC, cr.e LIMIT {CAP_CRUISES}),
ob AS (SELECT * FROM obs ORDER BY ts, e, n LIMIT {CAP_OBSERVATIONS})
SELECT (SELECT tile_version FROM socat_points_source WHERE id = 1) AS version,
 (SELECT json_build_object('n_obs', n_obs, 'n_cruises', n_cruises, 'f', f, 'tc', tc, 'sa', sa,
      'first_time', to_char(first_time AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
      'last_time', to_char(last_time AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'))::text FROM tot) AS tot,
 (SELECT coalesce(json_agg(json_build_object('expocode', e, 'platform_name', platform_name, 'qc_flag', qc_flag,
      'dataset_name', dataset_name, 'n_obs', n_obs, 'obs_key', e || '~' || first_n,
      'first_time', to_char(first_time AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
      'last_time', to_char(last_time AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'))
      ORDER BY n_obs DESC, e), '[]'::json)::text FROM cr_top) AS cruises,
 (SELECT coalesce(json_agg(json_build_object('obs_key', e || '~' || n,
      'time', to_char(ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
      'lon', round(olon::float8::numeric, 5), 'lat', round(olat::float8::numeric, 5),
      'fco2_uatm', f, 'sst_c', tc, 'sal_pss78', sa) ORDER BY ts, e, n), '[]'::json)::text FROM ob) AS observations"""


async def cell_lookup(conn, z: int, x: int, y: int, q: int, year: int, timeout: str = TILE_STATEMENT_TIMEOUT) -> dict:
    """The observations and cruises behind one point feature (tile z/x/y, cell q, UTC year): {version, tot,
    cruises, observations} with the three JSON parts parsed. Totals are exact; the lists are capped
    (CAP_CRUISES / CAP_OBSERVATIONS). QueryCanceledError propagates."""
    x0, y0, x1, y1 = cell_bounds_3857(z, x, y, q)
    pad = 1.0                                    # metres: a prefilter only, the exact test is q itself
    async with conn.transaction():
        await conn.execute(f"SET LOCAL statement_timeout = '{timeout}'")
        row = await conn.fetchrow(_CELL_SQL, z, x, y, q, year, x0 - pad, y0 - pad, x1 + pad, y1 + pad)
    return {"version": _clean(row["version"]), "tot": json.loads(row["tot"]),
            "cruises": json.loads(row["cruises"]), "observations": json.loads(row["observations"])}


# ── pre-bake (the import worker only, after a swap, still holding advisory lock 4242001) ─────────────────
# One pass over every drawable observation, counted at the heaviest pre-baked zoom and rolled up. The tile
# test is the same half-open envelope as _OBS_ALL (floor of the normalised Web-Mercator position). It is a
# threshold, so a boundary observation counted one tile over changes nothing that matters.
_HEAVY_N = 1 << R.PREBAKE_HEAVY_ZOOM
_HEAVY_SQL = f"""
SELECT least({_HEAVY_N - 1}, greatest(0, floor((u.lon::float8 + 180.0) / 360.0 * {_HEAVY_N})))::int AS x,
       least({_HEAVY_N - 1}, greatest(0, floor((1.0 - ln(tan(radians(c.la)) + 1.0 / cos(radians(c.la))) / pi())
             / 2.0 * {_HEAVY_N})))::int AS y,
       count(*)::bigint AS n
FROM socat_segments s
CROSS JOIN LATERAL unnest(s.lon, s.lat, s.fco2_flag) AS u(lon, lat, wf)
CROSS JOIN LATERAL (SELECT greatest(-{_LAT}::float8, least({_LAT}::float8, u.lat::float8)) AS la) c
WHERE s.qc_flag IN {_GOOD_QC} AND u.wf = 2
GROUP BY 1, 2"""


async def heavy_tiles(conn, min_obs: int = R.PREBAKE_HEAVY_OBS) -> list[tuple[int, int, int]]:
    """Every (z, x, y) with PREBAKE_ALL_ZOOM < z <= PREBAKE_HEAVY_ZOOM holding at least `min_obs` drawable
    observations, in (z, x, y) order. One unnest pass over socat_segments counted at the finest zoom and rolled
    up to the coarser ones. ⛔ No statement timeout: this is the worker's own session, not a request."""
    async with conn.transaction():
        await conn.execute("SET LOCAL statement_timeout = 0")
        rows = await conn.fetch(_HEAVY_SQL)
    counts: dict[tuple[int, int, int], int] = {}
    for r in rows:
        for z in range(R.PREBAKE_ALL_ZOOM + 1, R.PREBAKE_HEAVY_ZOOM + 1):
            shift = R.PREBAKE_HEAVY_ZOOM - z
            key = (z, r["x"] >> shift, r["y"] >> shift)
            counts[key] = counts.get(key, 0) + r["n"]
    return sorted(k for k, n in counts.items() if n >= min_obs)


async def prebake(pool, root: Path) -> tuple[int, int]:
    """After a swap: drop every other version's directory, then bake z0..PREBAKE_ALL_ZOOM plus the heavy
    z7..z10 tiles (`heavy_tiles`) into the cache of the CURRENT version, each under PREBAKE_TIMEOUT. Tiles
    already on disk are skipped. Files are written only under the version render() returned WITH the bytes;
    a tile that times out is skipped, never written. Raises BakeVersionChanged, BakeNoVersion, BakeStopped
    (past SOCAT_PREBAKE_DEADLINE_S), BakeConsecutiveTimeouts, OSError (cache not writable) or a DB error.
    Returns (tiles written, tiles skipped because they timed out)."""
    deadline = float(os.getenv("SOCAT_PREBAKE_DEADLINE_S", str(R.PREBAKE_DEADLINE_S)))
    started = time.monotonic()
    written = skipped = streak = 0
    async with pool.acquire() as conn:
        version = await current_version(conn)
        if version is None:
            raise BakeNoVersion("no socat tile version to bake")
        drop_other_versions(root, version)
        wanted = [(z, x, y) for z in range(R.PREBAKE_ALL_ZOOM + 1) for x in range(2 ** z) for y in range(2 ** z)]
        wanted += await heavy_tiles(conn)
        for z, x, y in wanted:
            path = tile_path(root, version, z, x, y)
            if path.exists():
                continue
            if time.monotonic() - started >= deadline:
                raise BakeStopped("socat tile pre-bake deadline")
            try:
                got, data = await render(conn, z, x, y, R.PREBAKE_TIMEOUT)
            except asyncpg.QueryCanceledError:
                skipped += 1
                streak += 1
                if streak >= R.PREBAKE_MAX_CONSECUTIVE_TIMEOUTS:
                    raise BakeConsecutiveTimeouts("socat tile pre-bake: consecutive timeouts")
                continue
            streak = 0
            if got is None:
                raise BakeNoVersion("socat tile version missing during the bake")
            if got != version:
                raise BakeVersionChanged("socat tile version changed during the bake")
            if not write_cached(path, data):
                raise OSError("socat tile cache not writable")
            written += 1
    await asyncio.to_thread(prune, root)
    return written, skipped


# ── API write counter → one background prune per PRUNE_EVERY writes ──────────────────────────────────────
_writes = 0
_prune_task: asyncio.Task | None = None


def note_write(root: Path) -> None:
    """Count API cache writes; every PRUNE_EVERY-th starts one background prune (never two at once)."""
    global _writes, _prune_task
    _writes += 1
    if _writes % pt.PRUNE_EVERY or (_prune_task is not None and not _prune_task.done()):
        return
    _prune_task = asyncio.get_running_loop().create_task(asyncio.to_thread(pt.prune, root))
