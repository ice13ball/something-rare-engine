# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""GLODAPv3 "Measurements" points: the API half of the glodap-points layer.

Real bottle casts drawn on top of the GLODAPv2.2016b mapped climatology. The import runs in
`glodap_bottles_worker` (own process); this module only reads what it swapped in, and records a
force-sync request for the worker (`request_refresh`).

⛔ Missing and broken never share a path: an unknown cast key is a 404; a database that cannot answer,
or a layer that has not loaded yet, is a 503 + Retry-After — never a 200 with an empty body.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import logging
import math
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response

import db
from auth import get_api_key
from ingestion.glodap_bottles_rules import (BOTTLE_UNITS, DEPTH_WINDOWS, FIELD_TO_BOTTLE, QC_VARIABLES, SOURCE,
                                            STARTED_PREFIX, STARTED_STALE, SWAPPED_WITH_REJECTS_PREFIX,
                                            TRANSIENT_PREFIXES, VARIABLES)
from services import glodap_carbon
from sync_log import log_sync_skipped

log = logging.getLogger(__name__)
router = APIRouter()

# ⛔ Never import `ingestion.glodap_bottles` (the loader: duckdb, circular via schema -> domains) or
# `glodap_bottles_worker` here: the API reads the run-state constants from the pure rules module only, so a
# failed import cannot 503 /meta or the force-sync. tests/test_glodap_api_db.py checks it in a subprocess.

PRODUCT = "GLODAPv3 (2026)"
FIELD_PRODUCT = "GLODAPv2.2016b mapped climatology (TCO2 and pH normalised to 2002)"
SOURCE_URL = "https://doi.org/10.25921/m6tp-mj50"
# Three credits travel together: the dataset, the paper, and the ship names (NVS, CC BY 4.0 — its
# attribution is a licence condition, see https://vocab.nerc.ac.uk/about).
CITATIONS = (
    "Lange, N., Lauvset, S. K., Carter, B. R., et al. (2026). The Global Ocean Data Analysis Project "
    "version 3 (GLODAPv3) (NCEI Accession 0315582). NOAA NCEI. https://doi.org/10.25921/m6tp-mj50",
    "Lange et al., ESSD preprint, https://doi.org/10.5194/essd-2026-496",
    "Ship names: The NERC Vocabulary Server (NVS), National Oceanography Centre - British Oceanographic "
    "Data Centre (BODC), collection C17 (ICES platform codes), https://vocab.nerc.ac.uk/collection/C17/current/ "
    "- CC BY 4.0, https://vocab.nerc.ac.uk/about",
)
CITATION = " — and ".join(CITATIONS)

# The map document is ~11 MiB raw / 1.4 MiB gzipped on the full file (measured 2026-10-06). Cloud Run's
# 32 MiB response cap applies BEFORE compression, so growth is watched on the raw size.
_RAW_WARN_BYTES = 24 * 2**20
_RETRY_AFTER = {"Retry-After": "60"}

# (loaded_at stamp, raw JSON, gzipped JSON). The stamp is what makes the cache survive the swap being done by
# ANOTHER process: the import runs in glodap_bottles_worker, whose clear_caches() cannot reach this process's
# memory, so every request compares the stamp with glodap_bottle_source.loaded_at and rebuilds on a mismatch.
_casts_cache: tuple[object, bytes, bytes] | None = None
_casts_lock = asyncio.Lock()


def clear_caches() -> None:
    global _casts_cache
    _casts_cache = None


def _unavailable(what: str) -> HTTPException:
    return HTTPException(503, f"{what} temporarily unavailable", headers=_RETRY_AFTER)


def _num(x, ndigits: int = 7):
    """real[] / float4 -> a clean JSON number: float32 noise trimmed (7 significant digits), NaN/inf -> None."""
    if x is None:
        return None
    x = float(x)
    if not math.isfinite(x):
        return None
    return float(f"{x:.{ndigits}g}")


