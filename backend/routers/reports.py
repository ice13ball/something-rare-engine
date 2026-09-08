# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Impact Evidence Report v2 endpoint.

Orchestrates: profile fetch -> alarm evaluation -> spatial distance queries ->
plume path lookup -> per-claim environmental dossiers -> findings -> scoring ->
structured JSON response.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta

import db
from auth import get_api_key, require_admin_token
from fastapi import APIRouter, Depends, HTTPException

log = logging.getLogger(__name__)
from pydantic import BaseModel, Field
from services.impact_scoring import (
    SEVERITY_RANK,
    THRESHOLDS_DOC,
    classify_severity,
    compute_claim_scores,
    compute_dataset_stats,
    compute_risk_rating,
    evaluate_alarms,
    generate_alarm_finding,
    generate_claim_env_finding,
    generate_claim_narrative,
    generate_evidence_summary,
    generate_executive_narrative,
    generate_plume_finding,
    haversine_km,
    oxygen_threshold,
    ph_threshold,
    total_trail_distance,
)

router = APIRouter(prefix="/v1/reports", tags=["reports"])


class ImpactReportRequest(BaseModel):
    platform_id: str
    hours: int = Field(default=168, ge=24, le=720)
    depth: int = Field(default=1000, ge=100, le=3000)


class ClaimReportRequest(BaseModel):
    isa_id: str


CACHE_MAX_AGE = timedelta(days=7)
REPORT_SCHEMA_VERSION = 3  # bump when report structure changes to invalidate cache

# In-memory job tracker: platform_id → {"status": "generating"|"ready"|"failed", "error": str|None}
import asyncio
_jobs: dict[str, dict] = {}

# Limit concurrent report generations to prevent VPS overload
_report_semaphore = asyncio.Semaphore(2)
QUERY_TIMEOUT_MS = 120_000  # 120s max per SQL statement


from contextlib import asynccontextmanager

@asynccontextmanager
async def _db_conn(timeout_ms: int = QUERY_TIMEOUT_MS):
    """Acquire a DB connection with statement timeout and no parallel workers."""
    async with db.pool.acquire() as conn:
        # SET (session-level) — works outside transactions, unlike SET LOCAL
        await conn.execute(f"SET statement_timeout = {timeout_ms}")
        await conn.execute("SET max_parallel_workers_per_gather = 0")
        try:
            yield conn
        finally:
            # Reset to defaults so the pooled connection is clean
            await conn.execute("SET statement_timeout = 0")
            await conn.execute("SET max_parallel_workers_per_gather = 2")


# ── Pre-computed species cache table ──────────────────────────────────────
# Avoids 3.6M-row spatial join on every report generation.
# Refreshed by calling refresh_species_cache() — runs ~once per day via cron.

