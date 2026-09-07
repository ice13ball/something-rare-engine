# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Seafloor — seamounts, hydrothermal vents, and bathymetry (GEBCO depth lookup
+ confidence/GMRT enrichment). Three sources that all describe the seafloor
itself rather than anything sitting on or above it.

Moved verbatim out of backend/main.py (Task 6, the last task, of the backend
vertical-split refactor, Phase 2). Only permitted edits applied: `@app.get` ->
`@router.get`, `_pool.acquire()` -> `db.pool.acquire()`, leading underscore
dropped from the three sync function names (`_sync_hydrothermal_vents` ->
`sync_hydrothermal_vents`, `_sync_seamounts` -> `sync_seamounts`,
`_sync_bathymetry_stats` -> `sync_bathymetry_stats`) and from the shared GMRT
helper (`_gmrt_for_bbox` -> `gmrt_for_bbox` — used by both bathymetry
endpoints, same "drop the leading underscore from every moved top-level name,
not just the sync_* ones" rule established for offshore's shared helpers and
followed in geochem.py), and imports/docstring. Module-level *constants*
(non-callables) keep their leading underscore: `_BATHY_TABLES`, `_BATHY_SETS`,
`_BATHYMETRY_FAIL_TTL_S`, `_BATHYMETRY_API`, and the two cache globals.
`VENT_SYNC_INTERVAL_DAYS` and `PANGAEA_VENTS_URL` keep their bare (no
underscore) names — that is how they were already spelled in main.py, not a
new choice made here.

