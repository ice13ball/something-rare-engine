# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Neutral impact-report endpoints (v2).

Mounted at /v2/reports. Owns its SQL — does not import from routers/reports.py
so v1 stays a known-good frozen restore point.

GET  /v2/reports/impact/{platform_id}          — return cached neutral report
POST /v2/reports/impact                         — kick off background regeneration
GET  /v2/reports/impact/{platform_id}/status   — poll generation status

"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import db
from auth import get_api_key
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from services.measurement_report import SCHEMA_VERSION, below_baseline, build_neutral_report
from services.concession_report import SCHEMA_VERSION as SCHEMA_VERSION_CONCESSION, build_neutral_concession_report

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/reports", tags=["reports-v2"])

CACHE_MAX_AGE         = timedelta(days=7)
QUERY_TIMEOUT_MS      = 120_000
_report_semaphore     = asyncio.Semaphore(2)
# Reclaim a 'generating' slot whose worker hasn't reported back in this long.
# Matches the frontend polling timeout (5 min) — a generation that legitimately
# takes longer than this is broken; the next POST should be allowed to retry.
STALE_CLAIM_AFTER     = timedelta(minutes=5)
_WORKER_ID            = f"{socket.gethostname()}:{os.getpid()}"


class ImpactReportRequest(BaseModel):
    platform_id: str
    hours: int  = Field(default=168, ge=24, le=720)
    depth: int  = Field(default=1000, ge=100, le=3000)


@asynccontextmanager
async def _db_conn(timeout_ms: int = QUERY_TIMEOUT_MS):
    async with db.pool.acquire() as conn:
        await conn.execute(f"SET statement_timeout = {timeout_ms}")
        await conn.execute("SET max_parallel_workers_per_gather = 0")
        try:
            yield conn
        finally:
            await conn.execute("SET statement_timeout = 0")
            await conn.execute("SET max_parallel_workers_per_gather = 2")


# ── Cache helpers ────────────────────────────────────────────────────────

async def _check_cache(platform_id: str) -> dict | None:
    """Return cached neutral report if fresh + schema-compatible, else None."""
    async with db.pool.acquire() as conn:
        cached = await conn.fetchrow(
            "SELECT report_json, generated_at FROM report_cache_v2 WHERE platform_id = $1",
            platform_id,
        )
    if cached and (datetime.now(timezone.utc) - cached["generated_at"]) < CACHE_MAX_AGE:
        data = json.loads(cached["report_json"])
        if data.get("schema_version") == SCHEMA_VERSION:
            return data
    return None


# ── Job-claim helpers ────────────────────────────────────────────────────

async def _claim_generation_slot(platform_id: str) -> bool:
    """Atomically claim the generation slot for this platform.

    Uses INSERT ... ON CONFLICT DO UPDATE WHERE ... RETURNING. The WHERE
    clause only allows the upsert when the existing slot is either:
      - in a terminal state (ready / failed), or
      - stale ('generating' for longer than STALE_CLAIM_AFTER, meaning the
        previous worker probably died mid-generation).

    Returns True iff this worker won the claim. The caller MUST then
    schedule _do_generate; on completion _mark_job_complete records the
    terminal state.
    """
    stale_seconds = int(STALE_CLAIM_AFTER.total_seconds())
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            INSERT INTO report_jobs_v2 (platform_id, status, worker_id)
            VALUES ($1, 'generating', $2)
            ON CONFLICT (platform_id) DO UPDATE SET
                status      = 'generating',
                started_at  = NOW(),
                finished_at = NULL,
                worker_id   = EXCLUDED.worker_id,
                error       = NULL
            WHERE report_jobs_v2.status <> 'generating'
               OR report_jobs_v2.started_at < NOW() - INTERVAL '{stale_seconds} seconds'
            RETURNING platform_id
            """,
            platform_id, _WORKER_ID,
        )
    return row is not None


async def _mark_job_complete(platform_id: str, status: str, error: str | None) -> None:
    """Update report_jobs_v2 with the terminal state after generation finishes.
    Caller passes status='ready' on success or 'failed' on exception.
    """
    async with db.pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE report_jobs_v2
            SET status = $2, finished_at = NOW(), error = $3
            WHERE platform_id = $1
            """,
            platform_id, status, error,
        )


