# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""ISA concessions domain — the four ArcGIS registry syncs (reserved areas,
APEIs, relinquished areas, mining contracts), the claim-boundary enrichment
pass, and the claim read endpoints.

Moved verbatim out of backend/main.py (Task 3 of the backend vertical-split
refactor, Phase 4). Only permitted edits applied: `@app.get` -> `@router.get`,
`_pool` -> `db.pool` (the pattern established in Phases 1-3, since this module
cannot import main's `_pool` global without recreating the import cycle this
refactor removes), leading underscore dropped from every moved top-level
function name (`_resource_type` -> `resource_type`,
`_fetch_arcgis_features` -> `fetch_arcgis_features`,
`_sync_reserved_areas` -> `sync_reserved_areas`, `_sync_apeis` -> `sync_apeis`,
`_sync_relinquished_areas` -> `sync_relinquished_areas`,
`_sync_mining_contracts` -> `sync_mining_contracts`,
`_enrich_claim_boundaries` -> `enrich_claim_boundaries`,
`_sync_arcgis_group` -> `sync_arcgis_group` — same convention every other
domain module in this refactor established), and imports. Callers in main.py
reach them as `isa.<name>`.

Do NOT move `get_vent_mining_conflicts` here — it joins hydrothermal_vents,
mining_contracts, biodiversity_hotspots and argo_profiles (four families) and
is cross-domain analysis that stays in main.py, like correlate_plume.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import asyncpg
import db
import httpx
from auth import get_api_key
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from indexnow import notify_indexnow as _notify_indexnow, SITE_HOST
from sync_log import log_sync as _log_sync

log = logging.getLogger(__name__)
router = APIRouter()

ARCGIS_BASE = (
    "https://services5.arcgis.com/VcAAb5oBhdAAnFj2/arcgis/rest/services"
    "/fclContractAreas_20240724/FeatureServer"
)

# Resource type decoded from ContractID suffix
def resource_type(contract_id: str) -> str:
    cid = contract_id.upper()
    if "CRFC" in cid:  return "Cobalt-Rich Ferromanganese Crusts"
    if "PMS"  in cid:  return "Polymetallic Sulphides"
    if "PMN"  in cid:  return "Polymetallic Manganese Nodules"
    return "Unknown"

_claims_risk_cache: str | None = None


def clear_caches() -> None:
    """Sweep this domain's caches. Called via domains.CACHE_CLEARING_DOMAINS."""
    global _claims_risk_cache
    _claims_risk_cache = None


async def fetch_arcgis_features(layer_id: int, out_fields: str) -> list[dict]:
    """Paginated fetch of all features from an ArcGIS FeatureServer layer."""
    url = f"{ARCGIS_BASE}/{layer_id}/query"
    all_features: list[dict] = []
    offset = 0
    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            params = {
                "where": "1=1",
                "outFields": out_fields,
                "f": "geojson",
                "resultRecordCount": 1000,
                "resultOffset": offset,
            }
            r = await client.get(url, params=params)
            r.raise_for_status()
            features = r.json().get("features", [])
            all_features.extend(features)
            if len(features) < 1000:
                break
            offset += 1000
    return all_features

# ── Per-source sync ───────────────────────────────────────────────────────────

async def sync_reserved_areas(conn: asyncpg.Connection) -> int:
    features = await fetch_arcgis_features(
        33, "OBJECTID,ContractID,AreaType,AreaKM2,Status,Remarks"
    )
    inserted = 0
    for f in features:
        p = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom or p.get("OBJECTID") is None:
            continue
        result = await conn.execute(
            """INSERT INTO reserved_areas
                   (arcgis_id, contract_id, area_type, area_km2, status, remarks, geom)
               VALUES ($1, $2, $3, $4, $5, $6, ST_SetSRID(ST_GeomFromGeoJSON($7), 4326))
               ON CONFLICT (arcgis_id) DO NOTHING""",
            p["OBJECTID"], p.get("ContractID"), p.get("AreaType"),
            p.get("AreaKM2"), p.get("Status"), p.get("Remarks"),
            json.dumps(geom),
        )
        if result == "INSERT 0 1":
            inserted += 1
    await _log_sync("reserved_areas", inserted, len(features))
    log.info("reserved_areas: %d new / %d total", inserted, len(features))
    return inserted


