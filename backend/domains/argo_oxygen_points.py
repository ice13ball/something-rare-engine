# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""BGC-Argo DOXY "Measurements": the API half of the argo-oxygen-points layer (Measurements of oxygen-deox).

The import runs in argo_doxy_worker (own process). This module only reads argo_doxy_profiles and records a
force-sync request. ⛔ Never import ingestion.argo_doxy, ingestion.argo_doxy_sprof, argo_doxy_worker or netCDF4
here (tests/test_argo_oxygen_api_db.py checks it in a fresh interpreter).
⛔ Missing and broken never share a path: unknown key / depth -> 404; not loaded or database down -> 503 +
Retry-After, never a 200 with an empty body."""
from __future__ import annotations

import asyncio
import gzip
import json
import logging
import math
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response

import db
from auth import get_api_key
from ingestion.argo_doxy_rules import (BAD_POSITION_QC, BAD_TIME_QC, CITATIONS, DEPTH_WINDOWS, DISPLAY_DEPTHS, FIELD_PRODUCT, GOOD_ADJ_QC, KEY_RE,
                                       PRODUCT, RULES_VERSION, SOURCE, STARTED_PREFIX, STARTED_STALE,
                                       TRANSIENT_PREFIXES, UNITS, UPDATED_WITH_REJECTS_PREFIX, float_page_url,
                                       gdac_file_url)
from services import oxygen_deox
from sync_log import log_sync_skipped

log = logging.getLogger(__name__)
router = APIRouter()
CITATION = " ".join(CITATIONS)
SOURCE_HOME = "https://doi.org/10.17882/42182"
_RETRY_AFTER = {"Retry-After": "60"}
# One depth measured ~12 MiB raw on the real index; Cloud Run caps a response at 32 MiB BEFORE compression.
_RAW_WARN_BYTES = 24 * 2**20
# key (a depth, or "floats") -> (loaded_at stamp, gzipped document). The stamp makes the cache survive a load done by
# ANOTHER process (argo_doxy_worker cannot clear this process's memory): every request compares it with
# argo_doxy_source.loaded_at.
_doc_cache: dict[object, tuple[object, bytes]] = {}
_doc_lock = asyncio.Lock()
_FIELD_RETRY_S = 600.0
_field_retry_at = 0.0          # monotonic time before which an unavailable ISAS grid is not looked for again


class NotLoaded(Exception):
    """Nothing to serve yet (first import has not run). Private on purpose: a bare LookupError/KeyError from a bug
    in a builder must NOT be reported as "not loaded"."""


def clear_caches() -> None:
    global _field_retry_at
    _doc_cache.clear()
    _field_retry_at = 0.0


def _unavailable(what: str) -> HTTPException:
    return HTTPException(503, f"{what} temporarily unavailable", headers=_RETRY_AFTER)


def _num(x, nd: int = 7):
    """real[] / float4 -> a clean JSON number: float32 noise trimmed (7 significant digits), NaN/inf -> None."""
    if x is None:
        return None
    x = float(x)
    return float(f"{x:.{nd}g}") if math.isfinite(x) else None


def _assemble_points(rows, depth: int) -> tuple[bytes, int]:
    """CPU-bound; runs in a worker thread. One row per DRAWABLE profile; `value` is null (drawn grey) when the
    profile has no good adjusted sample inside the depth's window."""
    floats: list[str] = []
    fidx: dict[str, int] = {}
    fi, cycle, desc, lon, lat, year, value = [], [], [], [], [], [], []
    for n, row in enumerate(rows):
        pre = f"{row['dac']}_{row['platform_number']}"
        k = fidx.get(pre)
        if k is None:
            k = fidx[pre] = len(floats)
            floats.append(pre)
        fi.append(k)
        cycle.append(row["cycle_number"])
        if row["direction"] == "D":
            desc.append(n)
        lon.append(round(row["lon"], 3))
        lat.append(round(row["lat"], 3))
        year.append(row["year"])
        v = row["v"]
        value.append(int(round(v)) if v is not None and math.isfinite(v) else None)
    lo, hi = DEPTH_WINDOWS[depth]
    doc = json.dumps({"product": PRODUCT, "depth": depth, "window": [lo, hi], "units": UNITS, "n": len(fi),
                      "floats": floats, "fi": fi, "cycle": cycle, "descending": desc, "lon": lon, "lat": lat,
                      "year": year, "value": value}, separators=(",", ":"), allow_nan=False)
    return doc.encode(), len(fi)


