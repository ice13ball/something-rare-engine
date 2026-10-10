# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""WOD23 casts (OSD, CTD, PFL): the API half of the wod-casts layer.

Routes: /v1/wod/tiles/{var}/{z}/{x}/{y}.pbf (the map), /v1/wod/cell/{z}/{x}/{y}/{q} (the casts one dot stands
for), /v1/wod/cast/{cast_id} (one cast) and /v1/wod/meta. The import runs in its own worker process; this module
only reads what the worker swapped in and records a force-sync request.

⛔ Never import the loader (`ingestion.wod_casts`), the parser (`ingestion.wod_casts_parse`) or the worker here, and
never netCDF4 at import time: the API reads its constants from the pure rules module, and
tests/test_wod_casts_api_db.py checks it in a fresh interpreter.
⛔ Missing and broken never share a path: an unknown key, an empty cell or an address outside the pyramid is a 404;
a database that cannot answer, a layer not built yet or a tile past its time limit is a 503 + Retry-After. Never an
empty 200 for a broken state.
⛔ Tile cache = disk, keyed on the data version and the variable / year range
(<root>/<version>/<var code>-<all|y0-y1>/z/x/y.pbf). Only the render path writes, and only under the version the
SAME statement returned with the bytes, so bytes in folder v are always v's bytes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from datetime import timezone

import asyncpg
import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

import db
from auth import get_api_key
from ingestion import wod_casts_rules as R
from services import wod_tiles as tiles
from services import woa_climatology
from sync_log import log_sync_skipped

log = logging.getLogger(__name__)
router = APIRouter()

PRODUCT = "World Ocean Database 2023 (WOD23) — OSD, CTD, PFL"
SOURCE_URL = "https://www.ncei.noaa.gov/products/world-ocean-database"
LICENCE = "Public use without restriction (NOAA NCEI)"
CITATION = (
    "Mishonov A.V., T. P. Boyer, O. K. Baranova, C. N. Bouchard, S. Cross, H. E. Garcia, R. A. Locarnini, "
    "C. R. Paver, J. R. Reagan, Z. Wang, D. Seidov, A. I. Grodsky, J. G. Beauchamp, (2024): World Ocean Database "
    "2023. C. Bouchard, Technical Ed., NOAA Atlas NESDIS 97, 206 pp., https://doi.org/10.25923/z885-h264")
ACCESSION_URL = "https://www.ncei.noaa.gov/archive/accession/{}"

_NOT_BUILT = {"Retry-After": "300", "Cache-Control": "no-store"}
_TOO_SLOW = {"Retry-After": "5", "Cache-Control": "no-store"}
_UNAVAILABLE = {"Retry-After": "60", "Cache-Control": "no-store"}
_MVT = "application/vnd.mapbox-vector-tile"
IMMUTABLE = "public, max-age=31536000, immutable"
SHORT = "public, max-age=60"

# The API pool is max_size=4: the semaphore is taken BEFORE a pool connection, so >= 2 connections stay free for
# every other endpoint however many cold tiles queue up.
_RENDER_SEM = asyncio.Semaphore(2)
_LIVE_TTL = 30.0
_live: tuple[str | None, float] = (None, 0.0)   # (live tile version, monotonic time it was learned)
_refreshing: asyncio.Task | None = None
_reconcile_task: asyncio.Task | None = None
_meta_cache: tuple[object, dict] | None = None   # (loaded_at the static part was built for, that part)


# ── live version (in-process, only ever downgrades caching) ───────────────────────────────────────────────
def _set_live_version(version: str | None) -> None:
    global _live
    _live = (version, time.monotonic())


def _live_version() -> str | None:
    version, at = _live
    return version if time.monotonic() - at < _LIVE_TTL else None


_WARN_EVERY_S = 300.0
_last_warn = float("-inf")


def _warn_version_refresh(e: Exception) -> None:
    """At most one line per _WARN_EVERY_S: the hit path retries on every request while the database is down."""
    global _last_warn
    now = time.monotonic()
    if now - _last_warn >= _WARN_EVERY_S:
        _last_warn = now
        log.warning("wod: could not refresh the live tile version (tiles stay on the short max-age): %s: %s",
                    type(e).__name__, e)


async def _refresh_live_version() -> None:
    try:
        async with db.pool.acquire() as conn:
            _set_live_version(await tiles.current_version(conn))
    except Exception as e:  # best effort: the hit path stays on the short max-age until a refresh works
        _warn_version_refresh(e)