async def sync_apeis(conn: asyncpg.Connection) -> int:
    features = await fetch_arcgis_features(35, "OBJECTID,AreaKM2,Status,Remarks")
    inserted = 0
    for f in features:
        p = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom or p.get("OBJECTID") is None:
            continue
        result = await conn.execute(
            """INSERT INTO isa_apeis (arcgis_id, area_km2, status, remarks, geom)
               VALUES ($1, $2, $3, $4, ST_SetSRID(ST_GeomFromGeoJSON($5), 4326))
               ON CONFLICT (arcgis_id) DO NOTHING""",
            p["OBJECTID"], p.get("AreaKM2"), p.get("Status"), p.get("Remarks"),
            json.dumps(geom),
        )
        if result == "INSERT 0 1":
            inserted += 1
    await _log_sync("apeis", inserted, len(features))
    log.info("isa_apeis: %d new / %d total", inserted, len(features))
    return inserted


async def sync_relinquished_areas(conn: asyncpg.Connection) -> int:
    # Key on OBJECTID_1 — the layer's real unique OID. The legacy `OBJECTID` column
    # (left over after the 2024-07-24 service republish) is a non-unique integer
    # attribute with only ~799 distinct values across 2,580 features, so keying on it
    # collapsed the table to 798 rows (~69% of relinquished areas were dropped).
    # TRUNCATE + reload in one transaction because existing rows hold stale,
    # OBJECTID-keyed arcgis_id values under a different key meaning.
    features = await fetch_arcgis_features(
        34, "OBJECTID_1,ContractID,AreaType,AreaKM2,ActDate,Status"
    )
    inserted = 0
    async with conn.transaction():
        await conn.execute("TRUNCATE relinquished_areas")
        for f in features:
            p = f.get("properties") or {}
            geom = f.get("geometry")
            if not geom or p.get("OBJECTID_1") is None:
                continue
            act_date = None
            if p.get("ActDate"):
                act_date = datetime.fromtimestamp(p["ActDate"] / 1000, tz=timezone.utc)
            result = await conn.execute(
                """INSERT INTO relinquished_areas
                       (arcgis_id, contract_id, area_type, area_km2, act_date, status, geom)
                   VALUES ($1, $2, $3, $4, $5, $6, ST_SetSRID(ST_GeomFromGeoJSON($7), 4326))
                   ON CONFLICT (arcgis_id) DO NOTHING""",
                p["OBJECTID_1"], p.get("ContractID"), p.get("AreaType"),
                p.get("AreaKM2"), act_date, p.get("Status"),
                json.dumps(geom),
            )
            if result == "INSERT 0 1":
                inserted += 1
    await _log_sync("relinquished_areas", inserted, len(features))
    log.info("relinquished_areas: %d new / %d total", inserted, len(features))
    return inserted