async def _read_job_state(platform_id: str) -> dict | None:
    """Return the current job row for a platform, or None if no claim exists."""
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, error FROM report_jobs_v2 WHERE platform_id = $1",
            platform_id,
        )
    if not row:
        return None
    return {"status": row["status"], "error": row["error"]}


# ── Data fetchers (copied from v1; v1 stays frozen) ──────────────────────

async def _fetch_profiles(platform_id: str) -> list[dict]:
    async with _db_conn() as conn:
        rows = await conn.fetch("""
            SELECT profile_id, platform_id,
                   to_char(profile_date, 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS date,
                   ST_X(geom::geometry) AS lon, ST_Y(geom::geometry) AS lat,
                   max_depth_m AS depth_m,
                   oxygen_umol_kg AS oxygen, ph
            FROM argo_profiles
            WHERE platform_id = $1
            ORDER BY profile_date ASC
        """, platform_id)
    return [dict(r) for r in rows]


async def _fetch_nearest_claims(profiles: list[dict]) -> None:
    """Attach nearest_claim_id, distance_to_claim_km, and claim metadata
    to each profile dict in place."""
    if not profiles:
        return
    lons = [p["lon"] for p in profiles]
    lats = [p["lat"] for p in profiles]
    async with _db_conn() as conn:
        rows = await conn.fetch("""
            WITH pts AS (
                SELECT idx, lon, lat
                FROM UNNEST($1::int[], $2::float8[], $3::float8[]) AS t(idx, lon, lat)
            )
            SELECT DISTINCT ON (pts.idx)
                   pts.idx,
                   mc.isa_id AS concession_id,
                   mc.contractor_name,
                   mc.area_km2,
                   ST_Distance(mc.geom::geography,
                               ST_SetSRID(ST_MakePoint(pts.lon, pts.lat), 4326)::geography)
                     / 1000.0 AS dist_km
            FROM pts
            CROSS JOIN LATERAL (
                SELECT isa_id, contractor_name, area_km2, geom
                FROM mining_contracts
                ORDER BY geom <-> ST_SetSRID(ST_MakePoint(pts.lon, pts.lat), 4326)
                LIMIT 1
            ) mc
            ORDER BY pts.idx
        """, list(range(len(profiles))), lons, lats)
    by_idx = {r["idx"]: r for r in rows}
    for i, p in enumerate(profiles):
        r = by_idx.get(i)
        if r:
            p["nearest_claim_id"]      = r["concession_id"]
            p["nearest_claim_name"]    = r["contractor_name"]
            p["nearest_claim_area"]    = r["area_km2"]
            p["distance_to_claim_km"]  = round(float(r["dist_km"]), 2)
        else:
            p["nearest_claim_id"]      = None
            p["nearest_claim_name"]    = None
            p["nearest_claim_area"]    = None
            p["distance_to_claim_km"]  = None


async def _fetch_plumes(profile_ids: list[str]) -> list[dict]:
    if not profile_ids:
        return []
    async with _db_conn() as conn:
        rows = await conn.fetch("""
            SELECT profile_id,
                   contractor_name AS intersects_concession
            FROM plume_paths
            WHERE profile_id = ANY($1::text[])
        """, profile_ids)
    return [dict(r) for r in rows]


def _build_dossier_rows(profiles: list[dict], plume_rows: list[dict]) -> list[dict]:
    """Aggregate per-concession counts from in-memory profile/plume data."""
    by_id: dict[str, dict] = {}
    plume_by_pid = {p["profile_id"]: p for p in plume_rows}

    for p in profiles:
        cid = p.get("nearest_claim_id")
        if not cid:
            continue
        d = by_id.setdefault(cid, {
            "concession_id":                cid,
            "contractor_name":              p.get("nearest_claim_name"),
            "area_km2":                     p.get("nearest_claim_area"),
            "min_distance_km":              float("inf"),
            "attributed_measurement_count": 0,
            "attributed_plume_count":       0,
            "profiles_within_50km":         0,
        })
        dist = p.get("distance_to_claim_km")
        if dist is not None and dist < d["min_distance_km"]:
            d["min_distance_km"] = dist
        if dist is not None and dist <= 50.0:
            d["profiles_within_50km"] += 1
        for prop in ("oxygen", "ph"):
            v = p.get(prop)
            if v is not None:
                if below_baseline(prop, v, p.get("depth_m")):
                    d["attributed_measurement_count"] += 1
        if p["profile_id"] in plume_by_pid:
            d["attributed_plume_count"] += 1

    # Drop any with infinite distance (defensive — shouldn't happen if every
    # nearest_claim_id was set with a real distance)
    return [d for d in by_id.values() if d["min_distance_km"] != float("inf")]


