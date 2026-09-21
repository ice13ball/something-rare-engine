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

router = APIRouter(prefix="/v1/reports", tags=["reports"])


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


# ⛔ `_check_cache`, `_do_generate` and `_do_generate_claim` lived here until
# 2026-09-21. They drove the v1 risk-scored reports, which are gone: the
# platform no longer computes a severity, a risk rating or a weighted score and
# publishes it as a finding. The neutral stack in `routers/reports_v2.py` owns
# /report/:id and /claim-report/:id now, including the data the server-rendered
# pages hand to Google. Chess-site reports below keep their own job tracking.

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
                AVG(lat) AS lat, AVG(lon) AS lon,
                AVG(depth_m) AS depth_m,
                COUNT(DISTINCT species)::INTEGER AS species_count,
                json_agg(DISTINCT phylum) FILTER (WHERE phylum IS NOT NULL AND phylum != '') AS phyla,
                json_agg(json_build_object(
                    'species', species, 'phylum', phylum,
                    'depth_m', depth_m, 'institution', institution_code
                )) AS species_list
            FROM chess_occurrences
            WHERE locality = $1
            -- ⚠️ GROUP BY is load-bearing, not decoration: a bare aggregate would
            -- return one all-NULL row for an unknown locality and the 404 below
            -- would never fire. Grouping by the key keeps "no rows" meaning "no site".
            GROUP BY locality
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
                -- ⛔ `risk_rating` deliberately omitted: it was hardcoded "Low" on every
                -- chess site, a verdict nobody computed and nothing now reads.
                -- The column keeps its NOT NULL DEFAULT, so the row still writes.
                INSERT INTO report_cache (platform_id, report_json, headline, finding_count, claim_count, generated_at)
                VALUES ($1, $2::jsonb, $3, $4, $5, NOW())
                ON CONFLICT (platform_id) DO UPDATE SET
                    report_json = EXCLUDED.report_json,
                    headline = EXCLUDED.headline,
                    generated_at = NOW()
            """,
                f"chess:{locality}",
                json.dumps(report, default=str),
                locality,
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