async def sync_mining_contracts(conn: asyncpg.Connection) -> int:
    """Sync active ISA exploration contracts from ArcGIS layer 32.
    New entries get contractor_name from isa_contract_lookup and is_high_risk
    computed via spatial overlap with biodiversity_hotspots.
    act_date comes from ArcGIS ActDate; expiry_date = act_date + 15 years (ISA contract term).
    region is not available in ArcGIS and remains NULL."""
    features = await fetch_arcgis_features(
        32, "OBJECTID,AreaKey,ContractID,AreaType,AreaKM2,ActDate,Status"
    )
    inserted = 0
    for f in features:
        p = f.get("properties") or {}
        geom = f.get("geometry")
        area_key = p.get("AreaKey")
        if not geom or not area_key:
            continue

        contractor = await conn.fetchval(
            "SELECT contractor_name FROM isa_contract_lookup WHERE contract_id = $1",
            p.get("ContractID"),
        )
        res_type = resource_type(p.get("ContractID") or "")
        geom_json = json.dumps(geom)

        act_date = None
        expiry_date = None
        if p.get("ActDate"):
            act_date = datetime.fromtimestamp(p["ActDate"] / 1000, tz=timezone.utc)
            expiry_date = act_date.replace(year=act_date.year + 15)

        result = await conn.execute(
            """INSERT INTO mining_contracts
                   (isa_id, contractor_name, resource_type, area_km2, act_date, expiry_date, geom, is_high_risk)
               VALUES ($1, $2, $3, $4, $5, $6, ST_SetSRID(ST_GeomFromGeoJSON($7), 4326), FALSE)
               ON CONFLICT (isa_id) DO UPDATE
                   SET contractor_name = COALESCE(EXCLUDED.contractor_name, mining_contracts.contractor_name),
                       resource_type   = CASE WHEN EXCLUDED.resource_type != 'Unknown'
                                              THEN EXCLUDED.resource_type
                                              ELSE mining_contracts.resource_type END,
                       act_date        = COALESCE(EXCLUDED.act_date, mining_contracts.act_date),
                       expiry_date     = COALESCE(EXCLUDED.expiry_date, mining_contracts.expiry_date)""",
            area_key, contractor, res_type, p.get("AreaKM2"), act_date, expiry_date, geom_json,
        )
        if result == "INSERT 0 1":
            inserted += 1

    # Single batch spatial join - uses GIST indexes, avoids 300K x 1300 per-row checks
    await conn.execute("""
        UPDATE mining_contracts mc
        SET is_high_risk = TRUE
        WHERE is_high_risk = FALSE
          AND EXISTS (
              SELECT 1 FROM biodiversity_hotspots h
              WHERE ST_Intersects(mc.geom, h.geom)
          )
    """)
    total = await conn.fetchval("SELECT COUNT(*) FROM mining_contracts")
    await _log_sync("mining_contracts", inserted, total)
    log.info("mining_contracts: %d new / %d total", inserted, total)
    if inserted > 0:
        await _notify_indexnow([f"https://{SITE_HOST}/sitemap.xml"])
    return inserted