async def ensure_species_cache_table():
    """Create the claim_species_cache table if it doesn't exist."""
    async with db.pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS claim_species_cache (
                isa_id TEXT NOT NULL,
                scientific_name TEXT NOT NULL,
                phylum TEXT,
                vernacular_name TEXT,
                image_url TEXT,
                records INT DEFAULT 1,
                is_endangered BOOLEAN DEFAULT false,
                iucn_category TEXT DEFAULT 'NE',
                PRIMARY KEY (isa_id, scientific_name)
            )
        """)
        # Add column if table already exists without it
        try:
            await conn.execute("ALTER TABLE claim_species_cache ADD COLUMN iucn_category TEXT DEFAULT 'NE'")
        except Exception:
            pass


async def refresh_species_cache():
    """Rebuild claim_species_cache. Delegates to the canonical implementation.

    This module carried its own copy built at `ST_DWithin(bh.geom, mc.geom, 0.5)`
    — half a DEGREE, ~55 km. `services/species_cache.py` was tightened to an exact
    10 km, but this copy was left behind, so the table had TWO live
    writers disagreeing about what "near a claim" means: whichever of
    `POST /v1/reports/refresh-species-cache` and `/admin/sync/species-cache` ran
    last silently set the radius for every reader, with nothing in the data to say
    which. 10 km is the project-wide rule (it follows from the spacing between
    claims and protected zones), so there is only one correct implementation and
    this delegates to it.
    """
    from services.species_cache import refresh_species_cache as _canonical
    return await _canonical()


async def _get_species_for_claim(conn, isa_id: str) -> list[dict]:
    """Get species from cache table (fast) with fallback to live spatial join."""
    rows = await conn.fetch(
        "SELECT scientific_name AS species, phylum, vernacular_name, image_url, "
        "records, is_endangered AS endangered, iucn_category "
        "FROM claim_species_cache WHERE isa_id = $1 "
        "ORDER BY CASE iucn_category WHEN 'CR' THEN 1 WHEN 'EN' THEN 2 WHEN 'VU' THEN 3 "
        "WHEN 'NT' THEN 4 WHEN 'LC' THEN 5 ELSE 6 END, records DESC",
        isa_id,
    )
    if rows:
        return [dict(r) for r in rows]

    # Fallback: live query (slow but works if cache is empty)
    await conn.execute("SET max_parallel_workers_per_gather = 0")
    await conn.execute(f"SET statement_timeout = {QUERY_TIMEOUT_MS}")
    rows = await conn.fetch(f"""
        SELECT bh.scientific_name AS species, bh.phylum,
               max(bh.vernacular_name) AS vernacular_name,
               max(bh.image_url) AS image_url,
               count(*) AS records,
               bool_or(COALESCE(bh.iucn_category, 'NE') IN ('CR','EN','VU')) AS endangered,
               COALESCE(max(CASE WHEN bh.iucn_category IN ('CR','EN','VU','NT','LC','DD')
                                 THEN bh.iucn_category END), 'NE') AS iucn_category
        FROM biodiversity_hotspots bh, mining_contracts mc
        WHERE mc.isa_id = $1
          -- 10 km is the project-wide radius for "species near a claim";
          -- the degree clause is an index-friendly pre-filter on the bh.geom GIST
          -- index, the geography clause refines it to exactly 10 km at any latitude.
          AND ST_DWithin(bh.geom, mc.geom, 0.12)
          AND ST_DWithin(bh.geom::geography, mc.geom::geography, 10000)
        GROUP BY bh.scientific_name, bh.phylum
        ORDER BY CASE COALESCE(max(CASE WHEN bh.iucn_category IN ('CR','EN','VU','NT','LC','DD')
                                        THEN bh.iucn_category END), 'NE')
                 WHEN 'CR' THEN 1 WHEN 'EN' THEN 2 WHEN 'VU' THEN 3
                 WHEN 'NT' THEN 4 WHEN 'LC' THEN 5 ELSE 6 END,
                 count(*) DESC
        LIMIT 200
    """, isa_id)
    return [dict(r) for r in rows]


async def _get_species_for_claims(conn, claim_ids: list[str]) -> dict[str, list]:
    """Get species for multiple claims from cache (fast)."""
    species_by_claim: dict[str, list] = {cid: [] for cid in claim_ids}
    if not claim_ids:
        return species_by_claim

    rows = await conn.fetch(
        "SELECT isa_id, scientific_name AS species, phylum, vernacular_name, image_url, "
        "records, is_endangered AS endangered, iucn_category "
        "FROM claim_species_cache WHERE isa_id = ANY($1::text[]) "
        "ORDER BY CASE iucn_category WHEN 'CR' THEN 1 WHEN 'EN' THEN 2 WHEN 'VU' THEN 3 "
        "WHEN 'NT' THEN 4 WHEN 'LC' THEN 5 ELSE 6 END, records DESC",
        claim_ids,
    )
    if rows:
        for r in rows:
            species_by_claim.setdefault(r["isa_id"], []).append({
                "species": r["species"], "phylum": r["phylum"],
                "vernacular_name": r["vernacular_name"], "image_url": r["image_url"],
                "records": r["records"], "endangered": r["endangered"],
                "iucn_category": r["iucn_category"],
            })
        return species_by_claim

    # Fallback: live query (limited)
    await conn.execute("SET max_parallel_workers_per_gather = 0")
    sp_rows = await conn.fetch("""
        SELECT mc.isa_id,
               bh.scientific_name AS species, bh.phylum,
               max(bh.vernacular_name) AS vernacular_name,
               max(bh.image_url) AS image_url,
               count(*) AS records,
               bool_or(COALESCE(bh.iucn_category, 'NE') IN ('CR','EN','VU')) AS endangered,
               COALESCE(max(CASE WHEN bh.iucn_category IN ('CR','EN','VU','NT','LC','DD')
                                 THEN bh.iucn_category END), 'NE') AS iucn_category
        FROM mining_contracts mc
        JOIN biodiversity_hotspots bh
          -- 10 km, index-friendly pre-filter then exact refine — see the sibling
          -- query above.
          ON ST_DWithin(bh.geom, mc.geom, 0.12)
         AND ST_DWithin(bh.geom::geography, mc.geom::geography, 10000)
        WHERE mc.isa_id = ANY($1::text[])
        GROUP BY mc.isa_id, bh.scientific_name, bh.phylum
        LIMIT 500
    """, claim_ids)
    for spr in sp_rows:
        species_by_claim.setdefault(spr["isa_id"], []).append({
            "species": spr["species"], "phylum": spr["phylum"],
            "vernacular_name": spr["vernacular_name"], "image_url": spr["image_url"],
            "records": spr["records"], "endangered": spr["endangered"],
            "iucn_category": spr["iucn_category"],
        })
    return species_by_claim


async def _check_cache(platform_id: str):
    """Return cached report dict if fresh and schema-compatible, else None."""
    async with db.pool.acquire() as conn:
        cached = await conn.fetchrow(
            "SELECT report_json, generated_at FROM report_cache WHERE platform_id = $1",
            platform_id,
        )
    if cached and (datetime.now(timezone.utc) - cached["generated_at"]) < CACHE_MAX_AGE:
        data = json.loads(cached["report_json"])
        if data.get("_schema_version") == REPORT_SCHEMA_VERSION:
            return data
    return None


async def _do_generate(platform_id: str, hours: int, depth: int):
    """Run full report generation in background, write to cache, update _jobs."""
    async with _report_semaphore:
        try:
            req = ImpactReportRequest(platform_id=platform_id, hours=hours, depth=depth)
            result = await _generate_report_core(req)
            _jobs[platform_id] = {"status": "ready", "error": None}
            print(f"[JOBS] report generation complete for {platform_id}")
        except Exception as exc:
            _jobs[platform_id] = {"status": "failed", "error": str(exc)}
            print(f"[JOBS] report generation FAILED for {platform_id}: {exc}")


async def _do_generate_claim(isa_id: str):
    """Run claim report generation in background."""
    async with _report_semaphore:
        try:
            await _generate_claim_report_core(isa_id)
            _jobs[f"claim:{isa_id}"] = {"status": "ready", "error": None}
            print(f"[JOBS] claim report generation complete for {isa_id}")
        except Exception as exc:
            _jobs[f"claim:{isa_id}"] = {"status": "failed", "error": str(exc)}
            print(f"[JOBS] claim report generation FAILED for {isa_id}: {exc}")


@router.post("/impact", dependencies=[Depends(get_api_key)])
async def generate_impact_report(req: ImpactReportRequest):
    if db.pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # ── 0. Check cache ────────────────────────────────────────────────────
    cached = await _check_cache(req.platform_id)
    if cached:
        return cached

    # ── 1. Already generating? ────────────────────────────────────────────
    job = _jobs.get(req.platform_id)
    if job and job["status"] == "generating":
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=202, content={"status": "generating", "platform_id": req.platform_id})

    # ── 2. Kick off background generation ─────────────────────────────────
    _jobs[req.platform_id] = {"status": "generating", "error": None}
    asyncio.create_task(_do_generate(req.platform_id, req.hours, req.depth))
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=202, content={"status": "generating", "platform_id": req.platform_id})


@router.get("/impact/{platform_id}/status", dependencies=[Depends(get_api_key)])
async def report_status(platform_id: str):
    """Poll endpoint — returns generation status."""
    if db.pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Check cache first (may have been generated by a prior request)
    cached = await _check_cache(platform_id)
    if cached:
        _jobs.pop(platform_id, None)
        return {"status": "ready", "platform_id": platform_id}

    job = _jobs.get(platform_id)
    if not job:
        return {"status": "none", "platform_id": platform_id}
    return {"status": job["status"], "platform_id": platform_id, "error": job.get("error")}


@router.get("/impact/{platform_id}", dependencies=[Depends(get_api_key)])
async def get_cached_report(platform_id: str):
    """Fetch a ready report from cache."""
    if db.pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    cached = await _check_cache(platform_id)
    if cached:
        _jobs.pop(platform_id, None)
        return cached
    raise HTTPException(status_code=404, detail="Report not ready or not found")


@router.post("/claim-impact", dependencies=[Depends(get_api_key)])
async def generate_claim_report(req: ClaimReportRequest):
    if db.pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    cached = await _check_cache(f"claim:{req.isa_id}")
    if cached:
        return cached
    job_key = f"claim:{req.isa_id}"
    job = _jobs.get(job_key)
    if job and job["status"] == "generating":
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=202, content={"status": "generating", "isa_id": req.isa_id})
    _jobs[job_key] = {"status": "generating", "error": None}
    asyncio.create_task(_do_generate_claim(req.isa_id))
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=202, content={"status": "generating", "isa_id": req.isa_id})


@router.get("/claim-impact/{isa_id}/status", dependencies=[Depends(get_api_key)])
async def claim_report_status(isa_id: str):
    if db.pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    cached = await _check_cache(f"claim:{isa_id}")
    if cached:
        _jobs.pop(f"claim:{isa_id}", None)
        return {"status": "ready", "isa_id": isa_id}
    job = _jobs.get(f"claim:{isa_id}")
    if not job:
        return {"status": "none", "isa_id": isa_id}
    return {"status": job["status"], "isa_id": isa_id, "error": job.get("error")}


@router.get("/claim-impact/{isa_id}", dependencies=[Depends(get_api_key)])
async def get_cached_claim_report(isa_id: str):
    if db.pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    cached = await _check_cache(f"claim:{isa_id}")
    if cached:
        _jobs.pop(f"claim:{isa_id}", None)
        return cached
    raise HTTPException(status_code=404, detail="Claim report not ready or not found")


async def _generate_claim_report_core(isa_id: str):
    """Generate a comprehensive environmental impact report for a mining claim."""

    # ── 1. Fetch claim details ─────────────────────────────────────────
    async with db.pool.acquire() as conn:
        claim = await conn.fetchrow("""
            SELECT isa_id, contractor_name, resource_type, area_km2,
                   to_char(act_date, 'YYYY-MM-DD') AS act_date,
                   to_char(expiry_date, 'YYYY-MM-DD') AS expiry_date,
                   is_high_risk, jurisdiction_text,
                   nearest_eez_country, nearest_eez_dist_km,
                   nearest_unesco_site, nearest_unesco_dist_km,
                   ST_X(ST_Centroid(geom::geometry)) AS centroid_lon,
                   ST_Y(ST_Centroid(geom::geometry)) AS centroid_lat,
                   ST_AsGeoJSON(geom::geometry)::json AS geojson
            FROM mining_contracts
            WHERE isa_id = $1
        """, isa_id)

    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {isa_id} not found")

    # ── 2. Vents within 50km ───────────────────────────────────────────
    async with db.pool.acquire() as conn:
        vent_rows = await conn.fetch("""
            SELECT hv.name, hv.status, hv.depth_m,
                   ST_Y(hv.geom::geometry) AS lat, ST_X(hv.geom::geometry) AS lon,
                   ST_Distance(hv.geom, mc.geom::geography) / 1000.0 AS distance_km
            FROM hydrothermal_vents hv, mining_contracts mc
            WHERE mc.isa_id = $1
              AND ST_DWithin(hv.geom, mc.geom::geography, 50000)
            ORDER BY distance_km
        """, isa_id)
    vents = [dict(r) for r in vent_rows]

    # ── 3. Seamounts within 10km ───────────────────────────────────────
    async with db.pool.acquire() as conn:
        sm_rows = await conn.fetch("""
            SELECT s.summit_depth_m, s.height_m, s.area_km2,
                   ST_Y(s.geom::geometry) AS lat, ST_X(s.geom::geometry) AS lon,
                   ST_Distance(s.geom::geography, mc.geom::geography) / 1000.0 AS distance_km
            FROM seamounts s, mining_contracts mc
            WHERE mc.isa_id = $1
              AND ST_DWithin(s.geom::geography, mc.geom::geography, 10000)
            ORDER BY distance_km
        """, isa_id)
    seamounts = [dict(r) for r in sm_rows]

    # ── 3b. Chess sites within 50km ────────────────────────────────────
    async with db.pool.acquire() as conn:
        chess_rows = await conn.fetch("""
            SELECT
                co.locality, co.habitat_type,
                AVG(co.lat) AS lat, AVG(co.lon) AS lon,
                AVG(co.depth_m) AS depth_m,
                COUNT(DISTINCT co.species)::INTEGER AS species_count,
                MIN(ST_Distance(mc.geom::geography, co.geom::geography)) / 1000.0 AS distance_km
            FROM chess_occurrences co, mining_contracts mc
            WHERE mc.isa_id = $1
              AND co.habitat_type != 'vent'
              AND ST_DWithin(mc.geom::geography, co.geom::geography, 50000)
            GROUP BY co.locality, co.habitat_type
            ORDER BY distance_km
            LIMIT 20
        """, isa_id)
    chess_sites = [
        {
            "locality": r["locality"],
            "habitat_type": r["habitat_type"],
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "depth_m": float(r["depth_m"]) if r["depth_m"] is not None else None,
            "species_count": r["species_count"],
            "distance_km": round(float(r["distance_km"]), 2),
        }
        for r in chess_rows
    ]

    # ── 4. Species within 50km (from pre-computed cache) ────────────────
    async with db.pool.acquire() as conn:
        species = await _get_species_for_claim(conn, isa_id)
    endangered_count = sum(1 for s in species if s.get("iucn_category") in ("CR", "EN", "VU"))
    cr_en_count = sum(1 for s in species if s.get("iucn_category") in ("CR", "EN"))
    iucn_breakdown = {}
    for s in species:
        cat = s.get("iucn_category", "NE")
        iucn_breakdown[cat] = iucn_breakdown.get(cat, 0) + 1

    # ── 5. Nearby Argo floats (profiles within 200km, last 90 days) ────
    async with db.pool.acquire() as conn:
        argo_rows = await conn.fetch("""
            SELECT ap.profile_id, ap.platform_id,
                   to_char(ap.profile_date, 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS date,
                   ST_X(ap.geom::geometry) AS lon, ST_Y(ap.geom::geometry) AS lat,
                   ap.max_depth_m, ap.surface_temp_c, ap.surface_salinity,
                   ap.deep_temp_c, ap.deep_salinity, ap.deep_pressure_m,
                   ap.oxygen_umol_kg, ap.ph,
                   ST_Distance(ap.geom, mc.geom::geography) / 1000.0 AS distance_km
            FROM argo_profiles ap, mining_contracts mc
            WHERE mc.isa_id = $1
              AND ST_DWithin(ap.geom, mc.geom::geography, 200000)
              AND ap.profile_date >= NOW() - INTERVAL '90 days'
            ORDER BY ap.profile_date ASC
        """, isa_id)

    profiles = []
    for r in argo_rows:
        profiles.append({
            "profile_id": r["profile_id"],
            "platform_id": r["platform_id"],
            "date": r["date"],
            "lon": r["lon"], "lat": r["lat"],
            "depth_m": r["max_depth_m"],
            "surface_temp": r["surface_temp_c"],
            "surface_salinity": r["surface_salinity"],
            "deep_temp": r["deep_temp_c"],
            "deep_salinity": r["deep_salinity"],
            "oxygen": r["oxygen_umol_kg"],
            "ph": r["ph"],
            "distance_to_claim_km": round(r["distance_km"], 2),
            "nearest_claim_id": isa_id,
            "nearest_claim_name": claim["contractor_name"],
        })

    # ── 6. Evaluate alarms on nearby profiles ──────────────────────────
    stats = compute_dataset_stats(profiles) if profiles else {}
    alarm_log = []
    alarm_counter = 0
    for p in profiles:
        alarms, severities = evaluate_alarms(p, stats)
        p["alarms"] = alarms
        p["alarm_severities"] = severities
        for alarm_type in alarms:
            alarm_counter += 1
            depth = p.get("depth_m")
            if alarm_type == "low_oxygen":
                threshold = oxygen_threshold(depth)
            elif alarm_type == "low_ph":
                threshold = ph_threshold(depth)
            else:
                threshold = None

            value_key = {
                "low_oxygen": "oxygen",
                "low_ph": "ph",
                "temp_anomaly": "surface_temp",
                "salinity_anomaly": "surface_salinity",
            }.get(alarm_type, alarm_type)

            severity = classify_severity(
                alarm_type,
                p.get("distance_to_claim_km") or 999,
                endangered_count,
            )
            alarm_log.append({
                "alarm_id": alarm_counter,
                "profile_id": p["profile_id"],
                "platform_id": p["platform_id"],
                "date": p["date"],
                "lon": p["lon"], "lat": p["lat"],
                "type": alarm_type,
                "value": p.get(value_key),
                "threshold": threshold,
                "severity": severity,
                "distance_km": p.get("distance_to_claim_km"),
            })

    # ── 7. Plume attributions to this claim ────────────────────────────
    # Query ALL plume paths attributed to this contractor, not just from nearby profiles
    plume_attributions = []
    async with db.pool.acquire() as conn:
        plume_rows = await conn.fetch("""
            SELECT pp.profile_id, pp.platform_id, pp.origin_lon, pp.origin_lat,
                   pp.contractor_name, pp.speed_cms,
                   to_char(pp.profile_date, 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS date,
                   ap.oxygen_umol_kg, ap.ph, ap.surface_temp_c,
                   ap.surface_salinity, ap.deep_temp_c, ap.max_depth_m,
                   ST_X(ap.geom::geometry) AS float_lon,
                   ST_Y(ap.geom::geometry) AS float_lat
            FROM plume_paths pp
            LEFT JOIN argo_profiles ap ON ap.profile_id = pp.profile_id
            WHERE pp.contractor_name = $1
            ORDER BY pp.profile_date DESC
        """, claim["contractor_name"])
        for pr in plume_rows:
            float_lon = pr["float_lon"]
            float_lat = pr["float_lat"]
            plume_attributions.append({
                "profile_id": pr["profile_id"],
                "platform_id": pr["platform_id"],
                "date": pr["date"],
                "backtrack_origin": [pr["origin_lon"], pr["origin_lat"]],
                "source_claim_id": isa_id,
                "source_claim_name": pr["contractor_name"],
                "distance_to_source_km": round(haversine_km(
                    float_lon if float_lon is not None else pr["origin_lon"],
                    float_lat if float_lat is not None else pr["origin_lat"],
                    pr["origin_lon"], pr["origin_lat"]
                ), 1),
                "speed_cms": pr["speed_cms"],
                "measurements": {
                    "oxygen_umol_kg": pr["oxygen_umol_kg"],
                    "ph": pr["ph"],
                    "temp_c": pr["surface_temp_c"],
                    "salinity": pr["surface_salinity"],
                    "deep_temp_c": pr["deep_temp_c"],
                    "depth_m": pr["max_depth_m"],
                },
            })

    # ── 8. Build sensor timelines ──────────────────────────────────────
    sensor_timelines = {"oxygen": [], "ph": [], "temp": [], "salinity": []}
    for p in profiles:
        base = {"date": p["date"], "claim_distance_km": p.get("distance_to_claim_km"),
                "platform_id": p.get("platform_id")}
        if p.get("oxygen") is not None:
            sensor_timelines["oxygen"].append({
                **base, "value": p["oxygen"],
                "threshold": oxygen_threshold(p.get("depth_m")),
                "alarmed": "low_oxygen" in p.get("alarms", []),
            })
        if p.get("ph") is not None:
            sensor_timelines["ph"].append({
                **base, "value": p["ph"],
                "threshold": ph_threshold(p.get("depth_m")),
                "alarmed": "low_ph" in p.get("alarms", []),
            })
        if p.get("surface_temp") is not None:
            sensor_timelines["temp"].append({
                **base, "value": p["surface_temp"], "threshold": None,
                "alarmed": "temp_anomaly" in p.get("alarms", []),
            })
        if p.get("surface_salinity") is not None:
            sensor_timelines["salinity"].append({
                **base, "value": p["surface_salinity"], "threshold": None,
                "alarmed": "salinity_anomaly" in p.get("alarms", []),
            })

    # ── 9. Generate findings ───────────────────────────────────────────
    findings = []
    finding_num = 0

    # Environmental findings
    if vents:
        finding_num += 1
        findings.append(generate_claim_env_finding(
            finding_num, "vent_proximity", isa_id, claim["contractor_name"],
            {"count": len(vents), "active_count": sum(1 for v in vents if v.get("status") == "Active")},
        ))
    if endangered_count > 0:
        finding_num += 1
        findings.append(generate_claim_env_finding(
            finding_num, "species_risk", isa_id, claim["contractor_name"],
            {"endangered_count": endangered_count, "cr_en_count": cr_en_count,
             "total_count": len(species),
             "records": sum(s.get("records", 0) for s in species)},
        ))
    if seamounts:
        finding_num += 1
        findings.append(generate_claim_env_finding(
            finding_num, "seamount_overlap", isa_id, claim["contractor_name"],
            {"count": len(seamounts)},
        ))
    if chess_sites:
        finding_num += 1
        seep_count = sum(1 for s in chess_sites if s["habitat_type"] == "seep")
        whale_count = sum(1 for s in chess_sites if s["habitat_type"] == "whale_fall")
        findings.append({
            "number": finding_num,
            "type": "chess_proximity",
            "severity": "High" if whale_count > 0 else "Moderate",
            "observation": (
                f"{len(chess_sites)} chemosynthetic ecosystem(s) within 50 km of concession {isa_id} — "
                + (f"{seep_count} cold seep(s)" if seep_count else "")
                + (" and " if seep_count and whale_count else "")
                + (f"{whale_count} whale fall(s)" if whale_count else "")
                + (f"{sum(1 for s in chess_sites if s['habitat_type'] == 'omz')} OMZ site(s)" if not seep_count and not whale_count else "")
                + " from the ChEssBase dataset."
            ),
            "threshold_detail": "Chemosynthetic ecosystems are primary biodiversity sources; whale falls classified High risk under ISA environmental guidelines.",
            "spatial_link": f"Concession {isa_id} ({claim['contractor_name']})",
            "environmental_context": "These habitats support life through chemical energy rather than sunlight. Sediment plumes from mining can smother seep communities; acoustic disturbance can disrupt chemosynthetic food webs.",
            "refs": {"claim_id": isa_id},
            "chess_sites": chess_sites[:5],
        })

    # Alarm findings (reuse existing generator)
    for p in profiles:
        for alarm_type in p.get("alarms", []):
            finding_num += 1
            claim_info = {
                "isa_id": isa_id,
                "contractor_name": claim["contractor_name"],
                "distance_km": p.get("distance_to_claim_km", 999),
            }
            env_ctx = {
                "vent_count": len(vents),
                "species_count": len(species),
                "endangered_count": endangered_count,
                "seamount_count": len(seamounts),
            }
            findings.append(generate_alarm_finding(
                finding_num, alarm_type, p, stats, claim_info, env_ctx,
            ))

    # Plume findings
    for pa in plume_attributions:
        finding_num += 1
        p = next((pp for pp in profiles if pp["profile_id"] == pa["profile_id"]), {})
        claim_info = {"isa_id": isa_id, "contractor_name": claim["contractor_name"]}
        findings.append(generate_plume_finding(
            finding_num, pa, p, claim_info, 168,
        ))

    # Sort by severity
    findings.sort(key=lambda f: SEVERITY_RANK.get(f.get("severity", "Low"), 99))
    for i, f in enumerate(findings, 1):
        f["number"] = i

    # ── 10. Risk rating + narrative ────────────────────────────────────
    risk_rating = compute_risk_rating(findings)
    unique_floats = list({p["platform_id"] for p in profiles})
    narrative = generate_claim_narrative(
        isa_id, claim["contractor_name"], claim["resource_type"],
        claim["area_km2"], vents, seamounts, len(species), endangered_count,
        cr_en_count, len(unique_floats), len(alarm_log), len(plume_attributions), risk_rating,
    )
    evidence_summary = generate_evidence_summary(findings, risk_rating)

    # ── 11. UNESCO / EEZ proximity ─────────────────────────────────────
    nearest_unesco = None
    if claim["nearest_unesco_site"]:
        nearest_unesco = {"name": claim["nearest_unesco_site"], "distance_km": claim["nearest_unesco_dist_km"]}
    nearest_eez = None
    if claim["nearest_eez_country"]:
        nearest_eez = {"country": claim["nearest_eez_country"], "distance_km": claim["nearest_eez_dist_km"]}

    # ── 12. Claim polygon GeoJSON ──────────────────────────────────────
    claim_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"isa_id": isa_id, "contractor_name": claim["contractor_name"]},
            "geometry": claim["geojson"],
        }],
    }

    # ── 13. Build response ─────────────────────────────────────────────
    response = {
        "_schema_version": REPORT_SCHEMA_VERSION,
        "report_id": str(uuid.uuid4()),
        "report_type": "claim",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "isa_id": isa_id,
        "claim": {
            "isa_id": claim["isa_id"],
            "contractor_name": claim["contractor_name"],
            "resource_type": claim["resource_type"],
            "area_km2": claim["area_km2"],
            "act_date": claim["act_date"],
            "expiry_date": claim["expiry_date"],
            "is_high_risk": claim["is_high_risk"],
            "jurisdiction_text": claim["jurisdiction_text"],
            "centroid_lon": claim["centroid_lon"],
            "centroid_lat": claim["centroid_lat"],
        },
        "executive_summary": {
            "risk_rating": risk_rating,
            "narrative": narrative,
            "key_stats": {
                "vent_count": len(vents),
                "seamount_count": len(seamounts),
                "chess_site_count": len(chess_sites),
                "species_count": len(species),
                "endangered_species_count": endangered_count,
                "cr_en_species_count": cr_en_count,
                "iucn_breakdown": iucn_breakdown,
                "nearby_float_count": len(unique_floats),
                "alarm_count": len(alarm_log),
                "plume_attribution_count": len(plume_attributions),
                "finding_count": len(findings),
            },
        },
        "environmental_context": {
            "vents": vents,
            "seamounts": seamounts,
            "chess_sites": chess_sites,
            "species": {"curated": species[:30], "total_count": len(species)},
            "unesco_eez": {"nearest_unesco": nearest_unesco, "nearest_eez": nearest_eez},
        },
        "monitoring_evidence": {
            "profiles": profiles,
            "unique_floats": unique_floats,
            "date_range": {
                "start": profiles[0]["date"] if profiles else None,
                "end": profiles[-1]["date"] if profiles else None,
            },
        },
        "sensor_timelines": sensor_timelines,
        "alarm_log": alarm_log,
        "plume_attributions": plume_attributions,
        "findings": findings,
        "evidence_summary": evidence_summary,
        "claim_polygon": claim_geojson,
        "methodology": {
            "alarm_thresholds": THRESHOLDS_DOC,
            "scoring_formula": "environmental_score + alarm_score + plume_score",
            "environmental_radius": {"vents_km": 50, "seamounts_km": 10, "species_km": 50, "argo_km": 200},
            "data_sources": [
                "International Seabed Authority (concession boundaries)",
                "InterRidge v3.4 (hydrothermal vents)",
                "OBIS (biodiversity hotspots)",
                "Yesson et al. 2011 (seamounts)",
                "Argo Programme (autonomous profiling floats)",
                "Copernicus Marine Service (ocean currents / plume backtracking)",
            ],
        },
        "appendices": {
            "full_species_list": species,
            "full_vent_list": vents,
            "full_seamount_list": seamounts,
            "claim_polygon": claim_geojson,
        },
    }

    # ── Cache ──────────────────────────────────────────────────────────
    try:
        async with db.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO report_cache (platform_id, report_json, risk_rating, headline, finding_count, claim_count, generated_at)
                VALUES ($1, $2::jsonb, $3, $4, $5, $6, NOW())
                ON CONFLICT (platform_id) DO UPDATE SET
                    report_json = EXCLUDED.report_json,
                    risk_rating = EXCLUDED.risk_rating,
                    headline = EXCLUDED.headline,
                    finding_count = EXCLUDED.finding_count,
                    claim_count = EXCLUDED.claim_count,
                    generated_at = NOW()
            """,
                f"claim:{isa_id}",
                json.dumps(response, default=str),
                risk_rating,
                narrative[:200],
                len(findings),
                1,
            )
        print(f"[CACHE] claim report cached for {isa_id}")
    except Exception as exc:
        print(f"[CACHE] claim report cache write FAILED for {isa_id}: {exc}")

    return response


async def _generate_report_core(req: ImpactReportRequest):
    """Core generation logic — extracted so it can run as a background task."""

    # ── 1. Fetch all profiles for this platform (90-day rolling window) ──
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT profile_id, platform_id,
                   to_char(profile_date, 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS date,
                   ST_X(geom::geometry) AS lon, ST_Y(geom::geometry) AS lat,
                   max_depth_m, surface_temp_c, surface_salinity,
                   deep_temp_c, deep_salinity, deep_pressure_m,
                   oxygen_umol_kg, ph
            FROM argo_profiles
            WHERE platform_id = $1
            ORDER BY profile_date ASC
        """, req.platform_id)

    if not rows:
        raise HTTPException(status_code=404, detail=f"No profiles found for platform {req.platform_id}")

    # Normalize to dicts with spec field names
    profiles = []
    for r in rows:
        profiles.append({
            "profile_id": r["profile_id"],
            "date": r["date"],
            "lon": r["lon"],
            "lat": r["lat"],
            "depth_m": r["max_depth_m"],
            "surface_temp": r["surface_temp_c"],
            "surface_salinity": r["surface_salinity"],
            "deep_temp": r["deep_temp_c"],
            "deep_salinity": r["deep_salinity"],
            "oxygen": r["oxygen_umol_kg"],
            "ph": r["ph"],
        })

    # ── 2. Compute dataset stats for anomaly detection ───────────────────
    stats = compute_dataset_stats(profiles)

    # ── 3. Find nearest claim + distance for all profiles in one query ───
    async with db.pool.acquire() as conn:
        lons = [p["lon"] for p in profiles]
        lats = [p["lat"] for p in profiles]
        claim_rows = await conn.fetch("""
            WITH pts AS (
                SELECT idx, lon, lat
                FROM UNNEST($1::int[], $2::float8[], $3::float8[]) AS t(idx, lon, lat)
            )
            SELECT DISTINCT ON (pts.idx)
                   pts.idx,
                   mc.isa_id, mc.contractor_name, mc.resource_type,
                   mc.area_km2, mc.is_high_risk,
                   to_char(mc.expiry_date, 'YYYY-MM-DD') AS expiry_date,
                   mc.nearest_eez_country, mc.nearest_eez_dist_km,
                   mc.nearest_unesco_site, mc.nearest_unesco_dist_km,
                   ST_Distance(mc.geom::geography,
                               ST_SetSRID(ST_MakePoint(pts.lon, pts.lat), 4326)::geography) / 1000.0 AS dist_km
            FROM pts
            CROSS JOIN LATERAL (
                SELECT isa_id, contractor_name, resource_type, geom,
                       area_km2, is_high_risk, expiry_date,
                       nearest_eez_country, nearest_eez_dist_km,
                       nearest_unesco_site, nearest_unesco_dist_km
                FROM mining_contracts
                ORDER BY geom <-> ST_SetSRID(ST_MakePoint(pts.lon, pts.lat), 4326)
                LIMIT 1
            ) mc
            ORDER BY pts.idx
        """, list(range(len(profiles))), lons, lats)

        claim_map = {r["idx"]: r for r in claim_rows}
        for i, p in enumerate(profiles):
            cr = claim_map.get(i)
            if cr:
                p["nearest_claim_id"] = cr["isa_id"]
                p["nearest_claim_name"] = cr["contractor_name"]
                p["resource_type"] = cr["resource_type"]
                p["distance_to_claim_km"] = round(cr["dist_km"], 2)
                p["_claim_extra"] = {
                    "area_km2": cr["area_km2"],
                    "is_high_risk": cr["is_high_risk"],
                    "expiry_date": cr["expiry_date"],
                    "nearest_eez_country": cr["nearest_eez_country"],
                    "nearest_eez_dist_km": cr["nearest_eez_dist_km"],
                    "nearest_unesco_site": cr["nearest_unesco_site"],
                    "nearest_unesco_dist_km": cr["nearest_unesco_dist_km"],
                }
            else:
                p["nearest_claim_id"] = None
                p["nearest_claim_name"] = None
                p["resource_type"] = None
                p["distance_to_claim_km"] = None
                p["_claim_extra"] = {}

    # ── 4. Evaluate alarms for each profile ──────────────────────────────
    alarm_counter = 0
    for p in profiles:
        alarms, severities = evaluate_alarms(p, stats)
        p["alarms"] = alarms
        p["alarm_severities"] = severities
        # Assign unique alarm IDs for alarm_log
        p["_alarm_ids"] = {}
        for a in alarms:
            alarm_counter += 1
            p["_alarm_ids"][a] = alarm_counter

    # ── 5. Fetch plume paths for ALL profiles ────────────────────────────
    profile_map = {p["profile_id"]: p for p in profiles}
    plume_attributions = []
    async with db.pool.acquire() as conn:
        plume_rows = await conn.fetch("""
            SELECT profile_id, origin_lon, origin_lat, contractor_name, speed_cms
            FROM plume_paths
            WHERE profile_id = ANY($1::text[])
        """, list(profile_map.keys()))

        for pr in plume_rows:
            p = profile_map[pr["profile_id"]]
            plume_attributions.append({
                "profile_id": pr["profile_id"],
                "backtrack_origin": [pr["origin_lon"], pr["origin_lat"]],
                "source_claim_id": p.get("nearest_claim_id"),
                "source_claim_name": pr["contractor_name"] or p.get("nearest_claim_name"),
                "distance_to_source_km": round(haversine_km(
                    p["lon"], p["lat"],
                    pr["origin_lon"], pr["origin_lat"]
                ), 1),
                "hours_backtracked": req.hours,
                "speed_cms": pr["speed_cms"],
            })

    # ── 5b. Fetch claim polygons for the mini-map ────────────────────────
    claim_ids = list({p["nearest_claim_id"] for p in profiles if p.get("nearest_claim_id")})
    claim_geojson = {"type": "FeatureCollection", "features": []}
    if claim_ids:
        async with db.pool.acquire() as conn:
            geo_rows = await conn.fetch("""
                SELECT isa_id, contractor_name,
                       ST_AsGeoJSON(geom::geometry)::json AS geojson
                FROM mining_contracts
                WHERE isa_id = ANY($1::text[])
            """, claim_ids)
            for gr in geo_rows:
                claim_geojson["features"].append({
                    "type": "Feature",
                    "properties": {"isa_id": gr["isa_id"], "contractor_name": gr["contractor_name"]},
                    "geometry": gr["geojson"],
                })

    # ── 6. Per-claim environmental dossiers ──────────────────────────────
    claim_scores = compute_claim_scores(profiles, stats)
    claim_score_map = {cs["isa_id"]: cs for cs in claim_scores}

    # Update plume_hits count
    plume_claim_names = {}
    for pa in plume_attributions:
        name = pa["source_claim_name"]
        plume_claim_names[name] = plume_claim_names.get(name, 0) + 1
    for cs in claim_scores:
        cs["plume_hits"] = plume_claim_names.get(cs["contractor_name"], 0)

    # Build per-claim extra info from profiles
    claim_extra_map: dict[str, dict] = {}
    for p in profiles:
        cid = p.get("nearest_claim_id")
        if cid and cid not in claim_extra_map and p.get("_claim_extra"):
            claim_extra_map[cid] = p["_claim_extra"]

    # 6a. Vents within 50km of each claim
    vent_by_claim: dict[str, list] = {cid: [] for cid in claim_ids}
    if claim_ids:
        async with db.pool.acquire() as conn:
            vent_rows = await conn.fetch("""
                SELECT mc.isa_id,
                       hv.name, hv.status, hv.depth_m
                FROM mining_contracts mc
                JOIN hydrothermal_vents hv
                  ON ST_DWithin(hv.geom, mc.geom::geography, 50000)
                WHERE mc.isa_id = ANY($1::text[])
            """, claim_ids)
            for vr in vent_rows:
                vent_by_claim.setdefault(vr["isa_id"], []).append({
                    "name": vr["name"],
                    "status": vr["status"],
                    "depth_m": vr["depth_m"],
                })

    # 6b. Seamounts within 10km of each claim
    seamount_by_claim: dict[str, list] = {cid: [] for cid in claim_ids}
    if claim_ids:
        async with db.pool.acquire() as conn:
            sm_rows = await conn.fetch("""
                SELECT mc.isa_id,
                       s.summit_depth_m, s.height_m, s.area_km2
                FROM mining_contracts mc
                JOIN seamounts s
                  ON ST_DWithin(s.geom::geography, mc.geom::geography, 10000)
                WHERE mc.isa_id = ANY($1::text[])
            """, claim_ids)
            for sr in sm_rows:
                seamount_by_claim.setdefault(sr["isa_id"], []).append({
                    "summit_depth_m": sr["summit_depth_m"],
                    "height_m": sr["height_m"],
                    "area_km2": sr["area_km2"],
                })

    # 6c. OBIS species within 50km of each claim (from pre-computed cache)
    async with db.pool.acquire() as conn:
        species_by_claim = await _get_species_for_claims(conn, claim_ids)

    # Build plume evidence per claim
    plume_by_claim: dict[str, list] = {cid: [] for cid in claim_ids}
    for pa in plume_attributions:
        cid = pa.get("source_claim_id")
        if cid:
            plume_by_claim.setdefault(cid, []).append(pa)

    # Build alarm IDs per claim
    alarm_ids_by_claim: dict[str, list[int]] = {cid: [] for cid in claim_ids}
    for p in profiles:
        cid = p.get("nearest_claim_id")
        if cid:
            for aid in p.get("_alarm_ids", {}).values():
                alarm_ids_by_claim.setdefault(cid, []).append(aid)

    # Assemble dossiers
    claim_dossiers = []
    # env_context cache per claim for findings generation
    env_context_by_claim: dict[str, dict] = {}
    for cid in claim_ids:
        extra = claim_extra_map.get(cid, {})
        cs = claim_score_map.get(cid, {})
        vents = vent_by_claim.get(cid, [])
        seamounts = seamount_by_claim.get(cid, [])
        species_list = species_by_claim.get(cid, [])
        plumes = plume_by_claim.get(cid, [])
        attributed_alarms = alarm_ids_by_claim.get(cid, [])

        # Profiles within 50km of this claim
        profiles_within_50 = [
            p for p in profiles
            if p.get("nearest_claim_id") == cid and (p.get("distance_to_claim_km") or 999) <= 50
        ]
        min_dist = min(
            (p.get("distance_to_claim_km") for p in profiles if p.get("nearest_claim_id") == cid and p.get("distance_to_claim_km") is not None),
            default=999
        )

        # Top 20 species, endangered first
        sorted_species = sorted(species_list, key=lambda s: (not s.get("endangered", False), -s.get("records", 0)))
        curated_species = sorted_species[:20]

        endangered_count = sum(1 for s in species_list if s.get("endangered"))

        env_context = {
            "vent_count": len(vents),
            "species_count": len(species_list),
            "endangered_count": endangered_count,
            "seamount_count": len(seamounts),
        }
        env_context_by_claim[cid] = env_context

        # UNESCO / EEZ proximity
        nearest_unesco = None
        if extra.get("nearest_unesco_site"):
            nearest_unesco = {
                "name": extra["nearest_unesco_site"],
                "distance_km": extra.get("nearest_unesco_dist_km"),
            }
        nearest_eez = None
        if extra.get("nearest_eez_country"):
            nearest_eez = {
                "country": extra["nearest_eez_country"],
                "distance_km": extra.get("nearest_eez_dist_km"),
            }

        # Risk score
        alarm_score = cs.get("pollution_score", 0) if isinstance(cs, dict) else 0
        env_score = len(vents) * 0.3 + endangered_count * 0.2 + len(seamounts) * 0.1
        prox_score = 50 / min_dist if min_dist > 0 else 50
        plume_hits = len(plumes)
        total_risk = alarm_score + env_score + prox_score + plume_hits * 0.5

        dossier = {
            "claim": {
                "isa_id": cid,
                "contractor_name": cs.get("contractor_name", "Unknown") if isinstance(cs, dict) else "Unknown",
                "resource_type": cs.get("resource_type") if isinstance(cs, dict) else None,
                "area_km2": extra.get("area_km2"),
                "expiry_date": extra.get("expiry_date"),
                "is_high_risk": extra.get("is_high_risk"),
            },
            "spatial_relationship": {
                "min_distance_km": round(min_dist, 2),
                "profiles_within_50km": len(profiles_within_50),
            },
            "vents": vents,
            "seamounts": seamounts,
            "species": {
                "curated": curated_species,
                "total_species_count": len(species_list),
            },
            "unesco_eez": {
                "nearest_unesco": nearest_unesco,
                "nearest_eez": nearest_eez,
            },
            "attributed_alarms": attributed_alarms,
            "plume_evidence": plumes,
            "risk_score": {
                "total": round(total_risk, 2),
                "alarm_component": round(alarm_score, 2),
                "proximity_component": round(prox_score, 2),
                "environmental_component": round(env_score, 2),
                "plume_component": round(plume_hits * 0.5, 2),
            },
        }
        claim_dossiers.append(dossier)

    # Sort dossiers by risk score descending
    claim_dossiers.sort(key=lambda d: d["risk_score"]["total"], reverse=True)

    # ── 7. Build alarm_log ───────────────────────────────────────────────
    alarm_log = []
    for p in profiles:
        for alarm_type in p.get("alarms", []):
            alarm_id = p["_alarm_ids"].get(alarm_type)
            value_key = {
                "low_oxygen": "oxygen",
                "low_ph": "ph",
                "temp_anomaly": "surface_temp",
                "salinity_anomaly": "surface_salinity",
            }.get(alarm_type, alarm_type)
            depth = p.get("depth_m")
            if alarm_type == "low_oxygen":
                threshold = oxygen_threshold(depth)
            elif alarm_type == "low_ph":
                threshold = ph_threshold(depth)
            else:
                threshold = None

            cid = p.get("nearest_claim_id")
            env_ctx = env_context_by_claim.get(cid, {})
            severity = classify_severity(
                alarm_type,
                p.get("distance_to_claim_km") or 999,
                env_ctx.get("endangered_count", 0),
            )

            alarm_log.append({
                "alarm_id": alarm_id,
                "profile_id": p["profile_id"],
                "date": p["date"],
                "lon": p["lon"],
                "lat": p["lat"],
                "type": alarm_type,
                "value": p.get(value_key),
                "threshold": threshold,
                "severity": severity,
                "nearest_claim_id": cid,
                "nearest_claim_name": p.get("nearest_claim_name"),
                "distance_km": p.get("distance_to_claim_km"),
            })

    # ── 8. Generate findings ─────────────────────────────────────────────
    findings = []
    finding_num = 0

    # Alarm findings
    for p in profiles:
        for alarm_type in p.get("alarms", []):
            cid = p.get("nearest_claim_id")
            finding_num += 1
            claim_info = {
                "isa_id": cid,
                "contractor_name": p.get("nearest_claim_name", "Unknown"),
                "distance_km": p.get("distance_to_claim_km", 999),
            }
            env_ctx = env_context_by_claim.get(cid, {})
            findings.append(generate_alarm_finding(
                finding_num, alarm_type, p, stats, claim_info, env_ctx,
            ))

    # Plume findings
    for pa in plume_attributions:
        finding_num += 1
        p = profile_map.get(pa["profile_id"], {})
        claim_info = {
            "isa_id": pa.get("source_claim_id"),
            "contractor_name": pa.get("source_claim_name", "Unknown"),
        }
        findings.append(generate_plume_finding(
            finding_num, pa, p, claim_info, req.hours,
        ))

    # Sort by severity, then renumber
    findings.sort(key=lambda f: SEVERITY_RANK.get(f.get("severity", "Low"), 99))
    for i, f in enumerate(findings, 1):
        f["number"] = i

    # ── 8b. Build sensor timelines ───────────────────────────────────────
    sensor_timelines = {"oxygen": [], "ph": [], "temp": [], "salinity": []}
    for p in profiles:
        base = {"date": p["date"], "claim_distance_km": p.get("distance_to_claim_km")}

        if p.get("oxygen") is not None:
            o_thresh = oxygen_threshold(p.get("depth_m"))
            sensor_timelines["oxygen"].append({
                **base, "value": p["oxygen"], "threshold": o_thresh,
                "alarmed": "low_oxygen" in p.get("alarms", []),
            })

        if p.get("ph") is not None:
            ph_thresh = ph_threshold(p.get("depth_m"))
            sensor_timelines["ph"].append({
                **base, "value": p["ph"], "threshold": ph_thresh,
                "alarmed": "low_ph" in p.get("alarms", []),
            })

        if p.get("surface_temp") is not None:
            sensor_timelines["temp"].append({
                **base, "value": p["surface_temp"], "threshold": None,
                "alarmed": "temp_anomaly" in p.get("alarms", []),
            })

        if p.get("surface_salinity") is not None:
            sensor_timelines["salinity"].append({
                **base, "value": p["surface_salinity"], "threshold": None,
                "alarmed": "salinity_anomaly" in p.get("alarms", []),
            })

    # ── 9. Build trail summary ───────────────────────────────────────────
    trail_profiles = []
    for p in profiles:
        trail_profiles.append({
            "profile_id": p["profile_id"],
            "date": p["date"],
            "lon": p["lon"],
            "lat": p["lat"],
            "depth_m": p.get("depth_m"),
            "surface_temp": p.get("surface_temp"),
            "surface_salinity": p.get("surface_salinity"),
            "deep_temp": p.get("deep_temp"),
            "deep_salinity": p.get("deep_salinity"),
            "oxygen": p.get("oxygen"),
            "ph": p.get("ph"),
            "nearest_claim_id": p.get("nearest_claim_id"),
            "nearest_claim_name": p.get("nearest_claim_name"),
            "distance_to_claim_km": p.get("distance_to_claim_km"),
            "alarms": p.get("alarms", []),
            "alarm_severities": p.get("alarm_severities", {}),
        })

    trail_distance = total_trail_distance(profiles)

    # ── 10. Executive summary ────────────────────────────────────────────
    risk_rating = compute_risk_rating(findings)
    narrative = generate_executive_narrative(
        req.platform_id, profiles, findings, claim_dossiers, trail_distance,
    )
    evidence_summary = generate_evidence_summary(findings, risk_rating)

    # ── 11. Build structured response ─────────────────────────────────────
    response = {
        "_schema_version": REPORT_SCHEMA_VERSION,
        "report_id": str(uuid.uuid4()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform_id": req.platform_id,
        "parameters": {"hours": req.hours, "depth": req.depth},
        "executive_summary": {
            "risk_rating": risk_rating,
            "narrative": narrative,
            "key_stats": {
                "profile_count": len(profiles),
                "alarm_count": len(alarm_log),
                "claims_implicated": len(claim_dossiers),
                "endangered_species_count": sum(
                    sum(1 for s in dos["species"]["curated"] if s.get("endangered"))
                    for dos in claim_dossiers
                ),
                "total_distance_km": trail_distance,
                "date_range": {
                    "start": profiles[0]["date"],
                    "end": profiles[-1]["date"],
                },
            },
        },
        "methodology": {
            "alarm_thresholds": THRESHOLDS_DOC,
            "scoring_formula": "alarm_score + env_score + prox_score + plume_hits * 0.5",
            "plume_backtrack": {
                "hours": req.hours,
                "integration_depth_m": req.depth,
                "source": "Copernicus Marine CMEMS",
                "method": "RK4",
            },
            "data_sources": [
                "Argo Programme (autonomous profiling floats)",
                "Copernicus Marine Service (ocean currents)",
                "International Seabed Authority (concession boundaries)",
                "InterRidge (hydrothermal vents)",
                "OBIS (biodiversity hotspots)",
                "Yesson et al. (seamounts)",
            ],
            "notes": "Alarm thresholds are depth-adaptive. Temp/salinity anomalies are computed relative to all profiles in the current 90-day dataset window.",
        },
        "trail": {
            "profiles": trail_profiles,
            "total_distance_km": trail_distance,
            "date_range": {
                "start": profiles[0]["date"],
                "end": profiles[-1]["date"],
            },
        },
        "sensor_timelines": sensor_timelines,
        "alarm_log": alarm_log,
        "claim_dossiers": claim_dossiers,
        "claim_polygons": claim_geojson,
        "plume_attributions": plume_attributions,
        "findings": findings,
        "evidence_summary": evidence_summary,
        "appendices": {
            "full_sensor_data": trail_profiles,
            "full_species_list": [
                sp
                for dos in claim_dossiers
                for sp in species_by_claim.get(dos["claim"]["isa_id"], [])
            ] if claim_ids else [],
            "plume_coordinates": [
                {"profile_id": pa["profile_id"], "origin": pa["backtrack_origin"],
                 "speed_cms": pa.get("speed_cms")}
                for pa in plume_attributions
            ],
            "claim_polygons": claim_geojson,
        },
    }

    # ── Cache the report ──────────────────────────────────────────────────
    try:
        async with db.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO report_cache (platform_id, report_json, risk_rating, headline, finding_count, claim_count, generated_at)
                VALUES ($1, $2::jsonb, $3, $4, $5, $6, NOW())
                ON CONFLICT (platform_id) DO UPDATE SET
                    report_json = EXCLUDED.report_json,
                    risk_rating = EXCLUDED.risk_rating,
                    headline = EXCLUDED.headline,
                    finding_count = EXCLUDED.finding_count,
                    claim_count = EXCLUDED.claim_count,
                    generated_at = NOW()
            """,
                req.platform_id,
                json.dumps(response, default=str),
                response["executive_summary"]["risk_rating"],
                response["executive_summary"]["narrative"][:200],
                len(findings),
                len(claim_dossiers),
            )
        print(f"[CACHE] report cached for {req.platform_id}")
        log.info("report cached for %s", req.platform_id)
    except Exception as exc:
        print(f"[CACHE] report cache write FAILED for {req.platform_id}: {exc}")
        log.warning("report cache write failed for %s: %s", req.platform_id, exc)

    return response


@router.get("/seo/{platform_id}", dependencies=[Depends(get_api_key)])
async def report_seo_data(platform_id: str):
    """Return cached report summary for SSR rendering by bot-detection route."""
    if db.pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT report_json, risk_rating, headline, finding_count, claim_count, generated_at FROM report_cache WHERE platform_id = $1",
            platform_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="No cached report for this float")

    report = json.loads(row["report_json"])
    es = report.get("executive_summary", {})
    claims = report.get("claim_dossiers", [])
    findings = report.get("findings", [])

    # Build a rich description for meta tags
    description = (
        f"Environmental impact evidence report for Argo float {platform_id}. "
        f"Risk rating: {row['risk_rating']}. "
        f"{row['finding_count']} findings across {row['claim_count']} mining concession(s)."
    )

    # Curate top findings for the SSR page body
    top_findings = findings[:5]
    claim_summaries = []
    for cd in claims[:5]:
        c = cd.get("claim", {})
        rs = cd.get("risk_score", {})
        claim_summaries.append({
            "isa_id": c.get("isa_id"),
            "contractor_name": c.get("contractor_name"),
            "risk_total": rs.get("total", 0),
            "vent_count": len(cd.get("vents", [])),
            "species_count": cd.get("species", {}).get("total_species_count", 0),
        })

    return {
        "meta": {
            "title": f"Impact Report — Float {platform_id} | Abyssal Claims",
            "description": description[:160],
            "canonical_url": f"https://something-rare.com/report/{platform_id}",
            "json_ld": {
                "@context": "https://schema.org",
                "@type": "Report",
                "name": f"Environmental Impact Evidence Report — Argo Float {platform_id}",
                "description": description,
                "url": f"https://something-rare.com/report/{platform_id}",
                "datePublished": str(row["generated_at"].date()),
                "publisher": {
                    "@type": "Organization",
                    "name": "Abyssal Claims",
                    "url": "https://something-rare.com",
                },
                "about": {
                    "@type": "EnvironmentalReport",
                    "name": f"Deep-sea mining environmental impact analysis for float {platform_id}",
                },
            },
        },
        "platform_id": platform_id,
        "risk_rating": row["risk_rating"],
        "narrative": es.get("narrative", ""),
        "key_stats": es.get("key_stats", {}),
        "finding_count": row["finding_count"],
        "claim_count": row["claim_count"],
        "top_findings": top_findings,
        "claim_summaries": claim_summaries,
        "generated_at": str(row["generated_at"]),
    }


