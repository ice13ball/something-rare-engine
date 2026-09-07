# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Geographic context — EEZ boundaries, UNESCO protected marine sites, ports.

Three unrelated reference sources grouped by role rather than by provider: none of
them is a mining or measurement layer, all three exist to give other layers context.

⚠ `maritime_boundaries` is NOT a coastline and `protected_marine_sites` is a 50-row
UNESCO World Heritage list, NOT a protected-areas database. Two external analyses have already been misled
by these table names.

Moved verbatim out of backend/main.py (Task 2 of the backend vertical-split refactor
— the domain chosen to re-validate the Task-1 clear_caches() pattern on the
smallest, least-entangled slice before the cache-owning domains follow). Only
permitted edits applied: `@app.get` -> `@router.get`, `_pool.acquire()` ->
`db.pool.acquire()`, leading underscore dropped from the three sync function names,
and imports/docstring.

`get_eez`/`get_protected_marine_sites` did NOT have dedicated cache globals in
main.py — they read/write a shared TTL response cache (21600s) with nine call
sites total: at the time, seven were still in main.py (`get_seamounts`,
`get_vents`, `get_vent_mining_conflicts`, `correlate_plume`,
`get_plume_history`, `_sync_seamounts`, `admin_cache_clear`) plus the two
moved here (`get_eez`, `get_protected_marine_sites`) — a generic mechanism,
not domain data. It now lives in the leaf module `backend/response_cache.py`.
Consumers alias the store as `_cache` so call sites stay byte-identical to the
pre-refactor code:

    from response_cache import CACHE_TTL, store as _cache