def _assemble_casts(rows) -> tuple[bytes, int]:
    """CPU-bound (parses every cast's levels JSON); runs in a worker thread, not on the event loop."""
    depths = [str(d) for d in DEPTH_WINDOWS]
    keys, lon, lat, year = [], [], [], []
    values = {k: {d: [] for d in depths} for k, col in FIELD_TO_BOTTLE.items() if col}
    for r in rows:
        keys.append(r["cast_key"])
        lon.append(round(r["lon"], 4))
        lat.append(round(r["lat"], 4))
        year.append(r["year"])
        lv = json.loads(r["levels"])                         # asyncpg returns jsonb as str
        for k in values:
            per = lv.get(k, {})
            for d in depths:
                hit = per.get(d)
                v = hit[0] if hit else None
                values[k][d].append(v if v is not None and math.isfinite(v) and v > 0 else None)
    doc = json.dumps({"product": PRODUCT, "n": len(keys), "keys": keys, "lon": lon, "lat": lat,
                      "year": year, "values": values}, separators=(",", ":"), allow_nan=False)
    return doc.encode(), len(keys)


async def _build_casts() -> tuple[bytes, int]:
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT cast_key, lon, lat, year, levels FROM glodap_casts "
                                "WHERE n_good > 0 ORDER BY cast_key")
    return await asyncio.to_thread(_assemble_casts, rows)


async def build_casts_document() -> bytes:
    """The map document: only casts with at least one WOCE-flag-2 value, flag-2 values only, no NaN."""
    return (await _build_casts())[0]


async def _loaded_at():
    async with db.pool.acquire() as conn:
        return await conn.fetchval("SELECT loaded_at FROM glodap_bottle_source WHERE id = 1")


async def _casts_document_cached() -> tuple[bytes, bytes]:
    """-> (raw, gzipped). Raises LookupError when nothing is loaded (never caches an empty document)."""
    global _casts_cache
    stamp = await _loaded_at()          # read BEFORE the data: a swap in between only makes us rebuild once more
    if stamp is None:
        raise LookupError("glodap_casts not loaded yet")
    cached = _casts_cache
    if cached is not None and cached[0] == stamp:
        return cached[1], cached[2]
    async with _casts_lock:
        cached = _casts_cache
        if cached is not None and cached[0] == stamp:
            return cached[1], cached[2]
        raw, n = await _build_casts()
        if n == 0:
            raise LookupError("glodap_casts holds no drawable cast")
        if len(raw) > _RAW_WARN_BYTES:
            log.warning("glodap casts document is %d B — approaching Cloud Run's 32 MiB pre-compression cap", len(raw))
        # Compressed ONCE here: the app-wide GZipMiddleware would re-compress 11 MiB at level 9 on every
        # request, and leaves a response that already carries Content-Encoding alone.
        gz = await asyncio.to_thread(gzip.compress, raw, 6)
        _casts_cache = (stamp, raw, gz)
        return raw, gz


@router.get("/v1/glodap/casts", dependencies=[Depends(get_api_key)])
async def glodap_casts(request: Request):
    try:
        raw, gz = await _casts_document_cached()
    except LookupError as e:             # not loaded yet: expected before the first import, one line per request
        log.warning("glodap casts: %s", e)
        raise _unavailable("GLODAP casts (not loaded yet)")
    except Exception:
        log.exception("glodap casts document")
        raise _unavailable("GLODAP casts")
    headers = {"Cache-Control": "public, max-age=3600", "Vary": "Accept-Encoding"}
    if "gzip" in request.headers.get("accept-encoding", "").lower():
        return Response(content=gz, media_type="application/json", headers={**headers, "Content-Encoding": "gzip"})
    return Response(content=raw, media_type="application/json", headers=headers)


def _field_samples(lat: float, lon: float) -> dict:
    return {k: {str(d): _num(glodap_carbon.sample(k, lat, lon, d)) for d in glodap_carbon.DISPLAY_DEPTHS}
            for k in FIELD_TO_BOTTLE}


