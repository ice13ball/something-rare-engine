# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Arctic land layers: arctic river stations (ArcticGRO + PANGAEA) and
permafrost-thaw features (Alaska Webb + ARTS pan-Arctic). Split out of
land_layers.py.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import Response

import db
from auth import get_api_key

log = logging.getLogger("land_layers")
router = APIRouter(tags=["land-layers"], dependencies=[Depends(get_api_key)])

# ── Module-level caches (cleared on sync) ──────────────────────────────────
_arctic_rivers_cache: str | None = None
_permafrost_thaw_cache: str | None = None


def clear_caches() -> None:
    """Reset this module's caches. Delegated into from land_layers.clear_caches()
    so the combined 13-cache sweep still clears everything from one call."""
    global _arctic_rivers_cache, _permafrost_thaw_cache
    _arctic_rivers_cache = None
    _permafrost_thaw_cache = None


# ── Arctic River Stations ──────────────────────────────────────────────────

async def _sync_arctic_rivers(force: bool = False) -> int:
    """Fetch ArcticGRO + PANGAEA river station data and upsert into arctic_river_stations.

    Per-source try/except isolation: one source failing must not abort the
    others.  If zero stations are built across all sources, existing DB data is
    preserved and 0 is returned.  DB writes only happen when at least one source
    succeeds.
    """
    from ingestion import arctic_rivers as ar
    global _arctic_rivers_cache

    builders: list[dict] = []

    # ArcticGRO — one Google Sheet tab per river (6 tabs).
    try:
        sheets = await asyncio.to_thread(ar.fetch_arcticgro)
        rows = ar.build_arcticgro_stations(sheets)
        builders += rows
        log.info("arctic-rivers: arcticgro built %d stations", len(rows))
    except Exception as exc:
        log.warning("arctic-rivers: arcticgro source failed: %s", exc)

    # PANGAEA Canadian Arctic Archipelago Rivers (945702). NOTE: PANGAEA.913197
    # (Lena/Samoylov) is a collection with no machine-readable textfile — it
    # needs a specific child-dataset DOI and is a documented follow-up.
    try:
        caa_rows = await asyncio.to_thread(ar.fetch_pangaea, "945702")
        rows = ar.build_pangaea_caa_stations(caa_rows)
        builders += rows
        log.info("arctic-rivers: pangaea_caa built %d stations", len(rows))
    except Exception as exc:
        log.warning("arctic-rivers: pangaea_caa source failed: %s", exc)

    if not builders:
        log.warning("arctic-rivers: 0 stations across all sources; preserving existing data")
        return 0

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("TRUNCATE arctic_river_stations")
            for s in builders:
                await conn.execute(
                    """
                    INSERT INTO arctic_river_stations
                      (station_id, source, river_name, site_label, lat, lon, geom,
                       record_start, record_end, mean_annual_discharge_km3,
                       summary_stats, discharge_monthly, biogeochem_monthly,
                       annual_fluxes, citation, units)
                    VALUES ($1, $2, $3, $4, $5, $6, ST_GeomFromText($7, 4326),
                            $8, $9, $10, $11, $12, $13, $14, $15, $16)
                    """,
                    s["station_id"], s["source"], s["river_name"], s["site_label"],
                    s["lat"], s["lon"], s["geom_wkt"],
                    s["record_start"], s["record_end"],
                    s["mean_annual_discharge_km3"],
                    json.dumps(s["summary_stats"]),
                    json.dumps(s["discharge_monthly"]) if s["discharge_monthly"] else None,
                    json.dumps(s["biogeochem_monthly"]),
                    json.dumps(s["annual_fluxes"]) if s["annual_fluxes"] else None,
                    s["citation"],
                    json.dumps(s.get("units")) if s.get("units") else None,
                )

    _arctic_rivers_cache = None
    log.info("arctic-rivers: inserted %d stations", len(builders))
    return len(builders)