Later tasks in this plan moved three of those seven remaining call sites into
their own domains: `seafloor` (Task 6) took `get_seamounts`/`get_vents`/
`_sync_seamounts` (now `sync_seamounts`) — those calls now go through
`domains/seafloor.py`, imported the same leaf the same way, not a copied TTL
dict. The other four (`get_vent_mining_conflicts`, `correlate_plume`,
`get_plume_history`, `admin_cache_clear`) remain in main.py; no `plumes`
domain has been built. `clear_caches()` still clears the
shared store on top of `admin_cache_clear`'s own `_cache.clear()` — redundant,
but idempotent, and it keeps `test_domain_cache_clear.py` (which scans for
cache-shaped names and asserts they're falsy post-clear) honest about this
module's `_cache` alias.

`get_ports`, unlike its two siblings, *did* have a dedicated `_ports_cache: str |
None` global in main.py — a genuine per-endpoint cache, not the shared store —
carried over unchanged.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import db
import httpx
from auth import get_api_key
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from response_cache import CACHE_TTL, store as _cache
from sync_log import log_sync as _log_sync

log = logging.getLogger(__name__)
router = APIRouter()

EEZ_WFS_URL = (
    "https://geo.vliz.be/geoserver/MarineRegions/ows"
    "?service=WFS&version=1.0.0&request=GetFeature"
    "&typeName=MarineRegions:eez"
    "&outputFormat=application/json"
    "&maxFeatures=500"
    # 'the_geom' is the actual geometry column name in this WFS layer (confirmed via geometry_name field).
    # It must be listed in propertyName for the geometry to be returned.
    "&propertyName=mrgid,geoname,sovereign1,iso_ter1,area_km2,the_geom"
)

UNESCO_WFS_URL = (
    "https://geo.vliz.be/geoserver/MarineRegions/ows"
    "?service=WFS&version=1.0.0&request=GetFeature"
    "&typeName=MarineRegions:worldheritagemarineprogramme"
    "&outputFormat=application/json"
    "&maxFeatures=200"
    # No propertyName — this layer returns XML error when propertyName includes the_geom.
    # All fields + geometry are returned by default; we pick what we need from properties.
)

# ── Caches ──────────────────────────────────────────────────────────────────
# `_cache`/`CACHE_TTL` are the shared response cache imported above (see module
# docstring). `_ports_cache` is this domain's one genuine dedicated global.
_ports_cache: str | None = None


def clear_caches() -> None:
    """Drop this domain's cached responses. Called by /admin/cache/clear."""
    global _ports_cache
    _cache.clear()
    _ports_cache = None


async def sync_eez() -> int:
    """Fetch World EEZ v12 from MarineRegions WFS and store simplified polygons.
    Uses a 30-day sync guard — EEZ boundaries change rarely.
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_synced_at FROM sync_log WHERE source = 'eez'"
        )
        if row and row["last_synced_at"]:
            age_days = (datetime.now(timezone.utc) - row["last_synced_at"]).days
            if age_days < 30:
                log.info("eez: sync skipped — last synced %d days ago", age_days)
                return 0

    log.info("eez: fetching World EEZ v12 from MarineRegions WFS…")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.get(EEZ_WFS_URL)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.error("eez: WFS fetch failed: %s", e)
        return 0

    features = data.get("features") or []
    if not features:
        log.error("eez: no features returned — check WFS endpoint")
        return 0

    # Import shapely once outside the loop — re-importing per iteration is slow and non-idiomatic
    from shapely.geometry import shape, mapping, MultiPolygon  # noqa: PLC0415

    inserted = 0
    # Second connection opened after the HTTP call completes — this is intentional:
    # we release the DB connection during the (potentially slow) HTTP fetch, then
    # re-acquire for the bulk insert. Consistent with _sync_hydrothermal_vents().
    async with db.pool.acquire() as conn:
        for f in features:
            props = f.get("properties") or {}
            geom = f.get("geometry")
            mrgid = props.get("mrgid")
            geoname = props.get("geoname") or props.get("GEONAME")
            if not geom or not mrgid or not geoname:
                continue

            # Simplify geometry to reduce storage (~5 km tolerance is fine for jurisdiction checks)
            try:
                shp = shape(geom)
                simplified = shp.simplify(0.05, preserve_topology=True)
                # Ensure it's a MultiPolygon
                if simplified.geom_type == "Polygon":
                    simplified = MultiPolygon([simplified])
                elif simplified.geom_type not in ("MultiPolygon", "Polygon"):
                    continue
                geom_json = json.dumps(mapping(simplified))
            except Exception as e:
                log.warning("eez: simplify failed for mrgid=%s: %s", mrgid, e)
                geom_json = json.dumps(geom)

            try:
                await conn.execute(
                    """INSERT INTO maritime_boundaries
                           (mrgid, geoname, sovereign1, iso_ter1, area_km2, geom)
                       VALUES ($1, $2, $3, $4, $5,
                               ST_SetSRID(ST_GeomFromGeoJSON($6), 4326))
                       ON CONFLICT (mrgid) DO UPDATE
                           SET geoname = EXCLUDED.geoname,
                               synced_at = now()""",
                    int(mrgid),
                    geoname,
                    props.get("sovereign1") or props.get("SOVEREIGN1"),
                    props.get("iso_ter1") or props.get("ISO_TER1"),
                    float(props.get("area_km2") or 0) or None,
                    geom_json,
                )
                inserted += 1
            except Exception as e:
                log.warning("eez: insert failed for mrgid=%s: %s", mrgid, e)

    total = inserted  # WFS gives full dataset each time
    await _log_sync("eez", inserted, total)
    log.info("eez: %d zones inserted/updated", inserted)
    return inserted


async def sync_protected_marine_sites() -> int:
    """Fetch UNESCO World Heritage Marine Programme sites from MarineRegions WFS.
    Stores polygon boundaries (not just centroids) for accurate distance calculations.
    Uses a 30-day sync guard — this list changes at most once a year.
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_synced_at FROM sync_log WHERE source = 'protected_marine_sites'"
        )
        if row and row["last_synced_at"]:
            age_days = (datetime.now(timezone.utc) - row["last_synced_at"]).days
            if age_days < 30:
                log.info("protected_marine_sites: sync skipped — %d days old", age_days)
                return 0

    log.info("protected_marine_sites: fetching UNESCO World Heritage Marine sites from MarineRegions WFS…")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(UNESCO_WFS_URL)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.error("protected_marine_sites: fetch failed: %s", e)
        return 0

    features = data.get("features") or []
    if not features:
        log.error("protected_marine_sites: no features returned — check WFS endpoint")
        return 0

    # Import shapely once outside the loop (same pattern as sync_eez)
    from shapely.geometry import shape, mapping, MultiPolygon  # noqa: PLC0415

    inserted = 0
    async with db.pool.acquire() as conn:
        for f in features:
            props = f.get("properties") or {}
            geom = f.get("geometry")
            mrgid = props.get("mrgid")
            name = props.get("full_name") or ""
            if not mrgid or not name:
                continue

            geom_json: str | None = None
            if geom:
                try:
                    shp = shape(geom)
                    simplified = shp.simplify(0.01, preserve_topology=True)
                    if simplified.geom_type == "Polygon":
                        simplified = MultiPolygon([simplified])
                    elif simplified.geom_type not in ("MultiPolygon",):
                        simplified = shp  # keep original if simplification changes type unexpectedly
                    geom_json = json.dumps(mapping(simplified))
                except Exception as e:
                    log.warning("protected_marine_sites: simplify failed for mrgid=%s: %s", mrgid, e)
                    geom_json = json.dumps(geom)

            try:
                await conn.execute(
                    """INSERT INTO protected_marine_sites
                           (site_id, name, country, lat_whc, lon_whc, area_km2, geom)
                       VALUES ($1, $2, $3, $4, $5, $6,
                               CASE WHEN $7::text IS NOT NULL
                                    THEN ST_SetSRID(ST_GeomFromGeoJSON($7), 4326)
                                    ELSE NULL END)
                       ON CONFLICT (site_id) DO UPDATE
                           SET name = EXCLUDED.name,
                               synced_at = now()""",
                    int(mrgid),
                    name,
                    props.get("country"),
                    float(props.get("lat_whc") or 0) or None,
                    float(props.get("long_whc") or 0) or None,
                    float(props.get("area_km2") or 0) or None,
                    geom_json,
                )
                inserted += 1
            except Exception as e:
                log.warning("protected_marine_sites: insert failed for mrgid=%s: %s", mrgid, e)

        # Fetch total inside the same connection — avoids opening a third pool connection
        total = await conn.fetchval("SELECT COUNT(*) FROM protected_marine_sites")
    await _log_sync("protected_marine_sites", inserted, total)
    log.info("protected_marine_sites: %d sites inserted/updated (%d total)", inserted, total)
    return inserted