@router.get("/lookup/claims-by-contractor", dependencies=[Depends(get_api_key)])
async def lookup_claims_by_contractor(q: str):
    """Return ISA IDs matching a contractor name (case-insensitive partial match)."""
    if db.pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT isa_id, contractor_name, resource_type "
            "FROM mining_contracts "
            "WHERE lower(contractor_name) LIKE '%' || lower($1) || '%' "
            "ORDER BY contractor_name, isa_id LIMIT 50",
            q,
        )
    return [{"isa_id": r["isa_id"], "contractor_name": r["contractor_name"],
             "resource_type": r["resource_type"]} for r in rows]


@router.post("/refresh-species-cache", dependencies=[Depends(require_admin_token)])
async def api_refresh_species_cache():
    """Manually trigger a species cache rebuild. Takes ~5-10 min on first run."""
    if db.pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    await ensure_species_cache_table()
    asyncio.create_task(refresh_species_cache())
    return {"status": "started", "message": "Species cache rebuild started in background"}


@router.get("/seo/claim/{isa_id}", dependencies=[Depends(get_api_key)])
async def claim_report_seo_data(isa_id: str):
    """Return cached claim report summary for SSR rendering by bot-detection route."""
    if db.pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT report_json, risk_rating, headline, finding_count, claim_count, generated_at FROM report_cache WHERE platform_id = $1",
            f"claim:{isa_id}",
        )
    if not row:
        raise HTTPException(status_code=404, detail="No cached claim report")

    report = json.loads(row["report_json"])
    claim = report.get("claim", {})
    es = report.get("executive_summary", {})
    env = report.get("environmental_context", {})
    findings = report.get("findings", [])

    description = (
        f"Environmental impact report for mining concession {isa_id} "
        f"({claim.get('contractor_name', 'Unknown')}). "
        f"Risk rating: {row['risk_rating']}. "
        f"{row['finding_count']} findings."
    )

    return {
        "meta": {
            "title": f"Claim Report — {claim.get('contractor_name', isa_id)} | Abyssal Claims",
            "description": description,
            "canonical_url": f"https://something-rare.com/claim-report/{isa_id}",
            "json_ld": {
                "@context": "https://schema.org",
                "@type": "Report",
                "name": f"Environmental Impact Report — {claim.get('contractor_name', isa_id)}",
                "description": description,
                "datePublished": row["generated_at"].isoformat() if row["generated_at"] else None,
                "publisher": {"@type": "Organization", "name": "Abyssal Claims"},
            },
        },
        "isa_id": isa_id,
        "contractor_name": claim.get("contractor_name"),
        "resource_type": claim.get("resource_type"),
        "risk_rating": row["risk_rating"],
        "narrative": es.get("narrative", ""),
        "key_stats": es.get("key_stats", {}),
        "finding_count": row["finding_count"],
        "top_findings": findings[:5],
        "vent_count": len(env.get("vents", [])),
        "species_count": env.get("species", {}).get("total_count", 0),
        "generated_at": row["generated_at"].isoformat() if row["generated_at"] else None,
    }