# ── Core generation ──────────────────────────────────────────────────────

async def _generate_neutral_report_core(platform_id: str) -> dict:
    profiles = await _fetch_profiles(platform_id)
    if not profiles:
        raise HTTPException(404, detail=f"No profiles found for platform {platform_id}")

    await _fetch_nearest_claims(profiles)
    plume_rows   = await _fetch_plumes([p["profile_id"] for p in profiles])
    dossier_rows = _build_dossier_rows(profiles, plume_rows)

    report = build_neutral_report(
        platform_id  = platform_id,
        profiles     = profiles,
        plume_rows   = plume_rows,
        dossier_rows = dossier_rows,
    )

    # Cache write
    try:
        async with db.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO report_cache_v2
                    (platform_id, report_json, headline, measurement_count, concession_count, generated_at)
                VALUES ($1, $2::jsonb, $3, $4, $5, NOW())
                ON CONFLICT (platform_id) DO UPDATE SET
                    report_json       = EXCLUDED.report_json,
                    headline          = EXCLUDED.headline,
                    measurement_count = EXCLUDED.measurement_count,
                    concession_count  = EXCLUDED.concession_count,
                    generated_at      = NOW()
            """,
                platform_id,
                json.dumps(report, default=str),
                report["headline"],
                len(report["measurements"]),
                len(report["claim_dossiers"]),
            )
        log.info("v2 report cached for %s", platform_id)
    except Exception as exc:
        log.warning("v2 report cache write failed for %s: %s", platform_id, exc)

    return report


async def _do_generate(platform_id: str) -> None:
    async with _report_semaphore:
        try:
            await _generate_neutral_report_core(platform_id)
            await _mark_job_complete(platform_id, status="ready", error=None)
            log.info("v2 report generation complete for %s", platform_id)
        except Exception as exc:
            await _mark_job_complete(platform_id, status="failed", error=str(exc))
            log.warning("v2 report generation FAILED for %s: %s", platform_id, exc)


# ── Endpoints ────────────────────────────────────────────────────────────

@router.post("/impact", dependencies=[Depends(get_api_key)])
async def generate(req: ImpactReportRequest):
    if db.pool is None:
        raise HTTPException(503, detail="Database unavailable")

    cached = await _check_cache(req.platform_id)
    if cached:
        return {"status": "ready", "cached": True}

    # Atomic claim across workers/processes — DB enforces uniqueness, not
    # in-memory state. If another worker (or this one) already owns a fresh
    # 'generating' slot, the claim fails and we return without scheduling.
    claimed = await _claim_generation_slot(req.platform_id)
    if not claimed:
        # Race against a generation that just finished: re-check cache once.
        cached = await _check_cache(req.platform_id)
        if cached:
            return {"status": "ready", "cached": True}
        return {"status": "generating", "cached": False}

    asyncio.create_task(_do_generate(req.platform_id))
    return {"status": "generating", "cached": False}


@router.get("/impact/{platform_id}/status", dependencies=[Depends(get_api_key)])
async def status(platform_id: str):
    if db.pool is None:
        raise HTTPException(503, detail="Database unavailable")
    cached = await _check_cache(platform_id)
    if cached:
        return {"status": "ready", "cached": True}
    job = await _read_job_state(platform_id)
    if job is None:
        return {"status": "unknown", "error": None, "cached": False}
    return {"status": job["status"], "error": job["error"], "cached": False}


@router.get("/impact/{platform_id}", dependencies=[Depends(get_api_key)])
async def cached(platform_id: str):
    if db.pool is None:
        raise HTTPException(503, detail="Database unavailable")
    data = await _check_cache(platform_id)
    if not data:
        raise HTTPException(404, detail="No cached neutral report for this float; POST /v2/reports/impact first")
    return data


# ── Concession reports ──────────────────────────────────────────────────
#
# Parallel stack to the Argo platform reports above. Same patterns
# (cache, atomic claim, 5-min stale reclaim, semaphore) but keyed by
# isa_id and rendered from concession-shaped data.


class ConcessionReportRequest(BaseModel):
    isa_id: str


async def _check_concession_cache(isa_id: str) -> dict | None:
    async with db.pool.acquire() as conn:
        cached = await conn.fetchrow(
            "SELECT report_json, generated_at FROM report_cache_v2_concession WHERE isa_id = $1",
            isa_id,
        )
    if cached and (datetime.now(timezone.utc) - cached["generated_at"]) < CACHE_MAX_AGE:
        data = json.loads(cached["report_json"])
        if data.get("schema_version") == SCHEMA_VERSION_CONCESSION:
            return data
    return None


async def _claim_concession_slot(isa_id: str) -> bool:
    stale_seconds = int(STALE_CLAIM_AFTER.total_seconds())
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            INSERT INTO report_jobs_v2_concession (isa_id, status, worker_id)
            VALUES ($1, 'generating', $2)
            ON CONFLICT (isa_id) DO UPDATE SET
                status      = 'generating',
                started_at  = NOW(),
                finished_at = NULL,
                worker_id   = EXCLUDED.worker_id,
                error       = NULL
            WHERE report_jobs_v2_concession.status <> 'generating'
               OR report_jobs_v2_concession.started_at < NOW() - INTERVAL '{stale_seconds} seconds'
            RETURNING isa_id
            """,
            isa_id, _WORKER_ID,
        )
    return row is not None