`sync_seamounts` (this module's public sync function) contains an unchanged
inline `from ingestion.seamount_ingest import sync_seamounts` — that import
now shares its name with the enclosing function. This was already legal
before the rename (Python resolves the local import binding within the
function's own scope, not the module global) and stays legal after it; the
body is verbatim, so the local import was not touched to avoid the collision.

## Two things that look like they belong here but do NOT

- `_resource_type` (formerly main.py) stayed in main.py at the time — its only
  caller was `_sync_mining_contracts`, i.e. the future `isa` domain, not this
  one. Both have since moved: it is now `isa.resource_type`, called by
  `isa.sync_mining_contracts` in `domains/isa.py`.
- `get_vent_report` (formerly main.py, `/v1/seo/vent-report/{vent_id}`) stayed
  in main.py at the time despite the name — it was an SEO route, and belonged
  with the other fourteen `/v1/seo/*` endpoints in a future `seo.py` domain.
  Moving it here would have split that family across two modules. `seo.py`
  now exists and owns it; see that module's docstring for the "now
  historical" note this cross-reference predates.

## `bathymetry_cache` (the Postgres table) is a memo cache, not a dataset

The bathymetry cache is a memo cache, not a dataset: the DB table's row count is "how many distinct points a user has
clicked", keyed at 0.01° resolution — it exists purely so a repeat hover
doesn't re-hit Open-Topo-Data. The platform's actual bathymetric coverage
lives in `services/bathymetry_grid_export.py` (a downsampled global GEBCO
2024 grid, 3600x7200 = 25.9M cells) and in `bathymetry_stats` (10,580 rows of
precomputed per-feature confidence stats, populated by `sync_bathymetry_stats`
below). Reading the memo cache's size as the extent of our bathymetry
coverage is a category error an external analysis has already made once.
Moving this module moves neither of those two real datasets — only the L1
in-memory dict that fronts the memo table, and the confidence/GMRT enrichment
endpoints that read `bathymetry_stats` directly.

## Caches — two globals that are NOT the same kind of thing

`_bathymetry_cache` (module dict, L1 hot cache in front of the `bathymetry_cache`
Postgres table) matches `test_domain_cache_clear.py`'s cache-name regex and is
cleared by `clear_caches()` below — it was never swept by `admin_cache_clear()`
before this move, so this is new coverage the extraction adds for free, not a
behavior change caused by it.

`_bathymetry_fail_until` is a **failure-backoff map** (host/tile key -> a
monotonic retry-after timestamp), not a response cache — it does not match the
cache-name regex (no "cache" substring) and `admin_cache_clear()` never
touched it. `clear_caches()` deliberately does NOT clear it: doing so would
reset every in-flight Open-Topo-Data backoff timer, silently un-throttling
retries against their ~1 req/s limit — a behavior change masquerading as a
housekeeping move. Left alone on purpose; do not "complete" this function by
adding it later.

## `get_seamounts`/`get_vents` share the leaf TTL response cache

Both read/write the shared `response_cache.py` store (21600s TTL, nine call
sites total across the codebase before this refactor began) rather than a
domain-local cache. Imported and aliased exactly as `geo_context.py` and
`geochem.py` do, so every call site in the moved bodies stays byte-identical:

    from response_cache import CACHE_TTL, store as _cache

`clear_caches()` below also clears this shared store on top of
`admin_cache_clear()`'s own `_cache.clear()` — redundant, but idempotent, and
it keeps the aliased `_cache` name honest under
`test_domain_cache_clear.py`'s `dir(mod)` scan (same rationale as
`geo_context.clear_caches()`).
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
import time
from datetime import datetime, timezone, timedelta

import db
import httpx
from auth import get_api_key
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from indexnow import notify_indexnow as _notify_indexnow, SITE_HOST
from response_cache import CACHE_TTL, store as _cache
from services import bathymetry_stats
from sync_log import log_sync as _log_sync

log = logging.getLogger(__name__)
router = APIRouter()

# ── Caches ──────────────────────────────────────────────────────────────────
# See module docstring: `_bathymetry_cache` is swept, `_bathymetry_fail_until`
# is deliberately not (it is a backoff map, not a response cache).
_bathymetry_cache: dict[str, str] = {}
_bathymetry_fail_until: dict[str, float] = {}
_BATHYMETRY_FAIL_TTL_S = 300  # retry a failed tile after 5 min
_BATHYMETRY_API = "https://api.opentopodata.org/v1/gebco2020"


def clear_caches() -> None:
    """Drop this domain's cached responses. Called by /admin/cache/clear.

    `_bathymetry_fail_until` (the Open-Topo-Data retry-backoff map) is NOT
    cleared here on purpose — see module docstring. `admin_cache_clear()`
    never touched it either; clearing it would reset every in-flight backoff
    timer, which is a behavior change, not a cache sweep.
    """
    _cache.clear()
    _bathymetry_cache.clear()


# ── Hydrothermal vents ───────────────────────────────────────────────────────

VENT_SYNC_INTERVAL_DAYS = 14
# InterRidge v3.4 hosted on PANGAEA (stable DOI-backed archive)
PANGAEA_VENTS_URL = "https://hs.pangaea.de/Maps/Vents/InterRidge_Beaulieu_2020/vent_fields_all_20200325cleansorted.csv"

async def sync_hydrothermal_vents() -> int:
    """Fetch InterRidge Vents Database v3.4 from PANGAEA and upsert new vent fields.

    Source: Beaulieu & Szafrański (2020), PANGAEA doi:10.1594/PANGAEA.917894
    Runs a 14-day interval check against sync_log — skips if last sync was
    within 14 days (vent locations are geologically stable; new discoveries rare).
    Returns number of new rows inserted.
    """
    # 14-day interval guard
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_synced_at FROM sync_log WHERE source = 'hydrothermal_vents'"
        )
    if row and row["last_synced_at"]:
        age_days = (datetime.now(timezone.utc) - row["last_synced_at"]).days
        if age_days < VENT_SYNC_INTERVAL_DAYS:
            log.info("hydrothermal_vents: skipping sync (last ran %d days ago)", age_days)
            return 0

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(PANGAEA_VENTS_URL)
            resp.raise_for_status()
            text = resp.text
    except Exception as exc:
        log.error("hydrothermal_vents: fetch failed: %s", exc)
        return 0

    if text.lstrip().startswith("<"):
        log.error("hydrothermal_vents: got HTML instead of CSV")
        return 0

    # PANGAEA CSV columns — see InterRidge v3.4 schema
    reader = csv.DictReader(io.StringIO(text))
    inserted = 0

    def _clean(val: str | None) -> str | None:
        if not val:
            return None
        v = val.strip().strip('"')
        return v if v and v.upper() != "NA" else None

    def _float(val: str | None) -> float | None:
        v = _clean(val)
        if not v:
            return None
        try:
            return float(v)
        except ValueError:
            return None

    async with db.pool.acquire() as conn:
        for row in reader:
            name = _clean(row.get("Name.ID"))
            raw_activity = (_clean(row.get("Activity")) or "").lower()
            if "active" in raw_activity and "inactive" not in raw_activity:
                status = "Active"
            elif "inactive" in raw_activity:
                status = "Inactive"
            else:
                status = "Extinct"

            try:
                lat = float(row.get("Latitude") or 0)
                lon = float(row.get("Longitude") or 0)
            except ValueError:
                continue
            if not name or (lat == 0 and lon == 0):
                continue

            depth_m = _float(row.get("Maximum.or.Single.Reported.Depth"))
            min_depth_m = _float(row.get("Minimum.Depth"))
            max_temp_c = _float(row.get("Maximum.Temperature"))
            temp_category = _clean(row.get("Max.Temperature.Category"))
            ocean = _clean(row.get("Ocean"))
            region = _clean(row.get("Region"))
            jurisdiction = _clean(row.get("National.Jurisdiction"))
            tectonic_setting = _clean(row.get("Tectonic.setting"))
            discovery_raw = _clean(row.get("Year.and.How.Discovered..if.active..visual.confirmation.is.listed.first."))
            biology_notes = _clean(row.get("Notes.Relevant.to.Biology"))
            description_notes = _clean(row.get("Notes.on.Vent.Field.Description"))

            result = await conn.execute(
                """INSERT INTO hydrothermal_vents
                       (name, status, depth_m, latitude, longitude, geom, source_url,
                        max_temp_c, temp_category, min_depth_m, ocean, region,
                        jurisdiction, tectonic_setting, discovery_year,
                        biology_notes, description_notes)
                   VALUES ($1, $2, $3, $4, $5,
                           ST_SetSRID(ST_MakePoint($5, $4), 4326)::geography,
                           $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                   ON CONFLICT (name, latitude, longitude) DO UPDATE SET
                       status = EXCLUDED.status,
                       depth_m = EXCLUDED.depth_m,
                       max_temp_c = EXCLUDED.max_temp_c,
                       temp_category = EXCLUDED.temp_category,
                       min_depth_m = EXCLUDED.min_depth_m,
                       ocean = EXCLUDED.ocean,
                       region = EXCLUDED.region,
                       jurisdiction = EXCLUDED.jurisdiction,
                       tectonic_setting = EXCLUDED.tectonic_setting,
                       discovery_year = EXCLUDED.discovery_year,
                       biology_notes = EXCLUDED.biology_notes,
                       description_notes = EXCLUDED.description_notes""",
                name, status, depth_m, lat, lon, PANGAEA_VENTS_URL,
                max_temp_c, temp_category, min_depth_m, ocean, region,
                jurisdiction, tectonic_setting, discovery_raw,
                biology_notes, description_notes,
            )
            if "INSERT" in result:
                inserted += 1

    async with db.pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM hydrothermal_vents")
    await _log_sync("hydrothermal_vents", inserted, total)
    log.info("hydrothermal_vents: %d new / %d total", inserted, total)
    if inserted > 0:
        async with db.pool.acquire() as conn:
            vent_ids = await conn.fetch("SELECT id FROM hydrothermal_vents ORDER BY created_at DESC LIMIT $1", inserted)
        await _notify_indexnow([f"https://{SITE_HOST}/vent/{r['id']}" for r in vent_ids])
    return inserted