# ── Chess Site Reports ─────────────────────────────────────────────────────────

class ChessSiteReportRequest(BaseModel):
    locality: str


async def _generate_chess_site_report(locality: str) -> dict:
    """Generate a site report for a ChEssBase locality."""
    if db.pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Site data grouped by locality
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                habitat_type,
                AVG(lat) AS lat, AVG(lon) AS lon,
                AVG(depth_m) AS depth_m,
                COUNT(DISTINCT species)::INTEGER AS species_count,
                json_agg(DISTINCT phylum) FILTER (WHERE phylum IS NOT NULL AND phylum != '') AS phyla,
                json_agg(json_build_object(
                    'species', species, 'phylum', phylum,
                    'depth_m', depth_m, 'institution', institution_code
                )) AS species_list
            FROM chess_occurrences
            WHERE locality = $1 AND habitat_type != 'vent'
            GROUP BY habitat_type
        """, locality)

    if not rows:
        raise HTTPException(status_code=404, detail=f"Chess site '{locality}' not found")

    r = rows[0]
    phyla = r["phyla"] if not isinstance(r["phyla"], str) else json.loads(r["phyla"])
    phyla = phyla or []
    species_list = r["species_list"] if not isinstance(r["species_list"], str) else json.loads(r["species_list"])
    species_list = species_list or []

    lat = float(r["lat"])
    lon = float(r["lon"])

    # Nearby mining claims within 50km
    async with db.pool.acquire() as conn:
        claim_rows = await conn.fetch("""
            SELECT mc.isa_id, mc.contractor_name, mc.resource_type,
                   ST_Distance(mc.geom::geography, ST_SetSRID(ST_MakePoint($2, $1), 4326)::geography) / 1000.0 AS distance_km
            FROM mining_contracts mc
            WHERE ST_DWithin(mc.geom::geography, ST_SetSRID(ST_MakePoint($2, $1), 4326)::geography, 50000)
            ORDER BY distance_km
            LIMIT 20
        """, lat, lon)

    # Nearby hydrothermal vents within 50km
    async with db.pool.acquire() as conn:
        vent_rows = await conn.fetch("""
            SELECT hv.name, hv.status, hv.depth_m,
                   ST_Distance(hv.geom, ST_SetSRID(ST_MakePoint($2, $1), 4326)::geography) / 1000.0 AS distance_km
            FROM hydrothermal_vents hv
            WHERE ST_DWithin(hv.geom, ST_SetSRID(ST_MakePoint($2, $1), 4326)::geography, 50000)
            ORDER BY distance_km
            LIMIT 10
        """, lat, lon)

    report = {
        "report_type": "chess",
        "locality": locality,
        "habitat_type": r["habitat_type"],
        "lat": lat,
        "lon": lon,
        "depth_m": float(r["depth_m"]) if r["depth_m"] is not None else None,
        "species_count": r["species_count"],
        "phyla": phyla,
        "species_list": species_list,
        "nearby_claims": [
            {
                "isa_id": c["isa_id"],
                "contractor_name": c["contractor_name"],
                "resource_type": c["resource_type"],
                "distance_km": round(float(c["distance_km"]), 2),
            }
            for c in claim_rows
        ],
        "nearby_vents": [
            {
                "name": v["name"],
                "status": v["status"],
                "depth_m": float(v["depth_m"]) if v["depth_m"] is not None else None,
                "distance_km": round(float(v["distance_km"]), 2),
            }
            for v in vent_rows
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Cache using same report_cache table with prefix
    try:
        async with db.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO report_cache (platform_id, report_json, risk_rating, headline, finding_count, claim_count, generated_at)
                VALUES ($1, $2::jsonb, $3, $4, $5, $6, NOW())
                ON CONFLICT (platform_id) DO UPDATE SET
                    report_json = EXCLUDED.report_json,
                    headline = EXCLUDED.headline,
                    generated_at = NOW()
            """,
                f"chess:{locality}",
                json.dumps(report, default=str),
                "Low",
                f"{locality} — {r['habitat_type']}",
                0,
                len(report["nearby_claims"]),
            )
    except Exception as exc:
        log.warning("chess report cache write failed for %s: %s", locality, exc)

    return report


