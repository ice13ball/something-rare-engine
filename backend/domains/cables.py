# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Submarine cables domain — syncs, endpoints and caches for the six cable
sub-sources (EMODnet, ONC, OOI, NOAA Marine Cadastre, NZ LINZ, AU ACMA).

Moved verbatim out of backend/main.py (Task 5 of the backend vertical-split
refactor — the pilot vertical slice). Only permitted edits applied: `@app.get`
-> `@router.get`, `_pool.acquire()` -> `db.pool.acquire()` (the pattern
established in Tasks 3/4 and already used throughout routers/*.py and
land_layers.py, since this module cannot import main's `_pool` global without
recreating the import cycle this refactor removes), leading underscore
dropped from the six sync function names, and imports/docstring.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import db
import httpx
from auth import get_api_key
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sync_log import log_sync as _log_sync

log = logging.getLogger(__name__)
router = APIRouter()

# ── Caches ──────────────────────────────────────────────────────────────────
_cables_cache:         str | None = None
_onc_cables_cache:     str | None = None
_ooi_cables_cache:     str | None = None
_noaa_cables_cache:    str | None = None
_nz_cables_cache:      str | None = None
_au_cables_cache:      str | None = None


def clear_caches() -> None:
    """Drop this domain's cached responses. Called by /admin/cache/clear."""
    global _cables_cache, _onc_cables_cache, _ooi_cables_cache
    global _noaa_cables_cache, _nz_cables_cache, _au_cables_cache
    _cables_cache = None
    _onc_cables_cache = None
    _ooi_cables_cache = None
    _noaa_cables_cache = None
    _nz_cables_cache = None
    _au_cables_cache = None


async def sync_submarine_cables(force: bool = False) -> int:
    """Sync EMODnet submarine cables — every published layer, into submarine_cables.

    The layer list lives in `emodnet_cables_ingest.LAYERS` and is not repeated
    here: this docstring said "7 layers … sigcables (Spain/Atlantic) … ~1,260
    features" while EMODnet published 11, and sigcables is French. A list
    written twice is a list that disagrees with itself. CC-BY 4.0.

    Cadence: weekly (7-day guard). Pass force=True to bypass for admin sync.

    Per-layer fetch failure does NOT abort: missing layer yields 0 features,
    others continue. Only TRUNCATE+INSERT if at least 1 layer succeeded.
    """
    from ingestion.emodnet_cables_ingest import (
        LAYERS,
        fetch_all_layers,
        coords_to_geojson_multilinestring,
    )

    async with db.pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = 'submarine_cables'"
        )
        if not force and last and (datetime.now(tz=timezone.utc) - last).days < 7:
            log.info("submarine_cables: skipping — synced %s", last.date())
            return 0

    rows: list[tuple] = []
    per_layer_counts: dict[str, int] = {}
    async for layer, normalized in fetch_all_layers():
        per_layer_counts[layer] = len(normalized)
        for f in normalized:
            try:
                geom_gj = coords_to_geojson_multilinestring(f["coordinates"])
            except (KeyError, TypeError) as exc:
                log.debug("submarine_cables[%s]: skipping bad geom — %s", layer, exc)
                continue
            rows.append((
                f["source_layer"], f["source_id"],
                f["name"], f["operator"], f["cable_type"],
                f["voltage_kv"], f["inst_year"], f["status"],
                f["location"],
                json.dumps(geom_gj),
            ))

    # Require all but one layer to have succeeded before TRUNCATE+insert.
    # A single transient EMODnet layer outage is acceptable. Anything worse —
    # preserve existing data, log warning, let the next scheduled run retry.
    #
    # ⛔ DERIVED from the layer list, never typed. This was `required = 6`
    # beside a note asking whoever changed the count to revisit it. The count
    # went from 7 to 11 on 2026-09-15, and six of eleven would have been enough
    # to TRUNCATE the table and re-fill it with 45% of the cables. A TRUNCATE
    # does not come back, and the sync would have reported success.
    succeeded_layers = sum(1 for c in per_layer_counts.values() if c > 0)
    required = max(1, len(LAYERS) - 1)
    if succeeded_layers < required:
        log.warning(
            "submarine_cables: only %d/%d layers succeeded (per-layer: %s) — "
            "aborting TRUNCATE to preserve existing data; will retry on next sync",
            succeeded_layers, len(per_layer_counts), per_layer_counts,
        )
        return 0

    if not rows:
        log.warning("submarine_cables: all %d layers returned 0 — aborting without TRUNCATE",
                    len(LAYERS))
        return 0

    inserted = 0
    async with db.pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE submarine_cables")
        for row in rows:
            try:
                await conn.execute(
                    """INSERT INTO submarine_cables
                           (source_layer, source_id, name, operator, cable_type,
                            voltage_kv, inst_year, status, location, geom)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9,
                               ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON($10), 4326)))
                       ON CONFLICT (source_layer, source_id) DO NOTHING""",
                    *row,
                )
                inserted += 1
            except Exception as e:
                log.warning("submarine_cables[%s]: insert failed sid=%s: %s",
                            row[0], row[1], e)
        total = await conn.fetchval("SELECT COUNT(*) FROM submarine_cables")

    global _cables_cache
    _cables_cache = None
    await _log_sync("submarine_cables", inserted, int(total or 0))
    log.info("submarine_cables: %d inserted, %d total | per-layer: %s",
             inserted, int(total or 0), per_layer_counts)
    return inserted


_ONC_CABLES_WFS = (
    "https://dservices2.arcgis.com/qRqOFxxnwUHOSocZ/arcgis/services/ONC_Cables/WFSServer"
    "?service=WFS&version=2.0.0&request=GetFeature&typeNames=ONC_Cables:ONC_Cables"
    "&outputFormat=GEOJSON"
)


async def sync_onc_cables() -> int:
    """Fetch ONC NEPTUNE/VENUS cable geometries from ArcGIS WFS."""
    async with db.pool.acquire() as conn:
        last = await conn.fetchval("SELECT last_synced_at FROM sync_log WHERE source = 'onc_cables'")
        if last and (datetime.now(tz=timezone.utc) - last).days < 30:
            log.info("onc_cables: skipping — synced %s", last.date())
            return 0

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(_ONC_CABLES_WFS)
            r.raise_for_status()
            fc = r.json()
    except Exception as exc:
        log.warning("onc_cables: fetch failed — %s", exc)
        return 0

    features = fc.get("features") or []
    if not features:
        log.warning("onc_cables: no features returned")
        return 0

    inserted = 0
    async with db.pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE onc_cables")
        for f in features:
            props = f.get("properties") or {}
            geom = f.get("geometry")
            if not geom:
                continue
            try:
                length = props.get("Length_metres")
                await conn.execute(
                    """INSERT INTO onc_cables (ext_id, status, length_m, comments, geom)
                       VALUES ($1, $2, $3, $4, ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON($5), 4326)))""",
                    str(props.get("ExtensionID")) if props.get("ExtensionID") is not None else None,
                    props.get("Status"),
                    float(length) if length is not None else None,
                    props.get("Comments"),
                    json.dumps(geom),
                )
                inserted += 1
            except Exception as e:
                log.warning("onc_cables: insert failed: %s", e)
        total = await conn.fetchval("SELECT COUNT(*) FROM onc_cables")
    global _onc_cables_cache
    _onc_cables_cache = None
    await _log_sync("onc_cables", inserted, total)
    log.info("onc_cables: %d features, %d total", inserted, total)
    return inserted


# ── OOI Regional Cabled Array ─────────────────────────────────────────────────
# No public cable-route shapefile exists; OOI's own map is a static JPG.
# We build approximate straight-line polylines from authoritative Primary Node
# coordinates fetched from the OOI asset-management GitHub repo (RS*/CE* CSVs).
# Segments between nodes are NOT bathymetry-routed — the legend says so.