@router.get("/arctic-rivers")
async def get_arctic_rivers():
    global _arctic_rivers_cache
    if _arctic_rivers_cache:
        return Response(content=_arctic_rivers_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        row = await conn.fetchval("""
            SELECT json_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(json_agg(
                    json_build_object(
                        'type', 'Feature',
                        'geometry', ST_AsGeoJSON(geom)::json,
                        'properties', json_build_object(
                            'station_id', station_id,
                            'source', source,
                            'river_name', river_name,
                            'site_label', site_label,
                            'record_start', record_start,
                            'record_end', record_end,
                            'mean_annual_discharge_km3', mean_annual_discharge_km3,
                            'summary_stats', summary_stats,
                            'units', units,
                            'discharge_monthly', discharge_monthly,
                            'biogeochem_monthly', biogeochem_monthly,
                            'annual_fluxes', annual_fluxes,
                            'citation', citation
                        )
                    )
                ), '[]'::json)
            )::text
            FROM arctic_river_stations
        """)

    _arctic_rivers_cache = row if isinstance(row, str) else json.dumps(row)
    return Response(content=_arctic_rivers_cache, media_type="application/json")


# ── Permafrost Thaw Features ────────────────────────────────────────────────

async def _sync_pf_source(source: str, fetch, build, force: bool) -> int:
    """Sync one permafrost-thaw sub-source. Per-source skip-if-populated;
    preserves that source's rows on any fetch/parse failure; DELETE-by-source (never TRUNCATE)."""
    async with db.pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM permafrost_thaw_features WHERE source=$1", source)
    if not force and existing and existing > 0:
        log.info("permafrost-thaw[%s]: skip — %d rows present", source, existing)
        return 0
    try:
        gj = await asyncio.to_thread(fetch)
    except Exception as exc:
        log.error("permafrost-thaw[%s]: fetch failed (%s) — keeping %d rows", source, exc, existing or 0)
        return 0
    rows = build(gj)
    if not rows:
        log.warning("permafrost-thaw[%s]: 0 rows parsed — preserving existing", source)
        return 0
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM permafrost_thaw_features WHERE source=$1", source)
            await conn.executemany(
                """INSERT INTO permafrost_thaw_features
                     (source, unique_id, feature_name, feature_type, feature_category,
                      thaw_type, data_source_type, authors, source_doi, imagery, lat, lon, geom)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,
                           ST_SetSRID(ST_MakePoint($12,$11),4326))""",
                [(r["source"], r["unique_id"], r["feature_name"], r["feature_type"],
                  r["feature_category"], r["thaw_type"], r["data_source_type"], r["authors"],
                  r["source_doi"], r["imagery"], r["lat"], r["lon"]) for r in rows])
    log.info("permafrost-thaw[%s]: inserted %d rows", source, len(rows))
    return len(rows)


async def _sync_permafrost_thaw(force: bool = False) -> int:
    """Sync all permafrost-thaw sub-sources (Alaska Webb + ARTS pan-Arctic)."""
    from ingestion import permafrost_thaw as pt
    from ingestion import arts_ingest as arts
    global _permafrost_thaw_cache
    n = 0
    n += await _sync_pf_source("alaska_webb", pt.fetch_alaska_thaw_geojson, pt.build_thaw_rows, force)
    n += await _sync_pf_source("arts_panarctic", arts.fetch_arts_geojson, arts.build_arts_rows, force)
    _permafrost_thaw_cache = None
    return n


@router.get("/permafrost-thaw")
async def get_permafrost_thaw():
    global _permafrost_thaw_cache
    if _permafrost_thaw_cache:
        return Response(content=_permafrost_thaw_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        row = await conn.fetchval("""
            SELECT json_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(json_agg(
                    json_build_object(
                        'type', 'Feature',
                        'geometry', ST_AsGeoJSON(geom)::json,
                        'properties', json_build_object(
                            'unique_id', unique_id,
                            'source', source,
                            'feature_name', feature_name,
                            'feature_type', feature_type,
                            'feature_category', feature_category,
                            'thaw_type', thaw_type,
                            'data_source_type', data_source_type,
                            'authors', authors,
                            'source_doi', source_doi,
                            'imagery', imagery
                        )
                    )
                ), '[]'::json)
            )::text
            FROM permafrost_thaw_features
        """)

    _permafrost_thaw_cache = row if isinstance(row, str) else json.dumps(row)
    return Response(content=_permafrost_thaw_cache, media_type="application/json")


