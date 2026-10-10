# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""SOCAT v2026 observation points: the API half of the socat-points layer.

Routes: /v1/socat/tiles/{z}/{x}/{y}.pbf (the map), /v1/socat/obs/{obs_key} (one observation, its segment and
cruise), /v1/socat/cell/{z}/{x}/{y}/{q} (what one point feature stands for) and /v1/socat/meta. The import runs
in its own worker process; this module only reads what the worker swapped in and records a force-sync request.

⛔ Never import the loader (`ingestion.socat_points`: 9 GB of parser code) or the worker here: the API reads the
run-state constants from the pure rules module, and tests/test_socat_points_api_db.py checks it in a subprocess.
⛔ Missing and broken never share a path: an unknown key / empty cell is a 404; a database that cannot answer, a
layer not built yet or a tile past its time limit is a 503 + Retry-After. Never an empty 200 for a broken state.
⛔ Tile cache = disk, keyed on the data version (<root>/<version>/all/z/x/y.pbf). Only the render path writes, and
only under the version the SAME statement returned with the bytes, so bytes in folder v are always v's bytes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from datetime import timedelta

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

import db
from auth import get_api_key
from ingestion import socat_points_rules as R
from services import socat_tiles as tiles
from sync_log import log_sync_skipped

log = logging.getLogger(__name__)
router = APIRouter()

PRODUCT = "SOCAT v2026 (Surface Ocean CO2 Atlas)"
SOURCE_URL = "https://doi.org/10.25921/8dba-fr90"
METADATA_URL = "https://www.ncei.noaa.gov/data/oceans/ncei/ocads/metadata/0315110.html"
LICENCE = "CC BY 4.0"
CITATIONS = (
    "Bakker, D. C. E., Alin, S. R., Bates, N., et al. (2026). Surface Ocean CO2 Atlas Database Version 2026 "
    "(SOCATv2026) (NCEI Accession 0315110). NOAA NCEI. https://doi.org/10.25921/8dba-fr90",
    "Bakker, D. C. E., et al. (2016). A multi-decade record of high-quality fCO2 data in version 3 of the Surface "
    "Ocean CO2 Atlas (SOCAT). Earth System Science Data 8, 383-413. https://doi.org/10.5194/essd-8-383-2016",
)
CITATION = " — and ".join(CITATIONS)
ACKNOWLEDGEMENT = (
    "The Surface Ocean CO2 Atlas (SOCAT) is an international effort, endorsed by the SCOR Infrastructural Project "
    "International Ocean Carbon Coordination Project (IOCCP) and the Surface Ocean Lower-Atmosphere Study (SOLAS), "
    "to deliver a uniform, quality-controlled surface ocean CO2 database. The many researchers and funding agencies "
    "responsible for the collection of data and quality control are thanked for their contributions to SOCAT.")
FCO2_SRC_NOTE = ("fCO2rec_src is the SOCAT algorithm code (0 not generated, 1-14) that produced the recomputed "
                 "fCO2; see the SOCAT data documentation for the meaning of each code.")

_NOT_BUILT = {"Retry-After": "300", "Cache-Control": "no-store"}
_TOO_SLOW = {"Retry-After": "5", "Cache-Control": "no-store"}
_UNAVAILABLE = {"Retry-After": "60", "Cache-Control": "no-store"}
_MVT = "application/vnd.mapbox-vector-tile"
IMMUTABLE = "public, max-age=31536000, immutable"
SHORT = "public, max-age=60"
MAX_ZOOM = 12   # == socat_tiles.TILE_MAX_ZOOM (a test pins it): a literal, as the schema -> domains import cycle can leave socat_tiles half-imported here