# ── Seamounts ─────────────────────────────────────────────────────────────────

async def sync_seamounts():
    """Fetch seamounts + knolls from PANGAEA and rebuild the table."""
    from ingestion.seamount_ingest import sync_seamounts
    async with db.pool.acquire() as conn:
        fetched, inserted = await sync_seamounts(conn)
        await _log_sync("seamounts", fetched, inserted)
    # Clear seamounts cache
    _cache.pop("seamounts", None)
    asyncio.create_task(_notify_indexnow([f"https://{SITE_HOST}/sitemap.xml"]))
    log.info("seamounts sync complete: %d fetched, %d inserted", fetched, inserted)


# ── Bathymetry confidence stats (GEBCO 2024) ────────────────────────────────

_BATHY_SETS = [
    ("isa_contract",      "mining_contracts",   "isa_id"),
    ("isa_reserved",      "reserved_areas",     "arcgis_id"),
    ("isa_apei",          "isa_apeis",          "arcgis_id"),
    ("isa_relinquished",  "relinquished_areas", "arcgis_id"),
    ("offshore_activity", "offshore_activities", "id"),
]


async def sync_bathymetry_stats(force: bool = False) -> int:
    """Compute GEBCO_2024 bathymetry confidence stats for ISA + offshore features.
    Admin-only batch (10–30 min); no startup task."""
    if not force:
        async with db.pool.acquire() as conn:
            last = await conn.fetchval(
                "SELECT last_synced_at FROM sync_log WHERE source='bathymetry-stats'")
        if last is not None and (datetime.now(timezone.utc) - last) < timedelta(days=30):
            log.info("bathymetry-stats: recent — skipping"); return 0
    if not await asyncio.to_thread(bathymetry_stats.ensure_holdings, force):
        await _log_sync("bathymetry-stats", 0, 0); return 0
    total = 0
    try:
        for ftype, table, pk in _BATHY_SETS:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch(
                    f"SELECT {pk}::text AS fid, ST_AsGeoJSON(geom)::text AS gj, "
                    f"ST_XMin(geom) AS w, ST_YMin(geom) AS s, ST_XMax(geom) AS e, ST_YMax(geom) AS n "
                    f"FROM {table} WHERE geom IS NOT NULL")
                for r in rows:
                    if (r["e"] - r["w"]) > 180:
                        continue
                    try:
                        out = await asyncio.to_thread(
                            bathymetry_stats.sample_polygon, json.loads(r["gj"]),
                            (r["w"], r["s"], r["e"], r["n"]))
                    except Exception as exc:
                        log.warning("bathy sample failed %s/%s: %s", ftype, r["fid"], exc); continue
                    if not out: continue
                    await conn.execute(
                        """INSERT INTO bathymetry_stats
                           (feature_type,feature_id,gebco_version,n_cells,pct_measured,pct_indirect,
                            pct_unknown,pct_multibeam,mapped_confidence,depth_min_m,depth_median_m,
                            depth_max_m,slope_median_deg,ruggedness,computed_at)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,NOW())
                           ON CONFLICT (feature_type,feature_id) DO UPDATE SET
                            gebco_version=EXCLUDED.gebco_version,n_cells=EXCLUDED.n_cells,
                            pct_measured=EXCLUDED.pct_measured,pct_indirect=EXCLUDED.pct_indirect,
                            pct_unknown=EXCLUDED.pct_unknown,pct_multibeam=EXCLUDED.pct_multibeam,
                            mapped_confidence=EXCLUDED.mapped_confidence,depth_min_m=EXCLUDED.depth_min_m,
                            depth_median_m=EXCLUDED.depth_median_m,depth_max_m=EXCLUDED.depth_max_m,
                            slope_median_deg=EXCLUDED.slope_median_deg,ruggedness=EXCLUDED.ruggedness,
                            computed_at=NOW()""",
                        ftype, r["fid"], out["gebco_version"], out["n_cells"], out["pct_measured"],
                        out["pct_indirect"], out["pct_unknown"], out["pct_multibeam"],
                        out["mapped_confidence"], out["depth_min_m"], out["depth_median_m"],
                        out["depth_max_m"], out.get("slope_median_deg"), out.get("ruggedness"))
                    total += 1
            log.info("bathymetry-stats: %s done (%d cumulative)", ftype, total)
    finally:
        await asyncio.to_thread(bathymetry_stats.cleanup_holdings)
    await _log_sync("bathymetry-stats", total, total)
    log.info("bathymetry-stats: %d features", total); return total