_OOI_SHORE_STATION = (-123.9719, 45.2025)  # Pacific City, OR landfall

# Reference-Designator prefix → (node_id, human label, raw URL)
_OOI_NODE_CSVS = {
    "RS01SLBS": ("PN1A", "Slope Base",
                 "https://raw.githubusercontent.com/oceanobservatories/asset-management/master/deployment/RS01SLBS_Deploy.csv"),
    "RS01SUM1": ("PN1B", "Southern Hydrate Ridge",
                 "https://raw.githubusercontent.com/oceanobservatories/asset-management/master/deployment/RS01SUM1_Deploy.csv"),
    "CE04OSBP": ("PN1C", "Endurance Oregon Offshore",
                 "https://raw.githubusercontent.com/oceanobservatories/asset-management/master/deployment/CE04OSBP_Deploy.csv"),
    "CE02SHBP": ("PN1D", "Endurance Oregon Shelf",
                 "https://raw.githubusercontent.com/oceanobservatories/asset-management/master/deployment/CE02SHBP_Deploy.csv"),
    "RS03AXBS": ("PN3A", "Axial Base",
                 "https://raw.githubusercontent.com/oceanobservatories/asset-management/master/deployment/RS03AXBS_Deploy.csv"),
    "RS03ECAL": ("PN3B", "Axial East Caldera (Summit)",
                 "https://raw.githubusercontent.com/oceanobservatories/asset-management/master/deployment/RS03ECAL_Deploy.csv"),
}