# P4: the semaphore is taken BEFORE a pool connection (the API pool is max_size=4, so >= 2 connections stay free
# for every other endpoint however many cold tiles queue up).
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
    """Log a failed version refresh, at most once per _WARN_EVERY_S: the hit path retries on every request
    while the database is unreachable, and one line per request would bury the real cause."""
    global _last_warn
    now = time.monotonic()
    if now - _last_warn >= _WARN_EVERY_S:
        _last_warn = now
        log.warning("socat: could not refresh the live tile version (tiles stay on the short max-age): %s: %s",
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
        log.warning("socat tile cache reconcile: live version unreadable, disk left as it is")
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
    return HTTPException(503, "socat points are not built yet", headers=_NOT_BUILT)


# ── tiles ─────────────────────────────────────────────────────────────────────────────────────────────────
def _tile_response(data: bytes, cache_control: str) -> Response:
    headers = {"Cache-Control": cache_control}
    if not data:
        return Response(status_code=204, headers=headers)
    return Response(content=data, media_type=_MVT, headers=headers)


@router.get("/v1/socat/tiles/{z}/{x}/{y}.pbf", dependencies=[Depends(get_api_key)])
async def socat_tile(z: int, x: int, y: int, v: str | None = None) -> Response:
    """SOCAT v2026 map tile (MVT layer `socat`): reduced track pieces at z0-8, one point per (UTC year, cell of
    a 256x256 grid over the tile) from z9 (`k` observations, `c` cruises, mean `f`/`t`/`s`, `y` year, `q` cell,
    `e`/`n` first observation). Variable, decade and year range are filtered client-side. Read-through disk cache
    keyed on the live data version; immutable for the browser when `v` is that version. 503 + Retry-After while
    nothing is built or the tile took too long. Data: SOCAT v2026, CC BY 4.0 — Bakker et al. (2026),
    https://doi.org/10.25921/8dba-fr90."""
    if not (0 <= z <= MAX_ZOOM and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        raise HTTPException(400, "tile coordinates out of range")
    root = tiles.cache_root()
    # Hit path, NO database access: bytes in folder `v` are always version v's bytes. The in-process live
    # version is _LIVE_TTL old at most: a stale value can only downgrade the caching, never mislabel bytes.
    if v is not None and tiles.VERSION_RE.fullmatch(v):
        data = await asyncio.to_thread(tiles.read_cached, tiles.tile_path(root, v, z, x, y))
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
    path = tiles.tile_path(root, version, z, x, y)
    data = await asyncio.to_thread(tiles.read_cached, path)
    if data is None:
        try:
            async with _RENDER_SEM:
                data = await asyncio.to_thread(tiles.read_cached, path)   # another request may have just filled it
                if data is None:
                    async with db.pool.acquire() as conn:
                        version, data = await tiles.render(conn, z, x, y)
                    _set_live_version(version)
                    if version is None:
                        raise _not_built()
                    # Reached only with a COMPLETE render: a timed-out one raised and is never written.
                    path = tiles.tile_path(root, version, z, x, y)
                    if await asyncio.to_thread(tiles.write_cached, path, data):
                        tiles.note_write(root)
        except asyncpg.QueryCanceledError:
            raise HTTPException(503, "socat tile took too long, try again", headers=_TOO_SLOW) from None
        except asyncpg.UndefinedTableError:
            raise _not_built() from None
        except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError):
            log.exception("socat tile %s/%s/%s", z, x, y)
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


def _utc(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _field_value(lat: float, lon: float, year: int):
    """The gridded decadal fCO2 of the field layer at (lat, lon) for the decade of `year`; None before 1970 or
    when the grid cannot answer. The field is an auxiliary figure: an unreadable grid must not 503 a lookup."""
    idx = R.decade_index(year)
    if idx is None:
        return None
    try:
        from services import socat_co2          # lazy: numpy / netCDF are not needed to serve tiles
        return _num(socat_co2.sample("fco2", lat, lon, idx))
    except Exception:
        log.warning("socat field sample unavailable", exc_info=True)
        return None


# ── /v1/socat/obs/{obs_key} ───────────────────────────────────────────────────────────────────────────────
def _cruise_payload(c) -> dict:
    return {"expocode": c["expocode"], "platform_name": c["platform_name"], "dataset_name": c["dataset_name"],
            "pis": c["pis"], "qc_flag": c["qc_flag"], "version": c["version"], "source_doi": c["source_doi"],
            "source_reference": c["source_reference"], "metadata_docs": c["metadata_docs"],
            "first_time": _iso(c["first_time"]), "last_time": _iso(c["last_time"]), "n_obs": c["n_obs"],
            "west": _num(c["west"]), "east": _num(c["east"]), "south": _num(c["south"]), "north": _num(c["north"]),
            "crosses_antimeridian": c["crosses_antimeridian"]}


async def get_obs_payload(obs_key: str) -> dict | None:
    """None when the key is unknown (-> 404). Raises when the database cannot answer (-> 503)."""
    m = R.OBS_KEY_RE.fullmatch(obs_key)
    expocode, n = m.group(1), int(m.group(2))
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(f"SET LOCAL statement_timeout = '{tiles.TILE_STATEMENT_TIMEOUT}'")
            seg = await conn.fetchrow(
                "SELECT * FROM socat_segments WHERE expocode = $1 AND ord0 <= $2 ORDER BY ord0 DESC LIMIT 1",
                expocode, n)
            if seg is None or n >= seg["ord0"] + seg["n_obs"]:
                return None
            cruise = await conn.fetchrow("SELECT * FROM socat_cruises WHERE expocode = $1", expocode)
    if cruise is None:
        raise RuntimeError(f"segment of {expocode} has no cruise row")
    i = n - seg["ord0"]
    t0 = seg["t0"]
    times = [_utc(t0 + timedelta(seconds=s)) for s in seg["dt_s"]]
    lon, lat = seg["lon"][i], seg["lat"][i]
    year = (t0 + timedelta(seconds=seg["dt_s"][i])).year
    field = await asyncio.to_thread(_field_value, lat, lon, year)
    return {
        "obs_key": obs_key, "expocode": expocode, "ordinal": n,
        "time": times[i], "lon": _num(lon), "lat": _num(lat),
        "fco2_uatm": _num(seg["fco2"][i]), "sst_c": _num(seg["sst"][i]), "sal_pss78": _num(seg["sal"][i]),
        "fco2_src": seg["fco2_src"][i], "fco2_src_note": FCO2_SRC_NOTE, "fco2_flag": seg["fco2_flag"][i],
        "segment": {"ord0": seg["ord0"], "n_obs": seg["n_obs"], "index": i, "time": times,
                    "lon": [_num(v) for v in seg["lon"]], "lat": [_num(v) for v in seg["lat"]],
                    "fco2_uatm": [_num(v) for v in seg["fco2"]], "sst_c": [_num(v) for v in seg["sst"]],
                    "sal_pss78": [_num(v) for v in seg["sal"]], "fco2_flag": list(seg["fco2_flag"])},
        "field": {"fco2_decadal_uatm": field},
        "cruise": _cruise_payload(cruise),
        "citation": CITATION, "citations": list(CITATIONS), "acknowledgement": ACKNOWLEDGEMENT,
        "source_url": SOURCE_URL, "metadata_url": METADATA_URL, "licence": LICENCE, "product": PRODUCT,
    }


@router.get("/v1/socat/obs/{obs_key}", dependencies=[Depends(get_api_key)])
async def socat_obs(obs_key: str):
    if not R.OBS_KEY_RE.fullmatch(obs_key):
        raise HTTPException(400, "malformed observation key")
    if db.pool is None:
        raise _unavailable("SOCAT observation")
    try:
        p = await get_obs_payload(obs_key)
        body = None if p is None else json.dumps(p, allow_nan=False)
    except asyncpg.UndefinedTableError:
        raise _not_built() from None
    except asyncpg.QueryCanceledError:
        raise HTTPException(503, "socat lookup took too long, try again", headers=_TOO_SLOW) from None
    except Exception:
        log.exception("socat obs %s", obs_key)
        raise _unavailable("SOCAT observation")
    if body is None:
        raise HTTPException(404, "observation not found")
    return Response(content=body, media_type="application/json")


# ── /v1/socat/cell/{z}/{x}/{y}/{q}?year=&v= ───────────────────────────────────────────────────────────────
_INT = re.compile(r"[0-9]{1,9}", re.ASCII)
_YEAR_RE = re.compile(r"[0-9]{4}", re.ASCII)


def _parse_cell(z: str, x: str, y: str, q: str, year: str | None) -> tuple[int, int, int, int, int]:
    """Validate the path and the year; HTTPException(400) on anything malformed (never FastAPI's 422)."""
    if not all(_INT.fullmatch(s) for s in (z, x, y, q)) or year is None or not _YEAR_RE.fullmatch(year):
        raise HTTPException(400, "malformed cell address")
    zi, xi, yi, qi = int(z), int(x), int(y), int(q)
    lo, hi = tiles.CELL_MAX_ZOOM_SPAN
    if not (lo <= zi <= hi and 0 <= xi < 2 ** zi and 0 <= yi < 2 ** zi and 0 <= qi < tiles.CELLS ** 2):
        raise HTTPException(400, f"cell address out of range (zoom {lo}..{hi}, q 0..65535)")
    return zi, xi, yi, qi, int(year)


@router.get("/v1/socat/cell/{z}/{x}/{y}/{q}", dependencies=[Depends(get_api_key)])
async def socat_cell(z: str, x: str, y: str, q: str, year: str | None = None, v: str | None = None):
    zi, xi, yi, qi, yr = _parse_cell(z, x, y, q, year)
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable", headers=_TOO_SLOW)
    try:
        async with _RENDER_SEM:
            async with db.pool.acquire() as conn:
                got = await tiles.cell_lookup(conn, zi, xi, yi, qi, yr)
    except asyncpg.QueryCanceledError:
        raise HTTPException(503, "socat cell took too long, try again", headers=_TOO_SLOW) from None
    except asyncpg.UndefinedTableError:
        raise _not_built() from None
    except Exception:
        log.exception("socat cell %s/%s/%s/%s", z, x, y, q)
        raise HTTPException(503, "database unavailable", headers=_TOO_SLOW) from None
    version, tot = got["version"], got["tot"]
    if version is None:
        raise _not_built()
    if not tot["n_obs"]:
        raise HTTPException(404, "no drawable observation in this cell and year")
    x0, y0, x1, y1 = tiles.cell_bounds_3857(zi, xi, yi, qi)
    west, south = tiles.to_lonlat(x0, y0)
    east, north = tiles.to_lonlat(x1, y1)
    centre_lon, centre_lat = (west + east) / 2, (south + north) / 2
    field = await asyncio.to_thread(_field_value, centre_lat, centre_lon, yr)
    n_cruises = tot["n_cruises"]
    body = json.dumps({
        "z": zi, "x": xi, "y": yi, "q": qi, "year": yr, "version": version,
        "cell": {"west": round(west, 6), "south": round(south, 6), "east": round(east, 6), "north": round(north, 6)},
        "n_obs": tot["n_obs"], "n_cruises": n_cruises,
        "mean": {"fco2_uatm": _num(tot["f"]), "sst_c": _num(tot["tc"]), "sal_pss78": _num(tot["sa"])},
        "first_time": tot["first_time"], "last_time": tot["last_time"],
        "field": {"fco2_decadal_uatm": field},
        "cruises": got["cruises"], "cruises_truncated": n_cruises > len(got["cruises"]),
        "observations": got["observations"], "observations_truncated": tot["n_obs"] > len(got["observations"]),
        "citation": CITATION, "acknowledgement": ACKNOWLEDGEMENT, "source_url": SOURCE_URL, "licence": LICENCE,
    }, allow_nan=False)
    return Response(content=body, media_type="application/json",
                    headers={"Cache-Control": IMMUTABLE if v == version else SHORT})


# ── /v1/socat/meta ────────────────────────────────────────────────────────────────────────────────────────
async def _health(conn, s) -> dict:
    """Layer health from socat_points_source (the worker's own record), not from sync_log text. FAILING only
    when the worker recorded a failure and no import has succeeded since (the swap clears it). A swap that
    stored rejected rows is a note, not a failure: it is derived from `last_rejects`, which only the loader
    writes (sync_log.skipped_reason is overwritten by `request_refresh`, so it cannot carry the note)."""
    if s["last_failed_at"] is not None:
        status = "failing"
    elif s["loaded_at"] is None:
        status = "not_loaded"
    else:
        status = "ok"
    rejects = s["last_rejects"]
    rejects = json.loads(rejects) if isinstance(rejects, str) else (rejects or {})
    n_rej = rejects.get("rows") or 0
    return {
        "status": status, "failure": s["last_failure"], "failed_at": _iso(s["last_failed_at"]),
        "last_run_at": _iso(s["last_run_at"]), "last_decision": s["last_decision"],
        "last_rejects": rejects,
        "last_rejects_at": _iso(s["last_rejects_at"]),
        "swap_note": f"{R.SWAPPED_WITH_REJECTS_PREFIX}: {n_rej} rows rejected (stored, not drawn)" if n_rej else None,
    }


def _static_meta(s) -> dict:
    def js(v):
        return json.loads(v) if isinstance(v, str) else (v or {})
    return {
        "product": PRODUCT, "release": s["release"], "licence": LICENCE, "source_url": SOURCE_URL,
        "metadata_url": METADATA_URL, "citation": CITATION, "citations": list(CITATIONS),
        "acknowledgement": ACKNOWLEDGEMENT, "report_created": s["report_created"],
        "n_observations": s["n_rows_stored"], "n_rejected": s["n_rows_rejected"], "n_cruises": s["n_cruises"],
        "n_datasets_listed": s["n_datasets_listed"], "n_segments": s["n_segments"],
        "lod_counts": js(s["lod_counts"]), "qc_counts": js(s["qc_counts"]),
        "year_min": s["year_min"], "year_max": s["year_max"], "loaded_at": _iso(s["loaded_at"]),
        "tile_version": s["tile_version"], "tile_built_at": _iso(s["tile_built_at"]),
        "point_min_zoom": R.POINT_MIN_ZOOM,
        "notes": ["Only observations with WOCE flag 2 from datasets with QC flag A-D are drawn; other rows are "
                  "stored, not drawn.",
                  "From zoom 9 a dot stands for all observations of one UTC year in one small cell of the tile; "
                  "clicking it lists them."],
    }


@router.get("/v1/socat/meta", dependencies=[Depends(get_api_key)])
async def socat_meta():
    global _meta_cache
    try:
        async with db.pool.acquire() as conn:
            s = await conn.fetchrow("SELECT * FROM socat_points_source WHERE id = 1")
            if s is None:
                raise _not_built()
            health = await _health(conn, s)
        cached = _meta_cache
        if cached is not None and cached[0] == s["loaded_at"] and cached[1]["tile_version"] == s["tile_version"]:
            static = cached[1]
        else:
            static = _static_meta(s)
            _meta_cache = (s["loaded_at"], static)
        body = json.dumps({**static, "health": health}, allow_nan=False)
    except HTTPException:
        raise
    except asyncpg.UndefinedTableError:
        raise _not_built() from None
    except Exception:
        log.exception("socat meta")
        raise _unavailable("SOCAT meta")
    return Response(content=body, media_type="application/json")


async def request_refresh() -> dict:
    """Admin force-sync: RECORD a request, never import. ⛔ The import runs in its own worker (own cgroup,
    MemoryMax); running it here would put a 9 GB parse inside the 9G-capped API. The worker reads
    `refresh_requested_at` on its next timer tick."""
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE socat_points_source SET refresh_requested_at = now() WHERE id = 1")
    await log_sync_skipped(R.SOURCE, "refresh requested; socat-points worker runs it on its next timer tick")
    return {"requested": True}