@router.post("/chess-site", dependencies=[Depends(get_api_key)])
async def generate_chess_site_report(req: ChessSiteReportRequest):
    """Start async generation of a chess site report."""
    if db.pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    job_id = f"chess:{req.locality}"
    _jobs[job_id] = {"status": "generating", "error": None}

    async def _run():
        async with _report_semaphore:
            try:
                await _generate_chess_site_report(req.locality)
                _jobs[job_id]["status"] = "ready"
            except Exception as exc:
                log.exception("chess site report failed: %s", exc)
                _jobs[job_id] = {"status": "failed", "error": str(exc)}

    asyncio.create_task(_run())
    return {"status": "generating", "locality": req.locality}


@router.get("/chess-site/{locality}/status", dependencies=[Depends(get_api_key)])
async def chess_site_report_status(locality: str):
    """Poll job status for a chess site report."""
    job_id = f"chess:{locality}"
    job = _jobs.get(job_id)
    if job:
        return job
    # Check cache
    if db.pool:
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT platform_id FROM report_cache WHERE platform_id = $1", job_id
            )
        if row:
            return {"status": "ready"}
    return {"status": "not_found"}


@router.get("/chess-site/{locality}", dependencies=[Depends(get_api_key)])
async def get_chess_site_report(locality: str):
    """Retrieve a completed chess site report."""
    if db.pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    job_id = f"chess:{locality}"
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT report_json FROM report_cache WHERE platform_id = $1", job_id
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"No report for chess site '{locality}'")
    return json.loads(row["report_json"])
