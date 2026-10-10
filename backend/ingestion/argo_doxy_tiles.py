# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""BGC-Argo O₂ map tiles, worker side: rebuild argo_doxy_tile_points + argo_doxy_cells from the live drawable
profiles as `_new` copies and swap them in with a new argo_doxy_source.tile_version (design 2026-10-10).

A LEAF for argo_doxy_worker: imports the rules, the DDL module and wod_casts_rules (numpy) only.
⛔ Never services.*, schema, domains or fastapi (tests/test_argo_doxy_worker_db.py checks the worker's imports).
⛔ argo_doxy_profiles is only READ. Every check runs before the swap: a mismatch leaves the live tiles and the version
as they are and no `_new` table behind.
Cells: level L = wod_casts_rules.lod_level(z) for z < POINT_MIN_ZOOM; a cell of level L is key >> 2*(20 - (6 + 2L)), the
same Morton prefix the tile route reads, so a cell, a tile and the pre-bake agree on which profiles a dot stands for."""
from __future__ import annotations

import asyncio
import logging
import math

import asyncpg
import numpy as np

from ingestion import argo_doxy_rules as A
from ingestion import wod_casts_rules as W
from ingestion.argo_doxy_ddl import (TILE_POINT_COLUMNS, cells_ddl, cells_index_names, tile_points_ddl,
                                     tile_points_index_ddl, tile_points_index_names)

log = logging.getLogger("argo_doxy_tiles")
POINTS, CELLS = "argo_doxy_tile_points", "argo_doxy_cells"
POINTS_NEW, CELLS_NEW = POINTS + "_new", CELLS + "_new"
COPY_CHUNK = 50_000
LOCK_BACKOFF = (10, 30, 60)          # four swap attempts at a 3 s lock_timeout (tile renders run <= 10 s)
_N = len(A.DISPLAY_DEPTHS)
_DRAWABLE_SQL = "SELECT profile_key, year, lat, lon, at_depth FROM argo_doxy_profiles WHERE drawable"

if A.LOD_LEVELS != tuple(sorted({W.lod_level(z) for z in range(A.POINT_MIN_ZOOM)})):
    raise RuntimeError("argo_doxy_rules.LOD_LEVELS disagrees with wod_casts_rules.lod_level below POINT_MIN_ZOOM")


class NothingToDraw(RuntimeError):
    """argo_doxy_profiles holds no drawable profile (before the first import, or after a purge): nothing is built."""


class TileBuildMismatch(RuntimeError):
    """A count disagrees (a level, a depth, or the live table moved under the build): nothing is swapped."""


def tile_point_records(rows) -> list[tuple]:
    """(profile_key, year, key, x, y, d) per drawable profile, in TILE_POINT_COLUMNS order."""
    if not rows:
        return []
    lon = np.fromiter((r["lon"] for r in rows), dtype=np.float64, count=len(rows))
    lat = np.fromiter((r["lat"] for r in rows), dtype=np.float64, count=len(rows))
    x, y = W.to_3857(lon, lat)
    keys = W.morton_key(x, y)
    out = []
    for r, k, xi, yi in zip(rows, keys.tolist(), x.tolist(), y.tolist()):
        d = [None if v is None or not math.isfinite(v) else int(round(v)) for v in r["at_depth"]]
        out.append((r["profile_key"], r["year"], k, xi, yi, d))
    return out


def cells_build_sql() -> list[str]:
    """Finest level from the points, every coarser level from the next finer one (a level is 2 bits per axis
    coarser = 4 Morton bits)."""
    top = A.LOD_LEVELS[-1]
    shift = 2 * (W.GRID_BITS - W.level_bits(top))
    s_pts = ", ".join(f"sum(p.d[{i}])::float8" for i in range(1, _N + 1))
    c_pts = ", ".join(f"nullif(count(p.d[{i}]), 0)::int" for i in range(1, _N + 1))
    s_cells = ", ".join(f"sum(w.s[{i}])" for i in range(1, _N + 1))
    c_cells = ", ".join(f"sum(w.c[{i}])::int" for i in range(1, _N + 1))
    out = [f"""INSERT INTO {CELLS_NEW} (level, cell, year, n, rep, sx, sy, s, c)
      SELECT {top}, (p.key >> {shift})::int, p.year, count(*)::int, max(p.profile_key),
             sum(p.x::float8), sum(p.y::float8), ARRAY[{s_pts}]::float8[], ARRAY[{c_pts}]::int[]
      FROM {POINTS_NEW} p GROUP BY 2, 3"""]
    for lv in reversed(A.LOD_LEVELS[:-1]):
        out.append(f"""INSERT INTO {CELLS_NEW} (level, cell, year, n, rep, sx, sy, s, c)
          SELECT {lv}, (w.cell >> 4)::int, w.year, sum(w.n)::int, max(w.rep), sum(w.sx), sum(w.sy),
                 ARRAY[{s_cells}]::float8[], ARRAY[{c_cells}]::int[]
          FROM {CELLS_NEW} w WHERE w.level = {lv + 1} GROUP BY 2, 3""")
    return out


async def _check(conn, n: int) -> dict[int, int]:
    """Every count the swap relies on; TileBuildMismatch on the first that disagrees."""
    n_live = await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles WHERE drawable")
    n_table = await conn.fetchval(f"SELECT count(*) FROM {POINTS_NEW}")
    if not n == n_live == n_table:
        raise TileBuildMismatch(f"read {n} drawable profiles, the live table holds {n_live}, {POINTS_NEW} {n_table}")
    per_level = {r["level"]: r["n"] for r in await conn.fetch(
        f"SELECT level, coalesce(sum(n), 0)::bigint AS n FROM {CELLS_NEW} GROUP BY level")}
    for lv in A.LOD_LEVELS:
        if per_level.get(lv, 0) != n:
            raise TileBuildMismatch(f"LOD level {lv} represents {per_level.get(lv, 0)} profiles, not {n}")
    if set(per_level) - set(A.LOD_LEVELS):
        raise TileBuildMismatch(f"unexpected LOD levels {sorted(set(per_level) - set(A.LOD_LEVELS))}")
    cols = ", ".join(f"count(d[{i}])::bigint" for i in range(1, _N + 1))
    want = list(await conn.fetchrow(f"SELECT {cols} FROM {POINTS_NEW}"))
    sums = ", ".join(f"coalesce(sum(c[{i}]), 0)::bigint" for i in range(1, _N + 1))
    for lv in A.LOD_LEVELS:
        got = list(await conn.fetchrow(f"SELECT {sums} FROM {CELLS_NEW} WHERE level = $1", lv))
        if got != want:
            raise TileBuildMismatch(f"LOD level {lv} per-depth counts {got} != profile values {want}")
    return {r["level"]: r["rows"] for r in await conn.fetch(
        f"SELECT level, count(*)::int AS rows FROM {CELLS_NEW} GROUP BY level ORDER BY level")}


async def _build(conn) -> tuple[int, dict[int, int], str]:
    """One REPEATABLE READ transaction: the read, the COPY and every check see one snapshot; a failure rolls the
    `_new` tables back with it."""
    async with conn.transaction(isolation="repeatable_read"):
        await conn.execute("SET LOCAL statement_timeout = 0")
        await conn.execute("SET LOCAL maintenance_work_mem = '256MB'")
        await conn.execute(f"DROP TABLE IF EXISTS {POINTS_NEW}, {CELLS_NEW}")
        for sql in tile_points_ddl(POINTS_NEW) + cells_ddl(CELLS_NEW):
            await conn.execute(sql)
        n = 0
        cur = await conn.cursor(_DRAWABLE_SQL)
        while True:
            rows = await cur.fetch(COPY_CHUNK)
            if not rows:
                break
            recs = tile_point_records(rows)
            await conn.copy_records_to_table(POINTS_NEW, records=recs, columns=TILE_POINT_COLUMNS)
            n += len(recs)
        if n == 0:
            raise NothingToDraw("argo_doxy_profiles holds no drawable profile")
        for sql in tile_points_index_ddl(POINTS_NEW) + cells_build_sql():
            await conn.execute(sql)
        level_rows = await _check(conn, n)
        await conn.execute(f"ANALYZE {POINTS_NEW}")
        await conn.execute(f"ANALYZE {CELLS_NEW}")
        loaded_at = await conn.fetchval("SELECT loaded_at FROM argo_doxy_source WHERE id = 1")
    return n, level_rows, f"{n}:{loaded_at.isoformat() if loaded_at else ''}"


async def _swap(conn, n: int, stamp: str) -> str:
    for attempt in range(len(LOCK_BACKOFF) + 1):
        try:
            async with conn.transaction():
                await conn.execute("SET LOCAL lock_timeout = '3s'")
                # Locks first, THEN the count: a purge that commits after a count taken earlier would otherwise be
                # overwritten by this swap (the dots of purged profiles come back). The profiles are locked in SHARE
                # mode (readers go on, writers wait; still never written) BEFORE the tile tables, the order a purge
                # takes them in (TRUNCATE profiles, then the tile tables): the opposite order could deadlock with it.
                await conn.execute("LOCK TABLE argo_doxy_profiles IN SHARE MODE")
                await conn.execute(f"LOCK TABLE {POINTS}, {CELLS} IN ACCESS EXCLUSIVE MODE")
                now_n = await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles WHERE drawable")
                if now_n != n:      # an import or a purge committed between the build and the swap
                    raise TileBuildMismatch(f"drawable profiles moved {n} -> {now_n} during the build")
                await conn.execute(f"DROP TABLE {POINTS}, {CELLS}")
                await conn.execute(f"ALTER TABLE {POINTS_NEW} RENAME TO {POINTS}")
                await conn.execute(f"ALTER TABLE {CELLS_NEW} RENAME TO {CELLS}")
                for old, new in (list(zip(tile_points_index_names(POINTS_NEW), tile_points_index_names(POINTS)))
                                 + list(zip(cells_index_names(CELLS_NEW), cells_index_names(CELLS)))):
                    await conn.execute(f'ALTER INDEX "{old}" RENAME TO "{new}"')
                # the CHECK on d was named after `_new` by Postgres (a numeric suffix is added when a name is taken)
                for chk in await conn.fetch("SELECT conname FROM pg_constraint WHERE conrelid = $1::regclass "
                                            "AND contype = 'c'", POINTS):
                    await conn.execute(f'ALTER TABLE {POINTS} RENAME CONSTRAINT "{chk["conname"]}" TO "{POINTS}_d_check"')
                version = await conn.fetchval(
                    """UPDATE argo_doxy_source SET
                         tile_version = to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYYMMDDHH24MISS') || '-' ||
                                        left(md5($1), 6),
                         tile_built_at = clock_timestamp()
                       WHERE id = 1 RETURNING tile_version""", stamp)
                if version is None:
                    raise TileBuildMismatch("argo_doxy_source row is missing")
                return version
        except asyncpg.exceptions.LockNotAvailableError:
            if attempt == len(LOCK_BACKOFF):
                raise
            await asyncio.sleep(LOCK_BACKOFF[attempt])
    raise AssertionError("unreachable")


async def rebuild_tiles(conn) -> dict:
    """Build, check, swap. Raises NothingToDraw / TileBuildMismatch / a DB error with the live tiles untouched."""
    n, level_rows, stamp = await _build(conn)
    try:
        version = await _swap(conn, n, stamp)
    except BaseException:
        try:
            await conn.execute(f"DROP TABLE IF EXISTS {POINTS_NEW}, {CELLS_NEW}")   # live tables intact; free the space
        except Exception:
            log.warning("argo-tiles: could not drop the unswapped _new tables", exc_info=True)
        raise
    return {"version": version, "n_points": n, "level_rows": level_rows}