# ── Endpoints ───────────────────────────────────────────────────────────────

# ── GEBCO seafloor depth lookup ──────────────────────────────────────────────
# Proxies Open-Topo-Data's gebco2020 dataset (same GEBCO source as our visual
# layer). Two-tier cache:
#   L1 (in-memory dict) — sub-millisecond, per-process, lost on restart.
#   L2 (bathymetry_cache table) — ~1 ms, shared across users, survives restarts.
# Open-Topo-Data is only hit on a full L1+L2 miss. First user to hover a region
# pays the 300-1500 ms upstream cost; every user after them gets ~1 ms forever.

def _bathymetry_payload(lat: float, lon: float, depth_m: float | None) -> str:
    return json.dumps({
        "depth_m": depth_m,
        "dataset": "GEBCO_2020",
        "lat": lat, "lon": lon,
    })

@router.get("/v1/bathymetry/lookup", dependencies=[Depends(get_api_key)])
async def get_bathymetry_at(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    """Return seafloor depth (negative meters) and dataset at (lat, lon)."""
    lat_r = round(lat, 2)
    lon_r = round(lon, 2)
    cache_key = f"{lat_r:.2f},{lon_r:.2f}"

    # L1: in-memory hot cache.
    if cache_key in _bathymetry_cache:
        return Response(content=_bathymetry_cache[cache_key], media_type="application/json")

    # L2: persistent Postgres cache. A missing table (e.g. schema.ensure_schema skipped
    # under lock_timeout) or a DB hiccup must not 500 the lookup — log and fall
    # through to the upstream API instead.
    row = None
    try:
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT depth_m FROM bathymetry_cache WHERE lat_round = $1 AND lon_round = $2",
                lat_r, lon_r,
            )
    except Exception as exc:
        log.warning("bathymetry_cache SELECT failed for %s,%s: %s", lat_r, lon_r, exc)
    if row is not None:
        payload = _bathymetry_payload(lat, lon, float(row["depth_m"]) if row["depth_m"] is not None else None)
        _bathymetry_cache[cache_key] = payload
        return Response(content=payload, media_type="application/json")

    # Negative cache: this tile failed upstream recently — return "unknown"
    # without re-hitting Open-Topo-Data until the backoff expires.
    fail_until = _bathymetry_fail_until.get(cache_key)
    if fail_until is not None and time.monotonic() < fail_until:
        return Response(content=_bathymetry_payload(lat, lon, None), media_type="application/json")

    # Miss on both layers — go to Open-Topo-Data.
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(_BATHYMETRY_API, params={"locations": f"{lat},{lon}"})
        r.raise_for_status()
        data = r.json()
        results = data.get("results") or []
        elev = results[0].get("elevation") if results else None
    except Exception as exc:
        log.warning("bathymetry lookup failed for %s,%s: %s", lat, lon, exc)
        elev = None

    payload = _bathymetry_payload(lat, lon, elev)
    # Persist successful lookups to both L1 and L2. Skip caching failures —
    # they're often transient (Open-Topo-Data rate limit / network blip) —
    # but remember them in the negative cache so retries back off.
    if elev is None:
        _bathymetry_fail_until[cache_key] = time.monotonic() + _BATHYMETRY_FAIL_TTL_S
        if len(_bathymetry_fail_until) > 10000:
            _bathymetry_fail_until.clear()
    else:
        _bathymetry_fail_until.pop(cache_key, None)
        _bathymetry_cache[cache_key] = payload
        try:
            async with db.pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO bathymetry_cache (lat_round, lon_round, depth_m)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (lat_round, lon_round) DO NOTHING""",
                    lat_r, lon_r, float(elev),
                )
        except Exception as exc:
            log.warning("bathymetry_cache INSERT failed for %s,%s: %s", lat_r, lon_r, exc)
        # Bound the L1 dict so a long-running process doesn't grow unbounded.
        if len(_bathymetry_cache) > 50000:
            for k in list(_bathymetry_cache.keys())[:5000]:
                _bathymetry_cache.pop(k, None)
    return Response(content=payload, media_type="application/json")


# ---------------------------------------------------------------------------
# Bathymetry confidence + GMRT endpoints
# ---------------------------------------------------------------------------

_BATHY_TABLES = {
    "isa_contract":       ("mining_contracts",    "isa_id"),
    "isa_reserved":       ("reserved_areas",      "arcgis_id"),
    "isa_apei":           ("isa_apeis",           "arcgis_id"),
    "isa_relinquished":   ("relinquished_areas",  "arcgis_id"),
    "offshore_activity":  ("offshore_activities", "id"),
}


async def gmrt_for_bbox(w, s, e, n) -> dict | None:
    """Return GMRT metadata for a bbox, caching in gmrt_area_cache by area_hash."""
    ah = hashlib.sha1(
        f"{round(w,2)},{round(s,2)},{round(e,2)},{round(n,2)}".encode()
    ).hexdigest()[:16]
    async with db.pool.acquire() as conn:
        c = await conn.fetchrow(
            "SELECT meters_per_node,nodes,gmrt_version FROM gmrt_area_cache WHERE area_hash=$1", ah
        )
        if c:
            return dict(c)
    url = (
        "https://www.gmrt.org/services/GridServer/metadata"
        f"?north={n}&south={s}&east={e}&west={w}&format=netcdf&mformat=json&resolution=max"
    )
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url)
            r.raise_for_status()
            j = r.json()
    except Exception as exc:
        log.info("gmrt metadata failed: %s", exc)
        return None
    # GMRT returns numeric metadata fields as strings (e.g. "61.15") — coerce
    # before binding to the DOUBLE PRECISION / BIGINT columns (asyncpg rejects str).
    def _num(v, cast):
        try:
            return cast(v)
        except (TypeError, ValueError):
            return None
    mpn = _num(j.get("meters_per_node"), float)
    nodes = _num(j.get("nodes"), int)
    ver = j.get("gmrt_version")
    async with db.pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO gmrt_area_cache (area_hash,bbox,meters_per_node,nodes,gmrt_version,raw,fetched_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,NOW()) ON CONFLICT (area_hash) DO UPDATE SET "
            "meters_per_node=EXCLUDED.meters_per_node,nodes=EXCLUDED.nodes,"
            "gmrt_version=EXCLUDED.gmrt_version,fetched_at=NOW()",
            ah, [w, s, e, n], mpn, nodes, ver, json.dumps(j),
        )
    return {"meters_per_node": mpn, "nodes": nodes, "gmrt_version": ver}


@router.get("/v1/bathymetry/confidence/{feature_type}/{feature_id}", dependencies=[Depends(get_api_key)])
async def bathymetry_confidence(feature_type: str, feature_id: str):
    """Return pre-computed GEBCO stats for a feature (fast, from bathymetry_stats table)."""
    if feature_type not in _BATHY_TABLES:
        raise HTTPException(status_code=404, detail="unknown feature_type")
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM bathymetry_stats WHERE feature_type=$1 AND feature_id=$2",
            feature_type, feature_id,
        )
    if not row:
        return Response(status_code=204, headers={"Cache-Control": "public, max-age=3600"})
    d = dict(row)
    d.pop("computed_at", None)
    return JSONResponse(d, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/bathymetry/gmrt/{feature_type}/{feature_id}", dependencies=[Depends(get_api_key)])
async def bathymetry_gmrt(feature_type: str, feature_id: str):
    """Return lazy-fetched GMRT grid metadata for the bbox of a feature."""
    if feature_type not in _BATHY_TABLES:
        raise HTTPException(status_code=404, detail="unknown feature_type")
    table, pk = _BATHY_TABLES[feature_type]
    async with db.pool.acquire() as conn:
        b = await conn.fetchrow(
            f"SELECT ST_XMin(geom) w, ST_YMin(geom) s, ST_XMax(geom) e, ST_YMax(geom) n "
            f"FROM {table} WHERE {pk}::text=$1",
            feature_id,
        )
    if not b or (b["e"] - b["w"]) > 180:
        return Response(status_code=204)
    res = await gmrt_for_bbox(b["w"], b["s"], b["e"], b["n"])
    if not res:
        return Response(status_code=204)
    return JSONResponse(res, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/v1/map/seamounts", dependencies=[Depends(get_api_key)])
async def get_seamounts():
    cache_key = "seamounts"
    if cache_key in _cache:
        fetched_at, data = _cache[cache_key]
        if time.monotonic() - fetched_at < CACHE_TTL:
            return Response(content=data, media_type="application/json")

    sql = """
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', coalesce(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(geom)::json,
                    'properties', json_build_object(
                        'peak_id',          peak_id,
                        'summit_depth_m',   summit_depth_m,
                        'height_m',         height_m,
                        'area_km2',         area_km2,
                        'in_2011',          in_2011,
                        'overlapping_base', overlapping_base,
                        'in_concession',    in_concession
                    )
                )
            ), '[]'::json)
        ) AS geojson
        FROM seamounts
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql)
    data = row["geojson"].encode() if isinstance(row["geojson"], str) else row["geojson"]
    _cache[cache_key] = (time.monotonic(), data)
    return Response(content=data, media_type="application/json")