def _refresh_live_version_soon() -> None:
    """Outside the hit path: when the in-process version is stale, refresh it in the background (one at a time)."""
    global _refreshing
    if _live_version() is None and db.pool is not None and (_refreshing is None or _refreshing.done()):
        _refreshing = asyncio.create_task(_refresh_live_version())


# ── cache sweep ───────────────────────────────────────────────────────────────────────────────────────────
async def _reconcile_disk_cache() -> None:
    """Read the live version, then drop every other version's directory; no live version (a psql purge set
    tile_version NULL) removes every version directory. A database that cannot answer leaves the disk alone."""
    if db.pool is None:
        return
    try:
        async with db.pool.acquire() as conn:
            live = await tiles.current_version(conn)
    except Exception:
        log.warning("wod tile cache reconcile: live version unreadable, disk left as it is")
        return
    _set_live_version(live)
    await asyncio.to_thread(tiles.drop_other_versions, tiles.cache_root(), live or "")


def clear_caches() -> None:
    """Admin cache sweep hook (registered in domains/__init__.py): the in-process state now, the disk cache in
    the background. Called synchronously with no running loop by the registry test: then only memory is cleared."""
    global _meta_cache, _live, _reconcile_task
    _meta_cache = None
    _live = (None, 0.0)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _reconcile_task = loop.create_task(_reconcile_disk_cache())


def _unavailable(what: str) -> HTTPException:
    return HTTPException(503, f"{what} temporarily unavailable", headers=_UNAVAILABLE)


def _not_built() -> HTTPException:
    return HTTPException(503, "wod casts are not built yet", headers=_NOT_BUILT)


# ── request parsing ───────────────────────────────────────────────────────────────────────────────────────
_INT = re.compile(r"[0-9]{1,9}", re.ASCII)
_YEAR_RE = re.compile(r"[0-9]{4}", re.ASCII)


def _years(y0: str | None, y1: str | None) -> tuple[int, int] | None:
    """Both or neither, four digits each, y0 <= y1; HTTPException(400) otherwise."""
    if y0 is None and y1 is None:
        return None
    if y0 is None or y1 is None or not _YEAR_RE.fullmatch(y0) or not _YEAR_RE.fullmatch(y1) or int(y0) > int(y1):
        raise HTTPException(400, "y0 and y1 must both be given as four-digit years with y0 <= y1")
    return int(y0), int(y1)


def _tile_response(data: bytes, cache_control: str) -> Response:
    headers = {"Cache-Control": cache_control}
    if not data:
        return Response(status_code=204, headers=headers)
    return Response(content=data, media_type=_MVT, headers=headers)


# Public names for the helpers domains/argo_oxygen_points.py shares with these tiles (one render budget, one status and
# year-parameter vocabulary for both tile families): rename or move any of them and that module breaks at API boot.
NOT_BUILT, TOO_SLOW, RENDER_SEM = _NOT_BUILT, _TOO_SLOW, _RENDER_SEM
parse_years, tile_response = _years, _tile_response


