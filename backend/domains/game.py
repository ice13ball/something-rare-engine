# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Public game domain — GET /v1/game/block/{isa_id}.

Serves one nodule contract block (mining_contracts) plus all isa_apeis rows as
a single GeoJSON FeatureCollection, for a browser game. Deliberately narrow:
only the columns needed by the game are selected from mining_contracts, never
contractor_name/jurisdiction/nearest_* — see the SELECT list below.

Caching mirrors `domains/geo_context.py`'s `get_eez` pattern: the shared
response-cache store (`response_cache.store`, aliased `_cache` here) keyed
per isa_id, with this module's own TTL. ISA sync (`domains/isa.py`) never
clears caches on completion, so the only invalidation is TTL expiry or an
admin cache-clear sweep (`/admin/cache/clear` via `CACHE_CLEARING_DOMAINS`) —
do not assume any other trigger exists.
"""
from __future__ import annotations

import json
import time
from datetime import timezone

import db
from auth import get_api_key
from fastapi import APIRouter, Depends, HTTPException, Response
from response_cache import store as _cache

router = APIRouter()

_GAME_BLOCK_TTL = 86400  # ISA tables only change on sync; TTL + admin cache-clear are the only invalidation.

# The exact source URL the platform legend already links for ISA exploration
# contracts (backend/main.py, LAYER metadata table, row "isa-contracts").
_ISA_SOURCE_URL = "https://www.isa.org.jm/exploration-contracts/"


def clear_caches() -> None:
    """Drop every cached response in the shared store (same convention as
    `geo_context.clear_caches()`/`seafloor.clear_caches()`: each module
    aliasing the shared `response_cache.store` clears it wholesale, redundant
    but idempotent). Registered in domains/__init__.py's
    CACHE_CLEARING_DOMAINS so /admin/cache/clear sweeps this module too."""
    _cache.clear()


@router.get("/v1/game/block/{isa_id}", dependencies=[Depends(get_api_key)])
async def get_game_block(isa_id: str):
    cache_key = f"game_block:{isa_id}"
    cached = _cache.get(cache_key)
    if cached is not None:
        fetched_at, data = cached
        if time.monotonic() - fetched_at < _GAME_BLOCK_TTL:
            return Response(
                content=data,
                media_type="application/json",
                headers={
                    "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
                    "X-Cache": "HIT",
                },
            )

    sql = """
        SELECT
            isa_id,
            resource_type,
            area_km2,
            round(ST_X(ST_Centroid(geom))::numeric, 5) AS centroid_lon,
            round(ST_Y(ST_Centroid(geom))::numeric, 5) AS centroid_lat,
            ST_AsGeoJSON(geom) AS geojson
        FROM mining_contracts
        WHERE isa_id = $1
    """
    async with db.pool.acquire() as conn:
        block = await conn.fetchrow(sql, isa_id)

        if block is None:
            raise HTTPException(status_code=404, detail="Unknown isa_id")
        if block["resource_type"] != "Polymetallic Manganese Nodules":
            raise HTTPException(
                status_code=400,
                detail="The game only supports Polymetallic Manganese Nodules blocks",
            )

        apeis_sql = """
            SELECT arcgis_id, area_km2, status, remarks, ST_AsGeoJSON(geom) AS geojson
            FROM isa_apeis
            WHERE geom IS NOT NULL
            ORDER BY arcgis_id
        """
        apeis_rows = await conn.fetch(apeis_sql)

        # Do NOT use isa_apeis.synced_at — on production it is stuck at
        # 2026-03-24 because sync_apeis's INSERT uses ON CONFLICT DO NOTHING,
        # so it never advances on re-sync. sync_log is the honest source.
        synced_at_row = await conn.fetchrow(
            "SELECT max(last_synced_at) AS synced_at FROM sync_log WHERE source IN ('mining_contracts', 'apeis')"
        )

    # A block row with no geometry still answers (null geometry is valid GeoJSON)
    # instead of a 500 from json.loads(None).
    block_geom = json.loads(block["geojson"]) if block["geojson"] is not None else None
    features = [
        {
            "type": "Feature",
            "geometry": block_geom,
            "properties": {
                "kind": "block",
                "isa_id": block["isa_id"],
                "resource_type": block["resource_type"],
                "area_km2": block["area_km2"],
                "centroid_lon": float(block["centroid_lon"]) if block["centroid_lon"] is not None else None,
                "centroid_lat": float(block["centroid_lat"]) if block["centroid_lat"] is not None else None,
            },
        }
    ]
    for r in apeis_rows:
        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(r["geojson"]),
                "properties": {
                    "kind": "apei",
                    "arcgis_id": r["arcgis_id"],
                    "AreaKM2": r["area_km2"],
                    "Status": r["status"],
                    "Remarks": r["remarks"],
                },
            }
        )

    synced_at = synced_at_row["synced_at"] if synced_at_row else None
    synced_at_iso = None
    if synced_at is not None:
        if synced_at.tzinfo is None:
            synced_at = synced_at.replace(tzinfo=timezone.utc)
        synced_at_iso = synced_at.isoformat()

    body = {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "source": "International Seabed Authority (DeepData)",
            "source_url": _ISA_SOURCE_URL,
            "synced_at": synced_at_iso,
        },
    }

    data = json.dumps(body, allow_nan=False).encode()
    _cache[cache_key] = (time.monotonic(), data)

    return Response(
        content=data,
        media_type="application/json",
        headers={
            "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
            "X-Cache": "MISS",
        },
    )