async def sync_port_locations(force: bool = False) -> int:
    """Fetch global port locations from tayljordan/ports (GitHub) and cache in PostGIS."""
    async with db.pool.acquire() as conn:
        last = await conn.fetchval("SELECT last_synced_at FROM sync_log WHERE source = 'port_locations'")
        if not force and last and (datetime.now(tz=timezone.utc) - last).days < 30:
            log.info("port_locations: skipping — synced %s", last.date())
            return 0

    url = "https://raw.githubusercontent.com/tayljordan/ports/main/ports.json"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url)
        r.raise_for_status()
    payload = r.json()
    # Upstream changed shape (2026-05): previously a bare list of port dicts with
    # UPPERCASE keys (LATITUDE/LONGITUDE/CITY/…); now a dict
    # {"metadata": {...}, "ports": [...]} with lowercase keys. Accept both.
    ports = payload.get("ports") if isinstance(payload, dict) else payload
    if not ports:
        log.warning("port_locations: no records returned")
        return 0

    inserted = 0
    async with db.pool.acquire() as conn:
        # TRUNCATE+INSERT in a single transaction: the source is a small,
        # bulk-replaced GitHub JSON (~3898 rows) and the table has no UNIQUE
        # constraint, so prior `ON CONFLICT DO NOTHING` was a no-op and any
        # re-sync silently duplicated every row.
        async with conn.transaction():
            await conn.execute("TRUNCATE TABLE port_locations RESTART IDENTITY")
            for p in ports:
                if not isinstance(p, dict):
                    continue
                lat, lon = p.get("latitude"), p.get("longitude")
                if lat is None or lon is None:
                    continue
                try:
                    await conn.execute(
                        """INSERT INTO port_locations (city, state, country, geom)
                           VALUES ($1, $2, $3, ST_SetSRID(ST_MakePoint($4, $5), 4326))""",
                        p.get("wpi_port_name"),
                        p.get("state"),
                        p.get("country"),
                        float(lon), float(lat),
                    )
                    inserted += 1
                except Exception as e:
                    log.warning("port_locations: insert failed: %s", e)
            total = await conn.fetchval("SELECT COUNT(*) FROM port_locations")
    global _ports_cache
    _ports_cache = None
    await _log_sync("port_locations", inserted, total)
    log.info("port_locations: %d new / %d total", inserted, total)
    return inserted


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/v1/map/eez", dependencies=[Depends(get_api_key)])
async def get_eez():
    cache_key = "eez"
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
                    'geometry', ST_AsGeoJSON(ST_Simplify(geom, 0.5))::json,
                    'properties', json_build_object(
                        'mrgid',      mrgid,
                        'geoname',    geoname,
                        'sovereign1', sovereign1,
                        'iso_ter1',   iso_ter1,
                        'area_km2',   area_km2
                    )
                )
            ), '[]'::json)
        ) AS geojson
        FROM maritime_boundaries
        WHERE geom IS NOT NULL
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql)
    if not row or not row["geojson"]:
        raise HTTPException(status_code=503, detail="Database unavailable")

    data = row["geojson"].encode() if isinstance(row["geojson"], str) else row["geojson"]
    _cache[cache_key] = (time.monotonic(), data)
    return Response(content=data, media_type="application/json")


@router.get("/v1/map/protected-marine-sites", dependencies=[Depends(get_api_key)])
async def get_protected_marine_sites():
    cache_key = "protected_marine_sites"
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
                        'site_id',  site_id,
                        'name',     name,
                        'country',  country,
                        'area_km2', area_km2
                    )
                )
            ), '[]'::json)
        ) AS geojson
        FROM protected_marine_sites
        WHERE geom IS NOT NULL
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql)
    if not row or not row["geojson"]:
        raise HTTPException(status_code=503, detail="Database unavailable")

    data = row["geojson"].encode() if isinstance(row["geojson"], str) else row["geojson"]
    _cache[cache_key] = (time.monotonic(), data)
    return Response(content=data, media_type="application/json")


@router.get("/v1/map/ports", dependencies=[Depends(get_api_key)])
async def get_ports():
    """Return port locations as GeoJSON FeatureCollection."""
    global _ports_cache
    if _ports_cache:
        return Response(content=_ports_cache, media_type="application/json")
    sql = """
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', coalesce(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(geom)::json,
                    'properties', json_build_object(
                        'city',    city,
                        'state',   state,
                        'country', country
                    )
                )
            ), '[]'::json)
        ) AS geojson
        FROM port_locations
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql)
    result = row["geojson"] if isinstance(row["geojson"], str) else json.dumps(row["geojson"])
    _ports_cache = result
    return Response(content=result, media_type="application/json")