# ── tiles ─────────────────────────────────────────────────────────────────────────────────────────────────
@router.get("/v1/wod/tiles/{var}/{z}/{x}/{y}.pbf", dependencies=[Depends(get_api_key)])
async def wod_tile(var: str, z: int, x: int, y: int, v: str | None = None,
                   y0: str | None = None, y1: str | None = None) -> Response:
    """WOD23 cast map tile (MVT layer `wod`) for one variable (temperature, salinity, oxygen, phosphate,
    silicate, nitrate, nstar): below zoom 6 one dot per cell of a coarse grid, from zoom 6 one dot per 256 x 256
    cell of the tile (`q` cell, `k` casts, `id` one real cast, `a`/`b` first and last year, `d0`..`d7` the mean
    scaled value at the 8 display depths 0, 50, 100, 200, 500, 1000, 1500, 2000 m; absent where no cast has a
    good value). `y0`/`y1` limit the years. Read-through disk cache keyed on the live data version; immutable for
    the browser when `v` is that version. 404 for an unknown variable or an address outside the pyramid; 503 +
    Retry-After while nothing is built or the tile took too long. Data: NOAA NCEI World Ocean Database 2023,
    public use without restriction - cite Mishonov et al. (2024), https://doi.org/10.25923/z885-h264."""
    if var not in R.PICK_VARS:
        raise HTTPException(404, "unknown variable")
    years = _years(y0, y1)
    if not tiles.valid_tile(z, x, y):
        raise HTTPException(404, "tile outside the pyramid")
    root = tiles.cache_root()
    key = tiles.cache_key(var, years)
    # Hit path, NO database access: bytes in folder `v` are always version v's bytes. The in-process live
    # version is _LIVE_TTL old at most: a stale value can only downgrade the caching, never mislabel bytes.
    if v is not None and tiles.VERSION_RE.fullmatch(v):
        data = await asyncio.to_thread(tiles.read_cached, tiles.tile_path(root, v, key, z, x, y))
        if data is not None:
            _refresh_live_version_soon()
            return _tile_response(data, IMMUTABLE if _live_version() == v else SHORT)
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable", headers=_TOO_SLOW)
    try:
        async with db.pool.acquire() as conn:
            version = await tiles.current_version(conn)
    except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError):
        raise HTTPException(503, "database unavailable", headers=_TOO_SLOW) from None
    _set_live_version(version)
    if version is None:
        raise _not_built()
    path = tiles.tile_path(root, version, key, z, x, y)
    data = await asyncio.to_thread(tiles.read_cached, path)
    if data is None:
        try:
            async with _RENDER_SEM:
                data = await asyncio.to_thread(tiles.read_cached, path)   # another request may have just filled it
                if data is None:
                    async with db.pool.acquire() as conn:
                        version, data = await tiles.render(conn, var, z, x, y, years)
                    _set_live_version(version)
                    if version is None:
                        raise _not_built()
                    # Reached only with a COMPLETE render: a timed-out one raised and is never written.
                    path = tiles.tile_path(root, version, key, z, x, y)
                    if await asyncio.to_thread(tiles.write_cached, path, data):
                        tiles.note_write(root)
        except asyncpg.QueryCanceledError:
            raise HTTPException(503, "wod tile took too long, try again", headers=_TOO_SLOW) from None
        except asyncpg.UndefinedTableError:
            raise _not_built() from None
        except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError):
            log.exception("wod tile %s/%s/%s/%s", var, z, x, y)
            raise HTTPException(503, "database unavailable", headers=_TOO_SLOW) from None
    return _tile_response(data, IMMUTABLE if v == version else SHORT)


# ── helpers for the lookups ───────────────────────────────────────────────────────────────────────────────
def _num(x, ndigits: int = 7):
    """real / float8 -> a clean JSON number: float32 noise trimmed, NaN/inf -> None."""
    if x is None:
        return None
    x = float(x)
    if not math.isfinite(x):
        return None
    return float(f"{x:.{ndigits}g}")


def _iso(value):
    return value.isoformat() if value else None


def _js(value):
    return json.loads(value) if isinstance(value, str) else (value or {})


def _to_lonlat(mx: float, my: float) -> tuple[float, float]:
    return (mx / R.WORLD * 180.0, math.degrees(2 * math.atan(math.exp(my / R.R_EARTH)) - math.pi / 2))


# ── /v1/wod/cell/{z}/{x}/{y}/{q}?y0=&y1=&v= ───────────────────────────────────────────────────────────────
def _parse_cell(z: str, x: str, y: str, q: str) -> tuple[int, int, int, int]:
    """Malformed -> 400; well-formed but outside the pyramid or the tile's cell range -> 404."""
    if not all(_INT.fullmatch(s) for s in (z, x, y, q)):
        raise HTTPException(400, "malformed cell address")
    zi, xi, yi, qi = int(z), int(x), int(y), int(q)
    if not tiles.valid_cell(zi, xi, yi, qi):
        raise HTTPException(404, "cell outside the pyramid")
    return zi, xi, yi, qi