async def _cached_document(key, build) -> bytes:
    """-> the gzipped document for `key`, rebuilt only when argo_doxy_source.loaded_at moved. `build` is an async
    callable returning (raw bytes, n); NotLoaded when nothing is loaded (an empty document is never cached)."""
    async with db.pool.acquire() as conn:
        stamp = await conn.fetchval("SELECT loaded_at FROM argo_doxy_source WHERE id = 1")
    if stamp is None:                   # read BEFORE the data: a load in between only makes us rebuild once more
        raise NotLoaded("argo_doxy_profiles not loaded yet")
    hit = _doc_cache.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    async with _doc_lock:
        hit = _doc_cache.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
        raw, n = await build()
        if n == 0:
            raise NotLoaded("argo_doxy_profiles holds no drawable profile")
        if len(raw) > _RAW_WARN_BYTES:
            log.warning("argo-oxygen %s: %d B raw — approaching Cloud Run's 32 MiB cap", key, len(raw))
        # Compressed ONCE here: the app-wide GZipMiddleware would re-compress every request, and leaves a response
        # that already carries Content-Encoding alone. Only the gzip is kept (8 depths x ~2.6 MiB + floats).
        gz = await asyncio.to_thread(gzip.compress, raw, 6)
        _doc_cache[key] = (stamp, gz)
        return gz


async def _build_points(depth: int) -> tuple[bytes, int]:
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT dac, platform_number, cycle_number, direction, lon, lat, year, at_depth[$1] AS v "
            "FROM argo_doxy_profiles WHERE drawable ORDER BY dac, platform_number, cycle_number, direction",
            DISPLAY_DEPTHS.index(depth) + 1)
    return await asyncio.to_thread(_assemble_points, rows, depth)


async def _serve(gz: bytes, request: Request, headers: dict) -> Response:
    if "gzip" in request.headers.get("accept-encoding", "").lower():
        return Response(content=gz, media_type="application/json", headers={**headers, "Content-Encoding": "gzip"})
    return Response(content=await asyncio.to_thread(gzip.decompress, gz), media_type="application/json",
                    headers=headers)


@router.get("/v1/argo-oxygen/points/{depth}", dependencies=[Depends(get_api_key)])
async def argo_oxygen_points(depth: int, request: Request):
    if depth not in DISPLAY_DEPTHS:
        raise HTTPException(404, "depth not offered")
    try:
        gz = await _cached_document(depth, lambda: _build_points(depth))
    except NotLoaded as e:               # expected before the first import: one line per request, no traceback
        log.warning("argo-oxygen points: %s", e)
        raise _unavailable("Argo O2 measurements (not loaded yet)")
    except Exception:
        log.exception("argo-oxygen points %s", depth)
        raise _unavailable("Argo O2 measurements")
    return await _serve(gz, request, {"Cache-Control": "public, max-age=3600", "Vary": "Accept-Encoding"})