# Two backbone cables as ordered sequences of node keys.
# Northern line: shore → Axial Base → Axial Summit
# Southern line: shore → Slope Base → S. Hydrate → OR Offshore → OR Shelf
_OOI_LINES = [
    ("northern", "OOI RCA Northern Line (Pacific City → Axial Seamount)",
     ["RS03AXBS", "RS03ECAL"]),
    ("southern", "OOI RCA Southern Line (Pacific City → Newport loop)",
     ["RS01SLBS", "RS01SUM1", "CE04OSBP", "CE02SHBP"]),
]


async def sync_ooi_cables() -> int:
    """Build OOI Regional Cabled Array approximate cable routes from node coordinates.

    Fetches authoritative Primary Node positions from the OOI asset-management
    GitHub repo and constructs straight-line MultiLineString polylines matching
    the published RCA topology (northern + southern backbone lines).

    Route geometry is approximate — segments connect published node coordinates
    with straight lines; actual cable follows bathymetry-driven laydown paths
    that OOI does not publish in machine-readable form.
    """
    async with db.pool.acquire() as conn:
        last = await conn.fetchval("SELECT last_synced_at FROM sync_log WHERE source = 'ooi_cables'")
        if last and (datetime.now(tz=timezone.utc) - last).days < 90:
            log.info("ooi_cables: skipping — synced %s", last.date())
            return 0

    # Fetch mean lat/lon and mean water_depth per node from GitHub CSVs
    import csv as _csv
    import io as _io
    node_coords: dict[str, tuple[float, float]] = {}
    node_depths: dict[str, int] = {}
    async with httpx.AsyncClient(timeout=30) as client:
        for ref_des, (node_id, label, url) in _OOI_NODE_CSVS.items():
            try:
                r = await client.get(url)
                r.raise_for_status()
                rows = list(_csv.DictReader(_io.StringIO(r.text)))
                lats = [float(row["lat"]) for row in rows if row.get("lat")]
                lons = [float(row["lon"]) for row in rows if row.get("lon")]
                depths = [float(row["water_depth"]) for row in rows if row.get("water_depth", "").strip()]
                if lats and lons:
                    node_coords[ref_des] = (sum(lons) / len(lons), sum(lats) / len(lats))
                    log.debug("ooi_cables: %s (%s) → %.4f, %.4f", node_id, label,
                              node_coords[ref_des][1], node_coords[ref_des][0])
                if depths:
                    node_depths[ref_des] = round(sum(depths) / len(depths))
            except Exception as exc:
                log.warning("ooi_cables: failed to fetch %s — %s", ref_des, exc)

    if not node_coords:
        log.warning("ooi_cables: no node coordinates fetched")
        return 0

    inserted = 0
    async with db.pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE ooi_cables")
        from math import radians, sin, cos, sqrt, atan2
        def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
            R = 6371000.0
            lat1, lat2 = radians(a[1]), radians(b[1])
            dlat, dlon = radians(b[1] - a[1]), radians(b[0] - a[0])
            h = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
            return 2 * R * atan2(sqrt(h), sqrt(1 - h))

        for line_key, line_label, node_keys in _OOI_LINES:
            # Build coordinate sequence: shore station + each node in order
            present_keys = [k for k in node_keys if k in node_coords]
            coords = [_OOI_SHORE_STATION] + [node_coords[k] for k in present_keys]
            if len(coords) < 2:
                log.warning("ooi_cables: skipping %s — insufficient node coords", line_key)
                continue
            total_m = sum(_haversine(coords[i], coords[i+1]) for i in range(len(coords) - 1))
            # Depth stats from node water_depth values
            line_depths = [node_depths[k] for k in present_keys if k in node_depths]
            deepest   = max(line_depths) if line_depths else None
            shallowest = min(line_depths) if line_depths else None
            # Encode as WKT MultiLineString from a single contiguous LineString
            pts = ", ".join(f"{lon} {lat}" for lon, lat in coords)
            wkt = f"MULTILINESTRING(({pts}))"
            try:
                await conn.execute(
                    """INSERT INTO ooi_cables
                           (ext_id, line_name, length_m, node_count,
                            deepest_node_m, shallowest_node_m, comments, geom)
                       VALUES ($1, $2, $3, $4, $5, $6, $7,
                               ST_Multi(ST_SetSRID(ST_GeomFromText($8), 4326)))""",
                    line_key, line_label, round(total_m), len(present_keys),
                    deepest, shallowest,
                    "Approximate route — straight-line between authoritative Primary Node coordinates. "
                    "Actual cable follows bathymetry-driven path not published in machine-readable form. "
                    "Source: oceanobservatories/asset-management on GitHub.",
                    wkt,
                )
                inserted += 1
            except Exception as e:
                log.warning("ooi_cables: insert failed for %s: %s", line_key, e)

        total = await conn.fetchval("SELECT COUNT(*) FROM ooi_cables")
    global _ooi_cables_cache
    _ooi_cables_cache = None
    await _log_sync("ooi_cables", inserted, int(total or 0))
    log.info("ooi_cables: %d lines inserted, %d total", inserted, int(total or 0))
    return inserted