@router.get("/v1/wod/cell/{z}/{x}/{y}/{q}", dependencies=[Depends(get_api_key)])
async def wod_cell(z: str, x: str, y: str, q: str, y0: str | None = None, y1: str | None = None,
                   v: str | None = None):
    zi, xi, yi, qi = _parse_cell(z, x, y, q)
    years = _years(y0, y1)
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable", headers=_TOO_SLOW)
    try:
        async with _RENDER_SEM:
            async with db.pool.acquire() as conn:
                got = await tiles.cell_lookup(conn, zi, xi, yi, qi, years)
    except asyncpg.QueryCanceledError:
        raise HTTPException(503, "wod cell took too long, try again", headers=_TOO_SLOW) from None
    except asyncpg.UndefinedTableError:
        raise _not_built() from None
    except Exception:
        log.exception("wod cell %s/%s/%s/%s", z, x, y, q)
        raise HTTPException(503, "database unavailable", headers=_TOO_SLOW) from None
    version = got["version"]
    if version is None:
        raise _not_built()
    if not got["n_casts"]:
        raise HTTPException(404, "no drawable cast in this cell and year range")
    x0, y0m, x1, y1m = R.cell_bounds_3857(zi, xi, yi, qi)
    west, south = _to_lonlat(x0, y0m)
    east, north = _to_lonlat(x1, y1m)
    casts = [{**c, "lat": _num(c["lat"]), "lon": _num(c["lon"])} for c in got["casts"]]
    body = json.dumps({
        "z": zi, "x": xi, "y": yi, "q": qi, "version": version, "years": list(years) if years else None,
        "cell": {"west": round(west, 6), "south": round(south, 6), "east": round(east, 6), "north": round(north, 6)},
        "n_casts": got["n_casts"], "year_min": got["year_min"], "year_max": got["year_max"],
        "casts": casts, "truncated": got["n_casts"] > len(casts),
        "citation": CITATION, "source_url": SOURCE_URL, "licence": LICENCE, "product": PRODUCT,
    }, allow_nan=False)
    return Response(content=body, media_type="application/json",
                    headers={"Cache-Control": IMMUTABLE if v == version else SHORT})


# ── /v1/wod/cast/{cast_id}?var=&depth= ─────────────────────────────────────────────────────────────────────
_CAST_SQL = """SELECT w.*, f.url AS source_file_url FROM wod_casts w
               LEFT JOIN wod_files f ON f.file_id = w.file_id WHERE w.cast_id = $1"""


def _good(row, code: str, z: np.ndarray, depth_ok: np.ndarray):
    """(values float64 with NaN for no value, good mask) of one variable, or (None, None) when the variable was not
    measured, its profile flag is not 0, or its arrays do not line up with the depths."""
    arr, flags = row[code], row[f"{code}_f"]
    pflag = row["pflag"][R.VAR_CODE_TO_INDEX[code]]
    if arr is None or flags is None or pflag != 0 or len(arr) != len(z) or len(flags) != len(z):
        return None, None
    vals = np.array([math.nan if a is None else a for a in arr], dtype=np.float64)
    return vals, np.isfinite(vals) & (np.frombuffer(flags, dtype=np.uint8) == R.GOOD_FLAG) & depth_ok


def _picks(row) -> dict[str, list]:
    """The 8 display-depth values per variable, recomputed from the stored arrays with the SAME function the parser
    stored them with (R.pick_levels): the panel and the dot agree. N* = nitrate - 16 phosphate at the same level."""
    z = np.array(row["depth"], dtype=np.float64)
    depth_ok = np.isfinite(z) & (np.frombuffer(row["depth_flag"], dtype=np.uint8) == R.GOOD_FLAG)
    series: dict[str, tuple] = {}
    for code, _nc, var, _scale in R.VARS:
        series[var] = _good(row, code, z, depth_ok)
    nv, ng = series["nitrate"]
    pv, pg = series["phosphate"]
    series["nstar"] = ((nv - R.NSTAR_K * pv, ng & pg) if nv is not None and pv is not None else (None, None))
    out: dict[str, list] = {}
    for var in R.PICK_VARS:
        vals, good = series[var]
        if vals is None:
            out[var] = [None] * len(R.DEPTHS)
        else:
            out[var] = [None if i is None else _num(vals[i]) for i in R.pick_levels(z, good)]
    return out


def _levels(row) -> dict[str, list]:
    """{code: [[depth, value, flag], ...]} for the non-NULL elements of every measured variable."""
    out: dict[str, list] = {}
    for code, _nc, _var, _scale in R.VARS:
        arr, flags = row[code], row[f"{code}_f"]
        if arr is None or flags is None:
            continue
        rows = []
        for i, a in enumerate(arr):
            val = _num(a)
            if val is not None:
                rows.append([_num(row["depth"][i]), val, flags[i]])
        out[code] = rows
    return out


def _field_values(lat: float, lon: float, var: str) -> dict[str, float | None]:
    """The WOA23 annual climatology at the cast's position for the 8 display depths; None where the grid cannot
    answer. An auxiliary figure: an unreadable grid must not 503 a lookup."""
    out: dict[str, float | None] = {}
    for depth in R.DEPTHS:
        try:
            out[str(depth)] = _num(woa_climatology.sample_annual_point(var, lat, lon, float(depth)))
        except Exception:
            log.warning("wod field sample unavailable", exc_info=True)
            out[str(depth)] = None
    return out