@router.get("/v1/map/vents", dependencies=[Depends(get_api_key)])
async def get_vents():
    cache_key = "vents"
    if cache_key in _cache:
        fetched_at, data = _cache[cache_key]
        if time.monotonic() - fetched_at < CACHE_TTL:
            return Response(content=data, media_type="application/json")

    sql = """
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', coalesce(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(geom::geometry)::json,
                    'properties', json_build_object(
                        'id',      id,
                        'name',    name,
                        'status',  status,
                        'depth_m', depth_m,
                        'min_depth_m',       min_depth_m,
                        'max_temp_c',        max_temp_c,
                        'temp_category',     temp_category,
                        'ocean',             ocean,
                        'region',            region,
                        'jurisdiction',      jurisdiction,
                        'tectonic_setting',  tectonic_setting,
                        'discovery_year',    discovery_year,
                        'biology_notes',     biology_notes
                    )
                )
            ), '[]'::json)
        ) AS geojson
        FROM hydrothermal_vents
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql)
    if not row or not row["geojson"]:
        raise HTTPException(status_code=503, detail="Database unavailable")

    data = row["geojson"].encode() if isinstance(row["geojson"], str) else row["geojson"]
    _cache[cache_key] = (time.monotonic(), data)
    return Response(content=data, media_type="application/json")