def _field_recent(lat: float | None, lon: float | None) -> dict:
    """ISAS20 2014-2018 mean at this spot, per display depth. ⛔ Recent only: a single profile has no
    1971-2000 baseline, so no difference is ever computed for it. A field that cannot be read gives nulls: the
    measurement is still worth showing. An unavailable grid is remembered for _FIELD_RETRY_S, so a missing file
    does not rescan the data directory (nor a broken one re-open a 190 MB grid) on every request."""
    global _field_retry_at
    none = {str(d): None for d in DISPLAY_DEPTHS}
    if lat is None or lon is None or time.monotonic() < _field_retry_at:
        return none
    try:
        g = oxygen_deox.load_recent_grid()
        if g is None:
            _field_retry_at = time.monotonic() + _FIELD_RETRY_S
            log.warning("argo-oxygen: ISAS 2014-2018 field not available; retrying in %d s", _FIELD_RETRY_S)
            return none
        return {str(d): _num(oxygen_deox.nearest_grid_value(g.lats, g.lons, g.depths, g.data, lat, lon, float(d)))
                for d in DISPLAY_DEPTHS}
    except Exception as e:
        _field_retry_at = time.monotonic() + _FIELD_RETRY_S
        log.warning("argo-oxygen: ISAS field unreadable (%s: %s); retrying in %d s", type(e).__name__, e,
                    _FIELD_RETRY_S)
        return none


async def get_profile_payload(key: str) -> dict | None:
    """None when the key is unknown (-> 404). Raises when the database cannot answer (-> 503)."""
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM argo_doxy_profiles WHERE profile_key = $1", key)
    if row is None:
        return None
    field = await asyncio.to_thread(_field_recent, row["lat"], row["lon"])
    return {
        "profile_key": row["profile_key"], "argo_profile_id": row["argo_profile_id"], "dac": row["dac"],
        "platform_number": row["platform_number"], "cycle_number": row["cycle_number"],
        "direction": row["direction"], "lat": row["lat"], "lon": row["lon"], "position_qc": row["position_qc"],
        "profile_time": row["profile_time"].replace(microsecond=0).isoformat() if row["profile_time"] else None,
        "juld_qc": row["juld_qc"], "year": row["year"], "doxy_mode": row["doxy_mode"],
        "pres_source": row["pres_source"], "n_levels_source": row["n_levels_source"], "n_levels": row["n_levels"],
        "n_good": row["n_good"], "drawable": row["drawable"], "units": UNITS,
        "levels": {"pres_dbar": [_num(x) for x in row["pres_dbar"]], "depth_m": [_num(x) for x in row["depth_m"]],
                   "doxy_adj": [_num(x) for x in row["doxy_adj"]], "doxy_adj_qc": list(row["doxy_adj_qc"]),
                   "doxy_raw": [_num(x) for x in row["doxy_raw"]], "doxy_raw_qc": list(row["doxy_raw_qc"])},
        "at_depth": {str(d): ([_num(v), _num(z)] if v is not None else None)
                     for d, v, z in zip(DISPLAY_DEPTHS, row["at_depth"], row["at_depth_m"])},
        "depth_windows": {str(k): list(v) for k, v in DEPTH_WINDOWS.items()},
        "field_recent": field, "field_product": FIELD_PRODUCT, "product": PRODUCT,
        "good_qc": sorted(GOOD_ADJ_QC), "source_url": gdac_file_url(row["gdac_file"]),
        "float_url": float_page_url(row["platform_number"]), "source_home": SOURCE_HOME,
        "citation": CITATION, "citations": list(CITATIONS),
    }


@router.get("/v1/argo-oxygen/profile/{profile_key}", dependencies=[Depends(get_api_key)])
async def argo_oxygen_profile(profile_key: str):
    if not KEY_RE.match(profile_key):
        raise HTTPException(404, "profile not found")
    try:
        p = await get_profile_payload(profile_key)
        body = None if p is None else json.dumps(p, allow_nan=False)
    except Exception:
        log.exception("argo-oxygen profile %s", profile_key)
        raise _unavailable("Argo O2 measurements")
    if body is None:
        raise HTTPException(404, "profile not found")
    return Response(content=body, media_type="application/json")