async def sync_noaa_cables(force: bool = False) -> int:
    """Sync NOAA Marine Cadastre Submarine Cables (US cable corridors).

    Source: https://coast.noaa.gov/arcgis/rest/services/Hosted/SubmarineCables/FeatureServer/0
    Joint NOAA Office of Coast Survey + BOEM portal. ~2,816 cable corridors
    with cable system, owner, status, and region attributes. US federal
    government work — public domain. Cadence: quarterly (90-day guard;
    pass force=True to bypass for admin force-sync).

    Geometry stored as MultiPolygon — these are corridors (legally-protected
    anchoring-prohibited zones), not centerlines. Rendered as outlines in
    the frontend to show corridor footprint honestly.
    """
    from ingestion.noaa_cables_ingest import fetch_noaa_cables_pages, rings_to_geojson_polygon

    async with db.pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = 'noaa_cables'"
        )
        if not force and last and (datetime.now(tz=timezone.utc) - last).days < 90:
            log.info("noaa_cables: skipping — synced %s", last.date())
            return 0

    inserted = 0
    skipped_geom = 0
    fetched_total = 0
    rows: list[tuple] = []
    try:
        async for page in fetch_noaa_cables_pages():
            fetched_total += len(page)
            for f in page:
                try:
                    polygon = rings_to_geojson_polygon(f["rings"])
                except (ValueError, KeyError, TypeError) as exc:
                    skipped_geom += 1
                    log.debug("noaa_cables: skipping feature %s — bad geometry: %s",
                              f.get("object_id"), exc)
                    continue
                rows.append((
                    f["object_id"],
                    f["short_name"],
                    f["cable_system"],
                    f["owner"],
                    f["status"],
                    f["region"],
                    f["shape_length"],
                    json.dumps(polygon),
                ))
    except httpx.HTTPError as exc:
        log.warning("noaa_cables: fetch failed mid-sync, aborting without TRUNCATE — %s", exc)
        return 0

    if not rows:
        log.warning("noaa_cables: no usable features (fetched=%d skipped_geom=%d)",
                    fetched_total, skipped_geom)
        return 0

    async with db.pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE noaa_cables")
        for row in rows:
            try:
                await conn.execute(
                    """INSERT INTO noaa_cables
                           (object_id, short_name, cable_system, owner,
                            status, region, shape_length, geom)
                       VALUES ($1, $2, $3, $4, $5, $6, $7,
                               ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON($8), 4326)))
                       ON CONFLICT (object_id) DO NOTHING""",
                    *row,
                )
                inserted += 1
            except Exception as e:
                log.warning("noaa_cables: insert failed for object_id=%s: %s",
                            row[0], e)

        total = await conn.fetchval("SELECT COUNT(*) FROM noaa_cables")

    global _noaa_cables_cache
    _noaa_cables_cache = None
    await _log_sync("noaa_cables", inserted, int(total or 0))
    log.info("noaa_cables: %d inserted, %d total (fetched=%d skipped_geom=%d)",
             inserted, int(total or 0), fetched_total, skipped_geom)
    return inserted


