# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Pre-bake the unfiltered offshore-activities tile pyramid after each sync.

Tiles are written to:
  /var/cache/abyssal-tiles-raster/offshore-activities/_baked/{z}/{x}/{y}.png

The endpoint (spatial_v2.py) checks this directory first for unfiltered requests
and falls back to on-demand rendering for filtered views.

Atomic swap: tiles are rendered into _baked.tmp/ then the directory is replaced
atomically so live serving never reads a half-baked pyramid.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import shutil
import time
from pathlib import Path

from raster_tiles import render_tile

log = logging.getLogger("offshore_tile_baker")

# ⛔ Must resolve to the SAME root that routers/spatial_v2.py reads from — it
# honours RASTER_TILE_CACHE_DIR and this file used to hard-code the default.
# Setting that variable moved the reader and left the writer behind, so every
# baked tile landed where nothing would ever look for it: the fast path simply
# stopped hitting and every request fell through to on-demand rendering,
# silently and forever. Read the variable in both places or in neither.
_RASTER_ROOT = Path(os.getenv("RASTER_TILE_CACHE_DIR", "/var/cache/abyssal-tiles-raster"))
_BAKED_DIR = _RASTER_ROOT / "offshore-activities" / "_baked"
_TMP_DIR   = _RASTER_ROOT / "offshore-activities" / "_baked.tmp"
_Z_MAX     = 9      # z=0..9 → ~10k–18k tiles for clustered offshore polygons
_SEM_SIZE  = 8      # parallel render workers

_bake_lock = asyncio.Lock()
_pending   = False  # a re-bake was requested while one was already running


def _tile_xy(lon: float, lat: float, z: int) -> tuple[int, int]:
    """Convert lon/lat (degrees) to (x, y) slippy-tile indices at zoom z."""
    n = 1 << z
    x = int((lon + 180.0) / 360.0 * n)
    lat_r = math.radians(max(min(lat, 85.0511), -85.0511))
    y = int((1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n)
    return (max(0, min(x, n - 1)), max(0, min(y, n - 1)))


async def _collect_tiles(pool, z: int) -> set[tuple[int, int]]:
    """Return all (x, y) tiles at zoom z that contain ≥1 offshore polygon."""
    sql = """
        SELECT
            ST_XMin(ST_Envelope(geom)) AS lon_min,
            ST_YMin(ST_Envelope(geom)) AS lat_min,
            ST_XMax(ST_Envelope(geom)) AS lon_max,
            ST_YMax(ST_Envelope(geom)) AS lat_max
        FROM offshore_activities
        WHERE geom IS NOT NULL
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)

    n = 1 << z
    tiles: set[tuple[int, int]] = set()
    for row in rows:
        x0, y0 = _tile_xy(row["lon_min"], row["lat_max"], z)  # NW corner
        x1, y1 = _tile_xy(row["lon_max"], row["lat_min"], z)  # SE corner
        for tx in range(x0 - 1, x1 + 2):
            for ty in range(y0 - 1, y1 + 2):
                if 0 <= tx < n and 0 <= ty < n:
                    tiles.add((tx, ty))
    return tiles


async def _render_one(pool, z: int, x: int, y: int, dest: Path, sem: asyncio.Semaphore) -> None:
    async with sem:
        try:
            async with pool.acquire() as conn:
                png = await render_tile(z, x, y, types=None, conn=conn, countries=None)
            path = dest / str(z) / str(x) / f"{y}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(png)
        except Exception as exc:
            log.warning("bake failed z=%d x=%d y=%d: %s", z, x, y, exc)


async def bake_offshore_tiles(pool) -> int:
    """Render every (z, x, y) tile that contains ≥1 polygon for z=0.._Z_MAX.

    Writes to a temporary directory then atomically swaps with _BAKED_DIR.
    Returns the total number of tiles written.
    """
    t0 = time.monotonic()
    tmp = _TMP_DIR
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(_SEM_SIZE)
    total = 0

    for z in range(0, _Z_MAX + 1):
        tiles = await _collect_tiles(pool, z)
        tasks = [_render_one(pool, z, x, y, tmp, sem) for x, y in tiles]
        await asyncio.gather(*tasks)
        total += len(tiles)
        log.info("bake z=%d: %d tiles", z, len(tiles))

    # Atomic swap
    if _BAKED_DIR.exists():
        shutil.rmtree(_BAKED_DIR)
    shutil.move(str(tmp), str(_BAKED_DIR))

    elapsed = time.monotonic() - t0
    log.info("offshore-tile-baker: wrote %d tiles in %.1f s", total, elapsed)
    return total


async def schedule_bake(pool) -> None:
    """Debounced entry point called by _clear_offshore_tile_cache().

    If a bake is already running, sets a flag so it re-runs once complete.
    This collapses bursts of 23 sequential sync calls into at most 2 bakes.
    """
    global _pending

    if _bake_lock.locked():
        _pending = True
        return

    async def _run() -> None:
        global _pending
        async with _bake_lock:
            while True:
                _pending = False
                try:
                    await bake_offshore_tiles(pool)
                except Exception as exc:
                    log.error("offshore-tile-baker: bake failed: %s", exc)
                if not _pending:
                    break

    asyncio.create_task(_run())