async def _mark_concession_complete(isa_id: str, status: str, error: str | None) -> None:
    async with db.pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE report_jobs_v2_concession
            SET status = $2, finished_at = NOW(), error = $3
            WHERE isa_id = $1
            """,
            isa_id, status, error,
        )


async def _read_concession_job_state(isa_id: str) -> dict | None:
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, error FROM report_jobs_v2_concession WHERE isa_id = $1",
            isa_id,
        )
    if not row:
        return None
    return {"status": row["status"], "error": row["error"]}


# ── Concession data fetchers (independent copies; v1 stays frozen) ──────

async def _fetch_concession_row(isa_id: str) -> dict | None:
    async with _db_conn() as conn:
        row = await conn.fetchrow("""
            SELECT isa_id, contractor_name, resource_type, area_km2,
                   jurisdiction_text AS sponsoring_state,
                   act_date          AS contract_date,
                   expiry_date,
                   ST_X(ST_Centroid(geom::geometry)) AS centroid_lon,
                   ST_Y(ST_Centroid(geom::geometry)) AS centroid_lat
            FROM mining_contracts
            WHERE isa_id = $1
        """, isa_id)
    return dict(row) if row else None


async def _fetch_concession_seamounts(isa_id: str) -> list[dict]:
    async with _db_conn() as conn:
        rows = await conn.fetch("""
            SELECT s.peak_id, NULL::text AS name, s.summit_depth_m, s.height_m, s.area_km2,
                   ST_Distance(s.geom::geography, mc.geom::geography) / 1000.0 AS distance_km
            FROM seamounts s, mining_contracts mc
            WHERE mc.isa_id = $1
              AND ST_DWithin(s.geom::geography, mc.geom::geography, 10000)
            ORDER BY distance_km
        """, isa_id)
    return [dict(r) for r in rows]


async def _fetch_concession_vents(isa_id: str) -> list[dict]:
    async with _db_conn() as conn:
        rows = await conn.fetch("""
            SELECT hv.id AS vent_id, hv.name, hv.depth_m,
                   ST_Distance(hv.geom, mc.geom::geography) / 1000.0 AS distance_km
            FROM hydrothermal_vents hv, mining_contracts mc
            WHERE mc.isa_id = $1
              AND ST_DWithin(hv.geom, mc.geom::geography, 50000)
            ORDER BY distance_km
        """, isa_id)
    return [dict(r) for r in rows]


async def _fetch_concession_species(isa_id: str) -> list[dict]:
    # claim_species_cache is built at an exact 10 km — an index-friendly ~0.12°
    # pre-filter refined by a geography ST_DWithin(..., 10000). 10 km is the
    # project-wide "species near a claim" radius. See `refresh_species_cache` in
    # services/species_cache.py.
    async with _db_conn() as conn:
        rows = await conn.fetch("""
            SELECT scientific_name, iucn_category, records AS record_count
            FROM claim_species_cache
            WHERE isa_id = $1
        """, isa_id)
    return [dict(r) for r in rows]


async def _fetch_concession_species_inside_count(isa_id: str) -> int | None:
    # Distinct species whose occurrence falls strictly INSIDE the claim
    # polygon (vs the 10 km radius the cache uses). Usually a fast GIST index
    # scan, but for very large + densely-sampled claims it can scan millions
    # of points. Hard-bound it with a SET LOCAL statement_timeout inside an
    # explicit transaction (guaranteed to apply, unlike a pooled session SET)
    # and return None on timeout so generation never hangs — and, critically,
    # so this read can't hold an AccessShareLock on mining_contracts long
    # enough to block schema.ensure_schema's ALTER on the next service restart.
    try:
        async with db.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SET LOCAL statement_timeout = 20000")
                await conn.execute("SET LOCAL max_parallel_workers_per_gather = 0")
                row = await conn.fetchrow("""
                    SELECT COUNT(DISTINCT bh.scientific_name) AS n
                    FROM biodiversity_hotspots bh, mining_contracts mc
                    WHERE mc.isa_id = $1
                      AND ST_Intersects(bh.geom, mc.geom)
                """, isa_id)
        return int(row["n"]) if row else 0
    except Exception as exc:
        log.warning("inside-count skipped for %s (timeout/err): %s", isa_id, exc)
        return None


async def _fetch_concession_plumes(isa_id: str) -> list[dict]:
    # Attribute a plume to the concession when its back-tracked PATH crosses
    # the claim polygon — i.e. the water the float sampled passed over (or
    # originated in) this claim. The earlier origin-point + contractor-name
    # match missed every plume that merely transits the claim (origin
    # elsewhere), so claims with visible plume paths reported zero.
    # path_coords is a [[lon,lat],…] array; build a LineString and intersect.
    async with _db_conn() as conn:
        rows = await conn.fetch("""
            SELECT pp.platform_id,
                   pp.profile_id,
                   to_char(pp.profile_date, 'YYYY-MM-DD') AS profile_date,
                   pp.origin_lat, pp.origin_lon,
                   pp.speed_cms, pp.source_dataset,
                   ap.oxygen_umol_kg, ap.ph,
                   ap.surface_temp_c, ap.surface_salinity, ap.max_depth_m
            FROM plume_paths pp
            JOIN mining_contracts mc ON mc.isa_id = $1
            LEFT JOIN argo_profiles ap ON ap.profile_id = pp.profile_id
            WHERE jsonb_array_length(pp.path_coords) >= 2
              AND ST_Intersects(
                    ST_SetSRID(
                      ST_GeomFromGeoJSON(
                        '{"type":"LineString","coordinates":' || pp.path_coords::text || '}'
                      ),
                      4326
                    ),
                    mc.geom
                  )
            ORDER BY pp.profile_date DESC, pp.platform_id
        """, isa_id)
    return [dict(r) for r in rows]


async def _fetch_concession_float_count(isa_id: str) -> int:
    async with _db_conn() as conn:
        row = await conn.fetchrow("""
            SELECT COUNT(DISTINCT ap.platform_id) AS n
            FROM argo_profiles ap, mining_contracts mc
            WHERE mc.isa_id = $1
              AND ST_DWithin(ap.geom, mc.geom::geography, 200000)
              AND ap.profile_date >= NOW() - INTERVAL '90 days'
        """, isa_id)
    return int(row["n"]) if row else 0


async def _generate_neutral_concession_core(isa_id: str) -> dict:
    concession = await _fetch_concession_row(isa_id)
    if not concession:
        raise HTTPException(404, detail=f"Concession {isa_id} not found")

    seamounts     = await _fetch_concession_seamounts(isa_id)
    vents         = await _fetch_concession_vents(isa_id)
    species       = await _fetch_concession_species(isa_id)
    species_inside = await _fetch_concession_species_inside_count(isa_id)
    plumes        = await _fetch_concession_plumes(isa_id)
    n_floats      = await _fetch_concession_float_count(isa_id)

    report = build_neutral_concession_report(
        isa_id                 = isa_id,
        concession_row         = concession,
        seamount_rows          = seamounts,
        species_rows           = species,
        species_inside_count   = species_inside,
        vent_rows              = vents,
        plume_rows             = plumes,
        monitoring_float_count = n_floats,
    )

    try:
        async with db.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO report_cache_v2_concession
                    (isa_id, report_json, headline, seamount_count, species_count, vent_count, generated_at)
                VALUES ($1, $2::jsonb, $3, $4, $5, $6, NOW())
                ON CONFLICT (isa_id) DO UPDATE SET
                    report_json    = EXCLUDED.report_json,
                    headline       = EXCLUDED.headline,
                    seamount_count = EXCLUDED.seamount_count,
                    species_count  = EXCLUDED.species_count,
                    vent_count     = EXCLUDED.vent_count,
                    generated_at   = NOW()
            """,
                isa_id,
                json.dumps(report, default=str),
                f"{concession.get('contractor_name') or isa_id} concession report",
                len(seamounts), len(species), len(vents),
            )
        log.info("v2 concession report cached for %s", isa_id)
    except Exception as exc:
        log.warning("v2 concession cache write failed for %s: %s", isa_id, exc)

    return report