async def _build_floats() -> tuple[bytes, int]:
    async with db.pool.acquire() as conn:
        got = await conn.fetchrow("""
            SELECT count(*) AS n, coalesce(json_agg(f ORDER BY dac, wmo), '[]'::json)::text AS features FROM (
              SELECT DISTINCT ON (dac, platform_number) dac, platform_number AS wmo,
                json_build_object('type','Feature',
                  'geometry', json_build_object('type','Point',
                     'coordinates', json_build_array(round(lon::numeric, 3), round(lat::numeric, 3))),
                  'properties', json_build_object('wmo', platform_number, 'dac', dac,
                     'last_profile_key', profile_key, 'last_date', profile_time::date,
                     'n_profiles', count(*) OVER (PARTITION BY dac, platform_number))) AS f
              FROM argo_doxy_profiles WHERE drawable
              ORDER BY dac, platform_number, profile_time DESC, cycle_number DESC, direction DESC) s""")
    return ('{"type":"FeatureCollection","features":' + got["features"] + "}").encode(), got["n"]


@router.get("/v1/argo-oxygen/floats", dependencies=[Depends(get_api_key)])
async def argo_oxygen_floats(request: Request):
    """One point per float. The query is a window + json_agg over every drawn profile, so the document is cached
    per loaded_at like the points documents (gzip once)."""
    try:
        gz = await _cached_document("floats", _build_floats)
    except NotLoaded as e:
        log.warning("argo-oxygen floats: %s", e)
        raise _unavailable("Argo O2 floats (not loaded yet)")
    except Exception:
        log.exception("argo-oxygen floats")
        raise _unavailable("Argo O2 floats")
    return await _serve(gz, request, {"Cache-Control": "public, max-age=3600", "Vary": "Accept-Encoding"})


def _iso(v):
    return v.isoformat() if v else None


async def _health(conn, s) -> dict:
    """ok / running / failing / not_loaded, from argo_doxy_source (the worker's own record), not from sync_log text.

    FAILING only when the worker recorded a failure (blocked / error / schema, or a killed run) and no run has
    succeeded since. NOT failures: a deferral that left a run due (TRANSIENT_PREFIXES), a run that kept some
    floats' old rows (UPDATED_WITH_REJECTS_PREFIX), held deletions, and the healthy daily decisions that write
    nothing at all. Held deletions are surfaced (`deletions_held`) because nothing else would show them."""
    try:
        lr = await conn.fetchrow("SELECT skipped_reason, skipped_at FROM sync_log WHERE source = $1", SOURCE)
    except Exception:                    # sync_log missing (fresh database): health needs no marker
        lr = None
    reason = (lr["skipped_reason"] or "") if lr else ""
    at = lr["skipped_at"] if lr else None
    running = reason.startswith(STARTED_PREFIX) and at is not None and datetime.now(timezone.utc) - at < STARTED_STALE
    status = ("running" if running else "failing" if s["last_failed_at"] is not None
              else "not_loaded" if s["loaded_at"] is None else "ok")
    rej = s["last_rejects"]
    rej = json.loads(rej) if isinstance(rej, str) else (rej or {})
    return {"status": status, "failure": None if running else s["last_failure"],
            "failed_at": None if running else _iso(s["last_failed_at"]),
            "deferred": reason if reason.startswith(TRANSIENT_PREFIXES) else None,
            "note": reason if reason.startswith(UPDATED_WITH_REJECTS_PREFIX) else None,
            "deletions_held": rej.get("deletions_held") or None,
            "last_run_at": _iso(s["last_run_at"]), "last_decision": s["last_decision"],
            "pending_floats": s["pending_floats"], "last_complete_at": _iso(s["last_complete_at"]),
            "last_rejects": rej, "last_rejects_at": _iso(s["last_rejects_at"])}