async def get_cast_payload(cast_key: str) -> dict | None:
    """None when the key is unknown (-> 404). Raises when the database cannot answer (-> 503)."""
    async with db.pool.acquire() as conn:
        r = await conn.fetchrow("SELECT c.*, cr.ship_name FROM glodap_casts c "
                                "LEFT JOIN glodap_cruises cr USING (expocode) WHERE c.cast_key = $1", cast_key)
    if r is None:
        return None
    field = await asyncio.to_thread(_field_samples, r["lat"], r["lon"])      # first call loads a netCDF grid
    return {
        "cast_key": r["cast_key"], "expocode": r["expocode"], "station": r["station"], "cast_no": r["cast_no"],
        "ship_name": r["ship_name"], "platform_code": r["platform_code"], "lat": r["lat"], "lon": r["lon"],
        "obs_date": r["obs_date"].isoformat(), "obs_time": r["obs_time"].isoformat() if r["obs_time"] else None,
        "time_precision": r["time_precision"], "year": r["year"], "region": r["region"], "doi": r["doi"],
        "bottom_depth_m": _num(r["bottom_depth_m"]), "pos_spread_km": _num(r["pos_spread_km"]),
        "depth_m": [_num(x) for x in r["depth_m"]],
        "pressure_dbar": [_num(x) for x in (r["pressure_dbar"] or [])],
        "bottle": [_num(x) for x in (r["bottle"] or [])],
        "variables": {v: {"values": [_num(x) for x in (r[v] or [])], "flags": list(r[f"{v}_f"] or []),
                          "qc": r[f"{v}_qc"] if v in QC_VARIABLES else None, "units": BOTTLE_UNITS[v]}
                      for v in VARIABLES},
        "levels": json.loads(r["levels"]), "field": field,
        "citation": CITATION, "citations": list(CITATIONS), "source_url": SOURCE_URL,
        "product": PRODUCT, "field_product": FIELD_PRODUCT,
    }


@router.get("/v1/glodap/cast/{cast_key}", dependencies=[Depends(get_api_key)])
async def glodap_cast(cast_key: str):
    try:
        p = await get_cast_payload(cast_key)
        body = None if p is None else json.dumps(p, allow_nan=False)
    except Exception:
        log.exception("glodap cast %s", cast_key)
        raise _unavailable("GLODAP casts")
    if body is None:
        raise HTTPException(404, "cast not found")
    return Response(content=body, media_type="application/json")


@router.get("/v1/glodap/cruises", dependencies=[Depends(get_api_key)])
async def glodap_cruises():
    try:
        async with db.pool.acquire() as conn:
            r = await conn.fetchrow("""SELECT count(*) AS n, coalesce(json_agg(f ORDER BY ex), '[]'::json)::text AS features
                FROM (SELECT expocode AS ex, json_build_object('type','Feature',
                  'geometry', json_build_object('type','Point','coordinates', json_build_array(lon, lat)),
                  'properties', json_build_object('expocode',expocode,'ship_name',ship_name,
                     'platform_code',platform_code,'doi',doi,'first_date',first_date,'last_date',last_date,
                     'n_casts',n_casts,'first_cast_key',first_cast_key)) AS f FROM glodap_cruises) s""")
    except Exception:
        log.exception("glodap cruises")
        raise _unavailable("GLODAP cruises")
    if not r["n"]:
        log.warning("glodap cruises: glodap_cruises not loaded yet")
        raise _unavailable("GLODAP cruises (not loaded yet)")
    return Response(content='{"type":"FeatureCollection","features":' + r["features"] + "}",
                    media_type="application/json", headers={"Cache-Control": "public, max-age=3600"})


def _iso(value):
    return value.isoformat() if value else None