async def _do_generate_concession(isa_id: str) -> None:
    async with _report_semaphore:
        try:
            await _generate_neutral_concession_core(isa_id)
            await _mark_concession_complete(isa_id, status="ready", error=None)
            log.info("v2 concession report generation complete for %s", isa_id)
        except Exception as exc:
            await _mark_concession_complete(isa_id, status="failed", error=str(exc))
            log.warning("v2 concession report generation FAILED for %s: %s", isa_id, exc)


@router.post("/concession", dependencies=[Depends(get_api_key)])
async def generate_concession(req: ConcessionReportRequest):
    if db.pool is None:
        raise HTTPException(503, detail="Database unavailable")

    cached = await _check_concession_cache(req.isa_id)
    if cached:
        return {"status": "ready", "cached": True}

    claimed = await _claim_concession_slot(req.isa_id)
    if not claimed:
        cached = await _check_concession_cache(req.isa_id)
        if cached:
            return {"status": "ready", "cached": True}
        return {"status": "generating", "cached": False}

    asyncio.create_task(_do_generate_concession(req.isa_id))
    return {"status": "generating", "cached": False}


@router.get("/concession/{isa_id}/status", dependencies=[Depends(get_api_key)])
async def concession_status(isa_id: str):
    if db.pool is None:
        raise HTTPException(503, detail="Database unavailable")
    cached = await _check_concession_cache(isa_id)
    if cached:
        return {"status": "ready", "cached": True}
    job = await _read_concession_job_state(isa_id)
    if job is None:
        return {"status": "unknown", "error": None, "cached": False}
    return {"status": job["status"], "error": job["error"], "cached": False}