def _cast_payload(row, var: str, depth: int | None, flag_meanings: dict, field: dict) -> dict:
    precision = row["time_precision"]
    cast_time = row["cast_time"]
    return {
        "cast_id": row["cast_id"], "instrument": row["instrument"], "dataset": row["dataset"],
        "cruise": row["cruise"], "orig_cruise": row["orig_cruise"], "platform": row["platform"],
        "vehicle": row["vehicle"], "wmo_id": row["wmo_id"], "institute": row["institute"],
        "project": row["project"], "country": row["country"], "t_instrument": row["t_instrument"],
        "o2_instrument": row["o2_instrument"], "real_time": row["real_time"],
        "date": _iso(row["cast_date"]),
        "time": (cast_time.astimezone(timezone.utc).strftime("%H:%M:%S")
                 if precision == "second" and cast_time is not None else None),
        "time_precision": precision,
        "lat": _num(row["lat"]), "lon": _num(row["lon"]),
        "access_no": row["access_no"],
        "accession_url": ACCESSION_URL.format(row["access_no"]) if row["access_no"] is not None else None,
        "source_file_url": row["source_file_url"],
        "levels": _levels(row), "depth_flag": list(row["depth_flag"]), "pflag": list(row["pflag"]),
        "n_src": list(row["n_src"]), "picks": _picks(row),
        "field": {"variable": var, "selected_depth": depth, "values": field},
        "flag_meanings": flag_meanings,
        "product": PRODUCT, "licence": LICENCE, "citation": CITATION, "source_url": SOURCE_URL,
    }


async def get_cast_payload(cast_id: int, var: str, depth: int | None) -> dict | None:
    """None when the cast is unknown (-> 404). Raises _not_built() when nothing is built, other errors -> 503."""
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(f"SET LOCAL statement_timeout = '{tiles.TILE_STATEMENT_TIMEOUT}'")
            row = await conn.fetchrow(_CAST_SQL, cast_id)
            src = await conn.fetchrow("SELECT tile_version, flag_meanings FROM wod_casts_source WHERE id = 1")
    if row is None:
        if src is None or src["tile_version"] is None:
            raise _not_built()
        return None
    flag_meanings = _js(src["flag_meanings"]) if src is not None else {}
    field = await asyncio.to_thread(_field_values, row["lat"], row["lon"], var)
    return _cast_payload(row, var, depth, flag_meanings, field)


@router.get("/v1/wod/cast/{cast_id}", dependencies=[Depends(get_api_key)])
async def wod_cast(cast_id: str, var: str = "temperature", depth: str | None = None):
    if not _INT.fullmatch(cast_id):
        raise HTTPException(400, "malformed cast id")
    if var not in R.PICK_VARS:
        raise HTTPException(400, "unknown variable")
    if depth is not None and not (depth.isascii() and depth.isdigit() and int(depth) in R.DEPTHS):
        raise HTTPException(400, f"depth must be one of {list(R.DEPTHS)}")
    if db.pool is None:
        raise _unavailable("WOD cast")
    try:
        p = await get_cast_payload(int(cast_id), var, None if depth is None else int(depth))
        body = None if p is None else json.dumps(p, allow_nan=False)
    except HTTPException:
        raise
    except asyncpg.UndefinedTableError:
        raise _not_built() from None
    except asyncpg.QueryCanceledError:
        raise HTTPException(503, "wod lookup took too long, try again", headers=_TOO_SLOW) from None
    except Exception:
        log.exception("wod cast %s", cast_id)
        raise _unavailable("WOD cast")
    if body is None:
        raise HTTPException(404, "cast not found")
    return Response(content=body, media_type="application/json", headers={"Cache-Control": SHORT})