async def sync_nz_cables(force: bool = False) -> int:
    """Sync NZ LINZ submarine cable polylines (Hydrographic chart-derived).

    Source: data.linz.govt.nz layer 51643. CC-BY 4.0. Requires LINZ_API_KEY.
    Cadence: quarterly (90-day guard); pass force=True to bypass for admin
    force-sync. Polylines are S-57 chart-derived centerlines, not corridors.
    """
    from ingestion.nz_cables_ingest import (
        fetch_nz_cables_features,
        coords_to_geojson_multilinestring,
    )

    async with db.pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = 'nz_cables'"
        )
        if not force and last and (datetime.now(tz=timezone.utc) - last).days < 90:
            log.info("nz_cables: skipping — synced %s", last.date())
            return 0

    inserted = 0
    skipped = 0
    fetched_total = 0
    rows: list[tuple] = []
    async for page in fetch_nz_cables_features():
        fetched_total += len(page)
        for f in page:
            try:
                geom_gj = coords_to_geojson_multilinestring(f["coordinates"])
            except (KeyError, TypeError) as exc:
                skipped += 1
                log.debug("nz_cables: skipping %s — bad geometry: %s", f.get("fidn"), exc)
                continue
            rows.append((
                f["fidn"],
                f["catcbl"],     f["catcbl_raw"],
                f["status"],     f["status_raw"],
                f["condtn"],     f["condtn_raw"],
                f["objnam"],
                f["inform"],
                f["txtdsc"],
                f["burdep"],
                f["datsta"],
                f["datend"],
                json.dumps(geom_gj),
            ))

    if not rows:
        log.warning("nz_cables: no usable features (fetched=%d skipped=%d)",
                    fetched_total, skipped)
        return 0

    async with db.pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE nz_cables")
        for row in rows:
            try:
                await conn.execute(
                    """INSERT INTO nz_cables
                           (fidn, catcbl, catcbl_raw, status, status_raw,
                            condtn, condtn_raw, objnam, inform, txtdsc,
                            burdep, datsta, datend, geom)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                               $11, $12, $13,
                               ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON($14), 4326)))
                       ON CONFLICT (fidn) DO NOTHING""",
                    *row,
                )
                inserted += 1
            except Exception as e:
                log.warning("nz_cables: insert failed fidn=%s: %s", row[0], e)
        total = await conn.fetchval("SELECT COUNT(*) FROM nz_cables")

    global _nz_cables_cache
    _nz_cables_cache = None
    await _log_sync("nz_cables", inserted, int(total or 0))
    log.info("nz_cables: %d inserted, %d total (fetched=%d skipped=%d)",
             inserted, int(total or 0), fetched_total, skipped)
    return inserted