async def enrich_claim_boundaries() -> int:
    """Pre-compute jurisdiction and UNESCO proximity for every mining claim.
    Safe to re-run — uses UPDATE so existing values are overwritten.
    Returns the number of claims updated.
    """
    log.info("claim boundaries: enriching mining_contracts…")
    async with db.pool.acquire() as conn:
        # NOTE on types: mc.geom and mb.geom are GEOMETRY(4326); ps.geom is GEOGRAPHY(POINT,4326).
        # ST_Within operates on GEOMETRY — correct for mc/mb.
        # ST_Distance on GEOMETRY gives degrees, not meters. We cast ::geography to get meters.
        # ps.geom is already GEOGRAPHY so no cast needed; mb.geom::geography is an implicit cast.
        # Do NOT accidentally swap these — mixing GEOMETRY/GEOGRAPHY in ST_Distance returns wrong units.

        # Check we have data to work with
        eez_count = await conn.fetchval("SELECT COUNT(*) FROM maritime_boundaries")
        unesco_count = await conn.fetchval("SELECT COUNT(*) FROM protected_marine_sites")
        if eez_count == 0 or unesco_count == 0:
            log.warning(
                "claim boundaries: skipping — maritime_boundaries=%d, protected_marine_sites=%d",
                eez_count, unesco_count,
            )
            return 0

        # Two-step approach: materialize centroids into a temp table first, then KNN join.
        # ST_Centroid(mc.geom) is expensive on MultiPolygons and cannot be cached by the planner.
        # By computing centroids once and storing them, the KNN <-> operator can use the GIST index
        # on maritime_boundaries/protected_marine_sites reliably.
        await conn.execute("""
            CREATE TEMP TABLE IF NOT EXISTS mc_centroids AS
            SELECT id, ST_Centroid(geom)::geometry(Point, 4326) AS ctr
            FROM mining_contracts
            WHERE geom IS NOT NULL
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS mc_centroids_gist ON mc_centroids USING GIST(ctr)"
        )

        result = await conn.execute("""
            UPDATE mining_contracts mc
            SET
                jurisdiction_text = COALESCE(
                    (SELECT 'Inside ' || mb.geoname
                     FROM maritime_boundaries mb
                     WHERE ST_Within(c.ctr, mb.geom)
                     LIMIT 1),
                    'International Waters / ISA'
                ),
                nearest_eez_country = eez_knn.sovereign1,
                nearest_eez_dist_km = ROUND(
                    (ST_Distance(c.ctr::geography, eez_knn.geom::geography) / 1000.0)::numeric, 1
                ),
                nearest_unesco_site = unesco_knn.name,
                nearest_unesco_dist_km = ROUND(
                    (ST_Distance(c.ctr::geography, unesco_knn.geom::geography) / 1000.0)::numeric, 1
                )
            FROM mc_centroids c
            LEFT JOIN LATERAL (
                SELECT mb.sovereign1, mb.geom
                FROM maritime_boundaries mb
                ORDER BY c.ctr <-> mb.geom
                LIMIT 1
            ) eez_knn ON true
            LEFT JOIN LATERAL (
                SELECT ps.name, ps.geom
                FROM protected_marine_sites ps
                WHERE ps.geom IS NOT NULL
                ORDER BY c.ctr <-> ps.geom
                LIMIT 1
            ) unesco_knn ON true
            WHERE mc.id = c.id
        """)

        # asyncpg result string is "UPDATE N"
        updated = int(result.split()[-1]) if result else 0
        log.info("claim boundaries: enriched %d claims", updated)

        # Second pass: populate the cached SEO count columns. These mirror the
        # 5 spatial subqueries that used to run live in /v1/seo/concession/{isa_id}.
        # Original implementation used per-row correlated subqueries (1318 × 5 =
        # 6,590 subquery executions); this CTE version does ONE spatial join per
        # target table (5 total) with GROUP BY, letting the planner batch the
        # spatial index lookups. ~30 min → ~2-3 min.
        log.info("claim boundaries: populating cached SEO counts…")
        await conn.execute("""
            WITH vent AS (
                SELECT c.id, COUNT(*) AS n
                FROM mc_centroids c
                JOIN hydrothermal_vents hv
                  ON ST_DWithin(hv.geom::geography, c.ctr::geography, 50000)
                GROUP BY c.id
            ),
            species AS (
                -- COUNT(*) instead of COUNT(DISTINCT scientific_name): the
                -- DISTINCT pass over biodiversity_hotspots was the dominant
                -- cost (~25-30 min per backfill). Observation-count is still
                -- meaningful for SEO ("N biodiversity records within 10 km").
                --
                -- 10 km, not 50: the project-wide radius for "species near a
                -- claim", set by the spacing between claims and protected zones.
                -- The degree clause is an index-friendly pre-filter on the
                -- bh.geom GIST index (a bare geography cast makes that index
                -- unusable and turns this into a scan of every row); the
                -- geography clause refines it to an exact 10 km at any latitude.
                -- Same pattern as services/species_cache.py.
                SELECT c.id, COUNT(*) AS n
                FROM mc_centroids c
                JOIN biodiversity_hotspots bh
                  ON ST_DWithin(bh.geom, c.ctr, 0.12)
                 AND ST_DWithin(bh.geom::geography, c.ctr::geography, 10000)
                GROUP BY c.id
            ),
            argo AS (
                SELECT c.id, COUNT(DISTINCT ap.platform_id) AS n
                FROM mc_centroids c
                JOIN argo_profiles ap
                  ON ap.near_mining = true
                 AND ap.profile_date > NOW() - INTERVAL '90 days'
                 AND ST_DWithin(ap.geom::geography, c.ctr::geography, 200000)
                GROUP BY c.id
            ),
            onc AS (
                -- latest_sensors IS NOT NULL restricts this to stations that
                -- actually carry oceanographic measurements (the same marker
                -- seo.py gates the sitemap on, and sync_onc_sensors() uses to
                -- decide what it has data for). Widening onc_ingest.py to all
                -- ~129 ONC device categories put ~1,993 locations (junction
                -- boxes, power supplies, cameras) within 200 km of most
                -- claims; without this filter nearby_onc_stations would count
                -- them all and the concession page would list dozens of
                -- non-instruments as "nearby ONC observatories".
                SELECT c.id, COUNT(*) AS n
                FROM mc_centroids c
                JOIN onc_locations ol
                  ON ST_DWithin(ol.geom::geography, c.ctr::geography, 200000)
                 AND ol.latest_sensors IS NOT NULL
                GROUP BY c.id
            ),
            oceansites AS (
                SELECT c.id, COUNT(*) AS n
                FROM mc_centroids c
                JOIN oceansites_stations os
                  ON ST_DWithin(os.geom::geography, c.ctr::geography, 500000)
                GROUP BY c.id
            )
            UPDATE mining_contracts mc SET
                vent_conflicts            = COALESCE(vent.n, 0),
                nearby_species            = COALESCE(species.n, 0),
                nearby_argo_floats        = COALESCE(argo.n, 0),
                nearby_onc_stations       = COALESCE(onc.n, 0),
                nearby_oceansites_moorings = COALESCE(oceansites.n, 0),
                seo_enriched_at = NOW()
            FROM mc_centroids c
            LEFT JOIN vent       ON vent.id       = c.id
            LEFT JOIN species    ON species.id    = c.id
            LEFT JOIN argo       ON argo.id       = c.id
            LEFT JOIN onc        ON onc.id        = c.id
            LEFT JOIN oceansites ON oceansites.id = c.id
            WHERE mc.id = c.id
        """)
        log.info("claim boundaries: SEO counts populated")
        return updated


async def sync_arcgis_group():
    async with db.pool.acquire() as conn:
        await sync_reserved_areas(conn)
        await sync_apeis(conn)
        await sync_relinquished_areas(conn)
        await sync_mining_contracts(conn)


# ── API endpoints ─────────────────────────────────────────────────────────────

@router.get("/v1/map/claims", dependencies=[Depends(get_api_key)])
async def get_claims():
    sql = """
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', coalesce(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(geom)::json,
                    'properties', json_build_object(
                        'isa_id', isa_id,
                        'contractor_name', contractor_name,
                        'resource_type', resource_type,
                        'area_km2', area_km2,
                        'expiry_date', expiry_date,
                        'region', region,
                        'is_high_risk', is_high_risk,
                        'jurisdiction_text', jurisdiction_text,
                        'nearest_eez_country', nearest_eez_country,
                        'nearest_eez_dist_km', nearest_eez_dist_km,
                        'nearest_unesco_site', nearest_unesco_site,
                        'nearest_unesco_dist_km', nearest_unesco_dist_km
                    )
                )
            ), '[]'::json)
        ) AS geojson
        FROM mining_contracts
        WHERE geom IS NOT NULL
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql)
    return Response(content=row["geojson"], media_type="application/json")