async def _health(conn, s) -> dict:
    """Layer health from glodap_bottle_source (the worker's own record), not from sync_log text.

    FAILING only when the worker recorded a failure (blocked / error / schema, or a killed run) and no
    import has succeeded since — the swap clears it. NOT failures: a deferral that left an import due
    (TRANSIENT_PREFIXES: low memory / disk / HEAD failed), a swap that rejected some rows
    (SWAPPED_WITH_REJECTS_PREFIX), and the healthy daily decisions that write nothing at all."""
    try:
        log_row = await conn.fetchrow("SELECT skipped_reason, skipped_at FROM sync_log WHERE source = $1", SOURCE)
    except Exception:                      # sync_log missing (fresh database): health needs no marker
        log_row = None
    reason = (log_row["skipped_reason"] or "") if log_row else ""
    skipped_at = log_row["skipped_at"] if log_row else None
    running = (reason.startswith(STARTED_PREFIX) and skipped_at is not None
               and datetime.now(timezone.utc) - skipped_at < STARTED_STALE)
    deferred = reason if reason.startswith(TRANSIENT_PREFIXES) else None
    swapped_note = reason if reason.startswith(SWAPPED_WITH_REJECTS_PREFIX) else None
    failed_at, failure = s["last_failed_at"], s["last_failure"]
    if running:
        status = "running"                  # the worker's pessimistic 'interrupted' stamp is expected mid-run
    elif failed_at is not None:
        status = "failing"
    elif s["loaded_at"] is None:
        status = "not_loaded"
    else:
        status = "ok"
    rejects = s["last_rejects"]
    return {
        "status": status,
        "failure": None if running else failure,
        "failed_at": None if running else _iso(failed_at),
        "deferred": deferred,
        "last_run_at": _iso(s["last_run_at"]), "last_decision": s["last_decision"],
        "last_rejects": json.loads(rejects) if isinstance(rejects, str) else (rejects or {}),
        "last_rejects_at": _iso(s["last_rejects_at"]),
        "swap_note": swapped_note,
    }


@router.get("/v1/glodap/meta", dependencies=[Depends(get_api_key)])
async def glodap_meta():
    try:
        async with db.pool.acquire() as conn:
            s = await conn.fetchrow("SELECT * FROM glodap_bottle_source WHERE id = 1")
            yr = await conn.fetchrow("SELECT min(year) AS lo, max(year) AS hi FROM glodap_casts")
            health = await _health(conn, s)
        body = json.dumps({
            "product": PRODUCT, "field_product": FIELD_PRODUCT, "citation": CITATION, "citations": list(CITATIONS),
            "licence": "CC BY 4.0", "source_url": SOURCE_URL,
            "n_casts": s["n_casts"], "n_casts_drawn": s["n_casts_drawn"], "n_samples": s["n_samples"],
            "year_min": yr["lo"], "year_max": yr["hi"], "loaded_at": _iso(s["loaded_at"]),
            "depth_windows": {str(k): list(v) for k, v in DEPTH_WINDOWS.items()}, "field_to_bottle": FIELD_TO_BOTTLE,
            "health": health,
            "notes": ["Only WOCE flag 2 (acceptable) values are drawn; flags 0 (interpolated/calculated) and 9 (no data) are stored, not drawn.",
                      "pH and fCO2 in GLODAPv3 were not subjected to secondary QC.",
                      "Cant is a mapped quantity: bottles carry none, so points are grey when Cant is selected.",
                      "The field's TCO2 and pH are normalised to 2002; bottles are as measured in their sample year."],
        }, allow_nan=False)
    except Exception:
        log.exception("glodap meta")
        raise _unavailable("GLODAP meta")
    return Response(content=body, media_type="application/json")


async def request_refresh() -> dict:
    """Admin force-sync: RECORD a request, never import. ⛔ The import runs in glodap_bottles_worker
    (own cgroup, MemoryMax); running it here would put a 481 MB CSV stream inside the 9G-capped API.
    The worker reads `refresh_requested_at` on its next timer tick."""
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE glodap_bottle_source SET refresh_requested_at = now() WHERE id = 1")
        running = await conn.fetchval(
            "SELECT 1 FROM sync_log WHERE source = $1 AND skipped_reason LIKE $2 AND skipped_at > now() - $3::interval",
            SOURCE, STARTED_PREFIX + "%", STARTED_STALE)
    if not running:                      # never overwrite a live import's "started" marker
        await log_sync_skipped(SOURCE, "refresh requested; glodap-bottles worker runs it on its next timer tick")
    return {"requested": True}