async def sync_au_cables(force: bool = False) -> int:
    """Sync AU AODN submarine cable protection zone polylines.

    Source: CSIRO GeoServer, ACMA-published. CC-BY 4.0. 16 features
    covering Perth + Northern Sydney + Southern Sydney protection zones.
    Cadence: quarterly (90-day guard, force-bypass via admin). Dataset is
    frozen at 2021 so re-syncs rarely produce deltas.
    """
    from ingestion.au_cables_ingest import (
        fetch_au_cables_features,
        coords_to_geojson_multilinestring,
    )

    async with db.pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = 'au_cables'"
        )
        if not force and last and (datetime.now(tz=timezone.utc) - last).days < 90:
            log.info("au_cables: skipping — synced %s", last.date())
            return 0

    inserted = 0
    skipped = 0
    fetched_total = 0
    rows: list[tuple] = []
    async for page in fetch_au_cables_features():
        fetched_total += len(page)
        for f in page:
            try:
                geom_gj = coords_to_geojson_multilinestring(f["coordinates"])
            except (KeyError, TypeError) as exc:
                skipped += 1
                log.debug("au_cables: skipping oid=%s — bad geom: %s",
                          f.get("object_id"), exc)
                continue
            rows.append((
                f["object_id"], f["cable"], f["abbrev"],
                json.dumps(geom_gj),
            ))

    if not rows:
        log.warning("au_cables: no usable features (fetched=%d skipped=%d)",
                    fetched_total, skipped)
        return 0

    async with db.pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE au_cables")
        for row in rows:
            try:
                await conn.execute(
                    """INSERT INTO au_cables (object_id, cable, abbrev, geom)
                       VALUES ($1, $2, $3,
                               ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON($4), 4326)))
                       ON CONFLICT (object_id) DO NOTHING""",
                    *row,
                )
                inserted += 1
            except Exception as e:
                log.warning("au_cables: insert failed oid=%s: %s", row[0], e)
        total = await conn.fetchval("SELECT COUNT(*) FROM au_cables")

    global _au_cables_cache
    _au_cables_cache = None
    await _log_sync("au_cables", inserted, int(total or 0))
    log.info("au_cables: %d inserted, %d total (fetched=%d skipped=%d)",
             inserted, int(total or 0), fetched_total, skipped)
    return inserted


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/v1/map/cables", dependencies=[Depends(get_api_key)])
async def get_cables():
    """Return submarine cable routes as GeoJSON FeatureCollection.

    Geometry simplified server-side via ST_SimplifyPreserveTopology with
    tolerance 0.0005° (~55 m at equator). NVE Norwegian power-cable polylines
    have very high vertex counts (1500+ per feature); simplification cuts
    payload from ~42 MB to ~4-5 MB without visible quality loss at our zoom
    range. Same pattern as the NOAA cables fix.

    length_km computed server-side from the simplified geometry.
    """
    global _cables_cache
    if _cables_cache:
        return Response(content=_cables_cache, media_type="application/json")
    sql = """
        WITH simplified AS (
          SELECT
            ST_SimplifyPreserveTopology(geom, 0.0005) AS geom,
            name, operator, cable_type, voltage_kv, status, inst_year,
            location, source_layer
          FROM submarine_cables
        )
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', coalesce(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(geom)::json,
                    'properties', json_build_object(
                        'name',         name,
                        'operator',     operator,
                        'cable_type',   cable_type,
                        'voltage_kv',   voltage_kv,
                        'status',       status,
                        'inst_year',    inst_year,
                        'length_km',    ROUND((ST_Length(geom::geography) / 1000)::numeric, 1)::float8,
                        'location',     location,
                        'source_layer', source_layer,
                        'source',       'emodnet'
                    )
                )
            ), '[]'::json)
        ) AS geojson
        FROM simplified
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql)
    result = row["geojson"] if isinstance(row["geojson"], str) else json.dumps(row["geojson"])
    _cables_cache = result
    return Response(content=result, media_type="application/json")


@router.get("/v1/map/onc-cables", dependencies=[Depends(get_api_key)])
async def get_onc_cables():
    """Return ONC NEPTUNE/VENUS fibre-optic cable routes as GeoJSON."""
    global _onc_cables_cache
    if _onc_cables_cache:
        return Response(content=_onc_cables_cache, media_type="application/json")
    sql = """
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', coalesce(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(geom)::json,
                    'properties', json_build_object(
                        'ext_id',   ext_id,
                        'status',   status,
                        'length_m', length_m,
                        'comments', comments,
                        'source',   'onc'
                    )
                )
            ), '[]'::json)
        ) AS geojson
        FROM onc_cables
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql)
    result = row["geojson"] if isinstance(row["geojson"], str) else json.dumps(row["geojson"])
    _onc_cables_cache = result
    return Response(content=result, media_type="application/json")