@router.get("/v1/map/reserved-areas", dependencies=[Depends(get_api_key)])
async def get_reserved_areas():
    sql = """
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', coalesce(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(geom)::json,
                    'properties', json_build_object(
                        'arcgis_id',  arcgis_id,
                        'ContractID', contract_id,
                        'AreaType',   area_type,
                        'AreaKM2',    area_km2,
                        'Status',     status,
                        'Remarks',    remarks
                    )
                )
            ), '[]'::json)
        ) AS geojson
        FROM reserved_areas
        WHERE geom IS NOT NULL
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql)
    return Response(content=row["geojson"], media_type="application/json")


@router.get("/v1/map/apeis", dependencies=[Depends(get_api_key)])
async def get_apeis():
    sql = """
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', coalesce(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(geom)::json,
                    'properties', json_build_object(
                        'arcgis_id', arcgis_id,
                        'AreaKM2',   area_km2,
                        'Status',    status,
                        'Remarks',   remarks
                    )
                )
            ), '[]'::json)
        ) AS geojson
        FROM isa_apeis
        WHERE geom IS NOT NULL
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql)
    return Response(content=row["geojson"], media_type="application/json")


@router.get("/v1/map/relinquished-areas", dependencies=[Depends(get_api_key)])
async def get_relinquished_areas():
    sql = """
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', coalesce(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(r.geom)::json,
                    'properties', json_build_object(
                        'arcgis_id',       r.arcgis_id,
                        'ContractID',      r.contract_id,
                        'AreaType',        r.area_type,
                        'AreaKM2',         r.area_km2,
                        'ActDate',         EXTRACT(EPOCH FROM r.act_date) * 1000,
                        'Status',          r.status,
                        'contractor_name', l.contractor_name
                    )
                )
            ), '[]'::json)
        ) AS geojson
        FROM relinquished_areas r
        LEFT JOIN isa_contract_lookup l ON r.contract_id = l.contract_id
        WHERE r.geom IS NOT NULL
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql)
    return Response(content=row["geojson"], media_type="application/json")


@router.get("/v1/map/claims/species-risk", dependencies=[Depends(get_api_key)])
async def get_claims_species_risk():
    """Return mining claims ranked by threatened species count (PostGIS intersection).

    Cached in memory — cleared on restart. Expensive query (~2s) runs once per session.
    Returns claims that have at least one species with a known IUCN category (not NE/DD).
    """
    global _claims_risk_cache
    if _claims_risk_cache:
        return Response(content=_claims_risk_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT mc.isa_id,
                   mc.contractor_name,
                   mc.resource_type,
                   ST_X(ST_Centroid(mc.geom)) AS lon,
                   ST_Y(ST_Centroid(mc.geom)) AS lat,
                   COUNT(DISTINCT CASE WHEN h.iucn_category IN ('CR','EN')
                         THEN h.scientific_name END)             AS cr_en_count,
                   COUNT(DISTINCT CASE WHEN h.iucn_category = 'VU'
                         THEN h.scientific_name END)             AS vu_count,
                   COUNT(DISTINCT CASE WHEN h.iucn_category IN ('NT','LC')
                         THEN h.scientific_name END)             AS nt_lc_count
            FROM   mining_contracts mc
            JOIN   biodiversity_hotspots h ON ST_Intersects(h.geom, mc.geom)
            WHERE  h.iucn_category IN ('CR','EN','VU','NT','LC')
              AND  h.geom  IS NOT NULL
              AND  mc.geom IS NOT NULL
            GROUP  BY mc.isa_id, mc.contractor_name, mc.resource_type, mc.geom
            ORDER  BY cr_en_count DESC, vu_count DESC, nt_lc_count DESC
        """)

    result = json.dumps([
        {
            "isa_id":           r["isa_id"],
            "contractor_name":  r["contractor_name"],
            "resource_type":    r["resource_type"],
            "lon":              r["lon"],
            "lat":              r["lat"],
            "cr_en_count":      r["cr_en_count"],
            "vu_count":         r["vu_count"],
            "nt_lc_count":      r["nt_lc_count"],
        }
        for r in rows
    ])
    _claims_risk_cache = result
    return Response(content=result, media_type="application/json")