@router.get("/v1/argo-oxygen/meta", dependencies=[Depends(get_api_key)])
async def argo_oxygen_meta():
    try:
        async with db.pool.acquire() as conn:
            s = await conn.fetchrow("SELECT * FROM argo_doxy_source WHERE id = 1")
            c = await conn.fetchrow("""
                SELECT count(*) AS stored, count(*) FILTER (WHERE drawable) AS drawn,
                  count(*) FILTER (WHERE doxy_mode NOT IN ('A','D')) AS realtime_only,
                  count(*) FILTER (WHERE doxy_mode IN ('A','D') AND n_good = 0) AS no_good_adjusted,
                  count(*) FILTER (WHERE doxy_mode IN ('A','D') AND n_good > 0
                                   AND (lat IS NULL OR coalesce(position_qc, 0) = ANY($2::int[]))) AS bad_position,
                  count(*) FILTER (WHERE doxy_mode IN ('A','D') AND n_good > 0 AND lat IS NOT NULL
                                   AND coalesce(position_qc, 0) <> ALL($2::int[])
                                   AND (profile_time IS NULL OR coalesce(juld_qc, 0) = ANY($3::int[]))) AS bad_time,
                  count(*) FILTER (WHERE rules_version <> $1) AS rules_stale,
                  min(year) FILTER (WHERE drawable) AS y0, max(year) FILTER (WHERE drawable) AS y1
                FROM argo_doxy_profiles""", RULES_VERSION, sorted(BAD_POSITION_QC), sorted(BAD_TIME_QC))
            empty = await conn.fetchval("SELECT count(*) FROM argo_doxy_empty")
            health = await _health(conn, s)
        rej = health["last_rejects"]
        indexed = s["n_index_doxy"]
        body = json.dumps({
            "product": PRODUCT, "field_product": FIELD_PRODUCT, "licence": "CC BY 4.0",
            "citation": CITATION, "citations": list(CITATIONS), "source_url": SOURCE_HOME,
            "gdac_state_as_of": _iso(s["index_date_update_max"]), "loaded_at": _iso(s["loaded_at"]),
            "year_min": c["y0"], "year_max": c["y1"], "units": UNITS,
            "arithmetic": {
                "index_doxy": indexed,
                # `rejected` is the LAST run's own counters (a run re-reads only changed floats), so it does not
                # have to add up to the index; `no_usable_doxy` and `not_yet_stored` are the standing remainder.
                "rejected": {k: v for k, v in rej.items() if isinstance(v, int) and k != "n_failed_floats"},
                "failed_floats": rej.get("n_failed_floats", 0),
                "no_usable_doxy": empty,
                "stored": c["stored"],
                "not_yet_stored": None if indexed is None else max(0, indexed - c["stored"] - empty),
                "not_drawn": {k: c[k] for k in ("realtime_only", "no_good_adjusted", "bad_position", "bad_time")},
                "drawn": c["drawn"]},
            "rules_version": {"code": RULES_VERSION, "last_complete_run": s["rules_version"],
                              "profiles_on_other_version": c["rules_stale"]},
            "depth_windows": {str(k): list(v) for k, v in DEPTH_WINDOWS.items()},
            "health": health,
            "notes": [
                "Only DOXY_ADJUSTED with QC 1 (good) or 2 (probably good) from profiles whose DOXY data mode is "
                "A or D is drawn; raw real-time DOXY (mode R) is stored with its flags and never drawn.",
                "Depth is computed from pressure (UNESCO 1983); the depth windows are in metres, like the field.",
                "Points are absolute O2: they are coloured in the Recent O2 (2014-2018) scale whichever field view "
                "is selected; a single profile has no 1971-2000 baseline, so no change is shown for it.",
                "The field is ISAS20 built from an older Argo snapshot; the points are today's GDAC profiles."],
        }, allow_nan=False)
    except Exception:
        log.exception("argo-oxygen meta")
        raise _unavailable("Argo O2 meta")
    return Response(content=body, media_type="application/json")


async def request_refresh() -> dict:
    """Admin force-sync: RECORD a request, never import (the worker reads it on its next timer tick)."""
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE argo_doxy_source SET refresh_requested_at = now() WHERE id = 1")
        running = await conn.fetchval(
            "SELECT 1 FROM sync_log WHERE source = $1 AND skipped_reason LIKE $2 AND skipped_at > now() - $3::interval",
            SOURCE, STARTED_PREFIX + "%", STARTED_STALE)
    if not running:
        await log_sync_skipped(SOURCE, "refresh requested; argo-doxy worker runs it on its next timer tick")
    return {"requested": True}