@router.get("/v1/map/ooi-cables", dependencies=[Depends(get_api_key)])
async def get_ooi_cables():
    """Return OOI Regional Cabled Array approximate backbone routes as GeoJSON."""
    global _ooi_cables_cache
    if _ooi_cables_cache:
        return Response(content=_ooi_cables_cache, media_type="application/json")
    sql = """
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', coalesce(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(geom)::json,
                    'properties', json_build_object(
                        'ext_id',           ext_id,
                        'line_name',        line_name,
                        'length_m',         length_m,
                        'node_count',       node_count,
                        'deepest_node_m',   deepest_node_m,
                        'shallowest_node_m',shallowest_node_m,
                        'operator',         'University of Washington APL / NSF OOI',
                        'commissioned',     2015,
                        'comments',         comments,
                        'source',           'ooi'
                    )
                )
            ), '[]'::json)
        ) AS geojson
        FROM ooi_cables
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql)
    result = row["geojson"] if isinstance(row["geojson"], str) else json.dumps(row["geojson"])
    _ooi_cables_cache = result
    return Response(content=result, media_type="application/json")


@router.get("/v1/map/noaa-cables", dependencies=[Depends(get_api_key)])
async def get_noaa_cables():
    """Return NOAA Marine Cadastre US cable corridors as GeoJSON.

    Polygon corridors (not centerlines) — frontend renders as outlines.

    Geometry simplified server-side via ST_SimplifyPreserveTopology with
    tolerance 0.0005° (~55 m at equator) — corridors are 100 m–1 km wide
    legal buffers, so vertex reduction at ~50 m is visually invisible but
    cuts payload + GPU vertex count materially. Topology preservation
    keeps polygon rings closed and non-self-intersecting.
    """
    global _noaa_cables_cache
    if _noaa_cables_cache:
        return Response(content=_noaa_cables_cache, media_type="application/json")
    sql = """
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', coalesce(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.0005))::json,
                    'properties', json_build_object(
                        'object_id',    object_id,
                        'short_name',   short_name,
                        'cable_system', cable_system,
                        'owner',        owner,
                        'status',       status,
                        'region',       region,
                        'shape_length', shape_length,
                        'source',       'noaa'
                    )
                )
            ), '[]'::json)
        ) AS geojson
        FROM noaa_cables
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql)
    result = row["geojson"] if isinstance(row["geojson"], str) else json.dumps(row["geojson"])
    _noaa_cables_cache = result
    return Response(content=result, media_type="application/json")


@router.get("/v1/map/nz-cables", dependencies=[Depends(get_api_key)])
async def get_nz_cables():
    """Return NZ LINZ submarine cable polylines as GeoJSON.

    S-57 chart-derived centerlines from NZ Hydrographic Authority via LINZ.
    Polyline geometry — frontend renders as line strings (not corridors).
    """
    global _nz_cables_cache
    if _nz_cables_cache:
        return Response(content=_nz_cables_cache, media_type="application/json")
    sql = """
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', coalesce(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(geom)::json,
                    'properties', json_build_object(
                        'fidn',       fidn,
                        'catcbl',     catcbl,
                        'catcbl_raw', catcbl_raw,
                        'status',     status,
                        'status_raw', status_raw,
                        'condtn',     condtn,
                        'condtn_raw', condtn_raw,
                        'objnam',     objnam,
                        'inform',     inform,
                        'txtdsc',     txtdsc,
                        'burdep',     burdep,
                        'datsta',     datsta,
                        'datend',     datend,
                        'source',     'nz'
                    )
                )
            ), '[]'::json)
        ) AS geojson
        FROM nz_cables
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql)
    result = row["geojson"] if isinstance(row["geojson"], str) else json.dumps(row["geojson"])
    _nz_cables_cache = result
    return Response(content=result, media_type="application/json")


@router.get("/v1/map/au-cables", dependencies=[Depends(get_api_key)])
async def get_au_cables():
    """Return AU ACMA cable protection zone polylines as GeoJSON.

    16 features across Perth + Northern Sydney + Southern Sydney zones.
    """
    global _au_cables_cache
    if _au_cables_cache:
        return Response(content=_au_cables_cache, media_type="application/json")
    sql = """
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', coalesce(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(geom)::json,
                    'properties', json_build_object(
                        'object_id', object_id,
                        'cable',     cable,
                        'abbrev',    abbrev,
                        'source',    'au'
                    )
                )
            ), '[]'::json)
        ) AS geojson
        FROM au_cables
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(sql)
    result = row["geojson"] if isinstance(row["geojson"], str) else json.dumps(row["geojson"])
    _au_cables_cache = result
    return Response(content=result, media_type="application/json")