@router.get("/concession/{isa_id}", dependencies=[Depends(get_api_key)])
async def concession_cached(isa_id: str):
    if db.pool is None:
        raise HTTPException(503, detail="Database unavailable")
    data = await _check_concession_cache(isa_id)
    if not data:
        raise HTTPException(404, detail="No cached neutral concession report; POST /v2/reports/concession first")
    return data


# ── SEO data for the server-rendered pages ──────────────────────────────────
#
# `frontend/seo/render-page.js` builds the HTML that Google indexes for
# /report/:platformId and /claim-report/:isaId. Until 2026-09-21 it fetched
# that data from v1, so every one of those ~40 indexed pages carried a meta
# description reading "Risk rating: High." — a verdict this platform computed
# from its own weights and published as if it were a finding about the sea.
#
# ⛔ Nothing below may emit a verdict word. `backend/scripts/check_neutral_report.py`
# rejects `critical`, `severe`, `significant`, `risk_score`, `risk_rating`,
# `severity`, `recommended`. What a reader gets instead is counts and distances,
# each traceable to a measurement or a concession boundary.


def _seo_meta(title: str, description: str, url: str, name: str, published: str) -> dict:
    return {
        "title": title,
        # 160 is Google's practical truncation point; cutting here rather than
        # letting the crawler do it keeps the sentence from ending mid-number.
        "description": description[:160],
        "canonical_url": url,
        "json_ld": {
            "@context": "https://schema.org",
            "@type": "Dataset",
            "name": name,
            "description": description,
            "url": url,
            "datePublished": published,
            "publisher": {
                "@type": "Organization",
                "name": "Abyssal Claims",
                "url": "https://something-rare.com",
            },
        },
    }