# ── /v1/wod/meta ───────────────────────────────────────────────────────────────────────────────────────────
async def _health(conn, s) -> dict:
    """Read LIVE on every request (P35): the worker's own record in wod_casts_source plus the files that are not
    loaded. FAILING when the worker recorded a failure after the last swap, or a file is failed / blocked;
    missing files (gone from the source, data kept) are reported, not failing."""
    files = await conn.fetch(
        "SELECT url, instrument, year, status, failure, failed_at FROM wod_files "
        "WHERE status IN ('failed', 'blocked', 'missing') ORDER BY status, year, instrument LIMIT 50")
    counts = {st: await conn.fetchval("SELECT count(*) FROM wod_files WHERE status = $1", st)
              for st in ("failed", "blocked", "missing")}
    failed_at, loaded_at = s["last_failed_at"], s["loaded_at"]
    source_failing = failed_at is not None and (loaded_at is None or failed_at > loaded_at)
    if source_failing or counts["failed"] or counts["blocked"]:
        status = "failing"
    elif loaded_at is None:
        status = "not_loaded"
    else:
        status = "ok"
    return {
        "status": status, "failure": s["last_failure"], "failed_at": _iso(failed_at),
        "last_run_at": _iso(s["last_run_at"]), "last_decision": s["last_decision"],
        "last_rejects": _js(s["last_rejects"]), "last_rejects_at": _iso(s["last_rejects_at"]),
        "failed_files": counts["failed"], "blocked_files": counts["blocked"], "missing_files": counts["missing"],
        "files": [{"url": f["url"], "instrument": f["instrument"], "year": f["year"], "status": f["status"],
                   "failure": f["failure"], "failed_at": _iso(f["failed_at"])} for f in files],
    }


async def _static_meta(conn, s) -> dict:
    """The part that only changes with a swap (cached on loaded_at): the per-instrument arithmetic of the loaded
    files (source casts, stored, drawn and the reject counters that explain the difference)."""
    arithmetic: dict[str, dict] = {}
    for f in await conn.fetch("SELECT instrument, n_casts_source, n_stored, n_drawn, rejects FROM wod_files "
                              "WHERE status = 'loaded' ORDER BY instrument, file_id"):
        a = arithmetic.setdefault(f["instrument"], {"files": 0, "source": 0, "stored": 0, "drawn": 0, "rejects": {}})
        a["files"] += 1
        a["source"] += f["n_casts_source"] or 0
        a["stored"] += f["n_stored"] or 0
        a["drawn"] += f["n_drawn"] or 0
        for k, n in _js(f["rejects"]).items():
            if k not in ("source", "stored"):
                a["rejects"][k] = a["rejects"].get(k, 0) + int(n)
    return {
        "product": PRODUCT, "release": R.RELEASE, "licence": LICENCE, "source_url": SOURCE_URL,
        "citation": CITATION, "n_stored": s["n_stored"], "n_drawn": s["n_drawn"],
        "year_min": s["year_min"], "year_max": s["year_max"], "loaded_at": _iso(s["loaded_at"]),
        "tile_version": s["tile_version"], "tile_built_at": _iso(s["tile_built_at"]),
        "point_min_zoom": R.POINT_MIN_ZOOM, "variables": list(R.PICK_VARS), "depths": list(R.DEPTHS),
        "windows": [list(w) for w in R.WINDOWS], "scales": dict(R.SCALES),
        "lod_counts": _js(s["lod_counts"]), "arithmetic": arithmetic,
        "notes": ["Only casts with at least one accepted value (WOD flag 0) and a date are drawn; the others are "
                  "stored, not drawn.",
                  "A dot stands for all casts of the selected years in one cell; clicking it lists them. "
                  "Values at a display depth are the accepted value nearest to it inside its window."],
    }


@router.get("/v1/wod/meta", dependencies=[Depends(get_api_key)])
async def wod_meta():
    global _meta_cache
    try:
        async with db.pool.acquire() as conn:
            s = await conn.fetchrow("SELECT * FROM wod_casts_source WHERE id = 1")
            if s is None:
                raise _not_built()
            health = await _health(conn, s)
            cached = _meta_cache
            if cached is not None and cached[0] == s["loaded_at"] and cached[1]["tile_version"] == s["tile_version"]:
                static = cached[1]
            else:
                static = await _static_meta(conn, s)
                _meta_cache = (s["loaded_at"], static)
        body = json.dumps({**static, "health": health}, allow_nan=False)
    except HTTPException:
        raise
    except asyncpg.UndefinedTableError:
        raise _not_built() from None
    except Exception:
        log.exception("wod meta")
        raise _unavailable("WOD meta")
    return Response(content=body, media_type="application/json")


async def request_refresh() -> dict:
    """Admin force-sync: RECORD a request, never import. ⛔ The import runs in its own worker (own cgroup,
    MemoryMax); running it here would put a netCDF parse inside the 9G-capped API. The worker reads
    `refresh_requested_at` on its next timer tick."""
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE wod_casts_source SET refresh_requested_at = now() WHERE id = 1")
    await log_sync_skipped(R.SOURCE, "refresh requested; wod-casts worker runs it on its next timer tick")
    return {"requested": True}