@router.get("/seo/{platform_id}", dependencies=[Depends(get_api_key)])
async def seo_platform_report(platform_id: str):
    """Neutral SSR payload for /report/{platform_id}."""
    if db.pool is None:
        raise HTTPException(503, detail="Database unavailable")
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT report_json, headline, measurement_count, concession_count, generated_at "
            "FROM report_cache_v2 WHERE platform_id = $1",
            platform_id,
        )
    if not row:
        raise HTTPException(404, detail="No cached neutral report for this float")

    report = json.loads(row["report_json"]) if isinstance(row["report_json"], str) else row["report_json"]
    summary = report.get("summary", {}) or {}
    url = f"https://something-rare.com/report/{platform_id}"
    description = (
        f"Argo float {platform_id}: {row['measurement_count']} attributed measurement(s) "
        f"near {row['concession_count']} mining concession(s). "
        f"{summary.get('measurements_below_baseline_p5', 0)} below the local baseline."
    )

    # The dossier list is trimmed, not summarised: each entry keeps the counts
    # and the distance the report computed, and nothing is folded into a score.
    dossiers = []
    for cd in (report.get("claim_dossiers") or [])[:5]:
        claim = cd.get("claim", {}) or {}
        dossiers.append({
            "concession_id": claim.get("concession_id"),
            "contractor_name": claim.get("contractor_name"),
            "min_distance_km": cd.get("min_distance_km"),
            "attributed_measurement_count": cd.get("attributed_measurement_count"),
            "profiles_within_50km": cd.get("profiles_within_50km"),
        })

    return {
        "meta": _seo_meta(
            f"Argo Float {platform_id} — Measurement Report | Abyssal Claims",
            description, url,
            f"Measurements attributed to Argo float {platform_id}",
            str(row["generated_at"].date()),
        ),
        "platform_id": platform_id,
        "headline": row["headline"],
        "summary": summary,
        "measurement_count": row["measurement_count"],
        "concession_count": row["concession_count"],
        "claim_summaries": dossiers,
        "generated_at": str(row["generated_at"]),
    }


@router.get("/seo/concession/{isa_id}", dependencies=[Depends(get_api_key)])
async def seo_concession_report(isa_id: str):
    """Neutral SSR payload for /claim-report/{isa_id}."""
    if db.pool is None:
        raise HTTPException(503, detail="Database unavailable")
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT report_json, headline, seamount_count, species_count, vent_count, generated_at "
            "FROM report_cache_v2_concession WHERE isa_id = $1",
            isa_id,
        )
    if not row:
        raise HTTPException(404, detail="No cached neutral concession report for this id")

    report = json.loads(row["report_json"]) if isinstance(row["report_json"], str) else row["report_json"]
    concession = report.get("concession", {}) or {}
    url = f"https://something-rare.com/claim-report/{isa_id}"
    radius = report.get("species_search_radius_km")
    # ⛔ The key is `contractor`, not `contractor_name`. Read from a real row
    # before writing the accessor: the sibling platform report uses the longer
    # name and assuming both matched produced a description with no contractor
    # in it — silently, because the guard was `if ... else ""`.
    contractor = concession.get("contractor") or concession.get("contractor_name")
    description = (
        f"ISA concession {isa_id}"
        + (f" ({contractor})" if contractor else "")
        + f": {row['species_count']} species record(s)"
        + (f" within {radius} km" if radius else "")
        + f", {row['vent_count']} hydrothermal vent(s), {row['seamount_count']} seamount(s)."
    )

    return {
        "meta": _seo_meta(
            f"ISA Concession {isa_id} — Environmental Context | Abyssal Claims",
            description, url,
            f"Environmental context for ISA concession {isa_id}",
            str(row["generated_at"].date()),
        ),
        "isa_id": isa_id,
        "headline": row["headline"],
        "contractor_name": contractor,
        "resource_type": concession.get("resource_type"),
        "area_km2": concession.get("area_km2"),
        "species_count": row["species_count"],
        "species_inside_count": report.get("species_inside_count"),
        "species_search_radius_km": radius,
        "vent_count": row["vent_count"],
        "seamount_count": row["seamount_count"],
        # ⚠️ `monitoring_floats` is an INTEGER here (a count), not the list its
        # plural name suggests. `len()` on it raised TypeError and the endpoint
        # answered 500 — caught on production before this reached a crawler.
        "monitoring_float_count": report.get("monitoring_floats"),
        "generated_at": str(row["generated_at"]),
    }
