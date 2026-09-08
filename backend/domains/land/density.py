# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Monitoring-density hex grid + DataCite-backed ocean-data syncs (WOD, PANGAEA,
BCO-DMO, NOAA, OBIS-SEAMAP, NCEI/ICOADS, CCHDO) and DeepData sampling-station
endpoints. Split out of land_layers.py — these feed the density grid and are
not land layers despite having lived in that file.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import Response

import db
from auth import get_api_key
from domains.land.common import (
    _log_land_sync,
    _datacite_extract_coords,
    _datacite_paginate,
)

log = logging.getLogger("land_layers")
# No prefix here — land_layers.py's router already carries "/v2/map" and
# mounts this one with `router.include_router(_density.router)`, which
# applies the parent's prefix. A prefix on both would double it.
router = APIRouter(tags=["land-layers"], dependencies=[Depends(get_api_key)])

# ── Module-level caches (cleared on sync) ──────────────────────────────────
_monitoring_density_cache: str | None = None
_deepdata_stations_cache: str | None = None


def clear_caches() -> None:
    """Reset this module's caches. Delegated into from land_layers.clear_caches()
    so the combined 13-cache sweep still clears everything from one call."""
    global _monitoring_density_cache, _deepdata_stations_cache
    _monitoring_density_cache = None
    _deepdata_stations_cache = None


def clear_deepdata_stations_cache() -> None:
    """Targeted invalidation of just the deepdata-stations cache, called from
    domains/biodiversity.py after a sync writes new stations. Deliberately
    does NOT call clear_caches() — that would also drop the unrelated
    monitoring-density cache."""
    global _deepdata_stations_cache
    _deepdata_stations_cache = None



# Display-uniform hex grid (EPSG:3857 — the basemap's own Web-Mercator projection).
# Generating in the *display* projection makes hexagons render as regular hexagons
# at every latitude (no polar shearing) and get progressively smaller in REAL area
# toward the poles — finer resolution where future polar layers will want it.
# Trade-off: NOT equal-area, so a polar cell's count isn't directly comparable to an
# equatorial one (an equatorial cell covers far more km²). Edge is in 3857 metres
# (≈ real metres only at the equator). Single tunable knob — change + rebuild.
_HEX_EDGE_M = 137000.0
# Bump when the cell-geometry build logic changes (forces a one-time rebuild even
# if the edge length is unchanged). v2 = clip-to-domain build (filled antimeridian
# seam + polar rows); v3 = ±72° latitude cap; v4 = switch 6933 equal-area -> 3857
# display-uniform grid so cells aren't stretched near the poles.
_HEX_BUILD_V = 4
# Web-Mercator (EPSG:3857) world half-extent in metres; covers lat ±85.06°.
_MERC_WORLD = 20037508.34

_MONITORING_DENSITY_SQL = """
    CREATE MATERIALIZED VIEW IF NOT EXISTS monitoring_density_grid AS
    WITH pts AS (
        SELECT lon, lat, 'chess'       AS src FROM chess_occurrences
        UNION ALL
        SELECT ST_X(geom) AS lon, ST_Y(geom) AS lat, 'argo' AS src
            FROM argo_profiles WHERE geom IS NOT NULL
        UNION ALL
        SELECT lon, lat, 'oceansites'  AS src FROM oceansites_stations
        UNION ALL
        SELECT ST_X(geom) AS lon, ST_Y(geom) AS lat, 'onc' AS src
            FROM onc_instruments WHERE geom IS NOT NULL
        UNION ALL
        SELECT cell_lon AS lon, cell_lat AS lat, 'obis' AS src
            FROM hotspot_grid WHERE resolution = 'coarse'
        UNION ALL
        SELECT lon, lat, 'wod'         AS src FROM wod_profiles
        UNION ALL
        SELECT lon, lat, 'pangaea'     AS src FROM pangaea_records
        UNION ALL
        SELECT lon, lat, 'bco-dmo'     AS src FROM bco_dmo_datasets
        UNION ALL
        SELECT lon, lat, 'noaa'        AS src FROM noaa_datasets
        UNION ALL
        SELECT lon, lat, 'seamap'      AS src FROM obis_seamap_records
        UNION ALL
        SELECT lon, lat, 'sio_bic'     AS src FROM sio_bic_records
        UNION ALL
        SELECT lon, lat, 'deepdata_isa' AS src FROM deepdata_occurrences
        UNION ALL
        SELECT lon, lat, 'mbari_vars'  AS src FROM mbari_vars_records
        UNION ALL
        SELECT lon, lat, 'noaa_corals' AS src FROM noaa_corals_records
        UNION ALL
        SELECT lon, lat, 'cchdo'       AS src FROM cchdo_stations
    ),
    binned AS (
        SELECT
            h.cell_id,
            COUNT(*)            AS point_count,
            COUNT(DISTINCT p.src) AS source_count
        FROM pts p
        JOIN density_hex_cells h
          ON ST_Contains(h.geom_3857,
                         ST_Transform(ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326), 3857))
        WHERE p.lon >= -180 AND p.lon < 180 AND p.lat >= -85 AND p.lat < 85
        GROUP BY h.cell_id
    )
    SELECT
        h.cell_id,
        ST_X(ST_Centroid(h.geom))::float8 AS centroid_lon,
        ST_Y(ST_Centroid(h.geom))::float8 AS centroid_lat,
        COALESCE(b.point_count, 0)  AS point_count,
        COALESCE(b.source_count, 0) AS source_count,
        h.geom,
        h.geom_3857
    FROM density_hex_cells h
    LEFT JOIN binned b USING (cell_id)
    -- Only emit cells that actually hold monitoring records. Zero-record cells are
    -- left blank (no hex) — areas with no reports read as open water. The 3857
    -- display-uniform build keeps cells unstretched at every latitude.
    WHERE COALESCE(b.point_count, 0) > 0
"""


# NOTE: `ensure_ne_ocean` (Natural Earth 50m ocean polygon) lived here until
# 2026-07-10. It was added 2026-05-22 to set a `density_hex_cells.is_ocean` flag
# so the density grid could tile open water; the very next day, 2026-05-23, the
# grid was reworked onto EPSG:3857 and dropped every read of that flag. The loader survived
# the refactor and spent a year fetching a 720 kB polygon on every fresh-DB boot
# that nothing ever queried. If an ocean mask is wanted again, write it then —
# do not resurrect a loader whose docstring described behaviour that no longer
# existed.


async def ensure_density_hex_cells():
    """Build the display-uniform hex tiling once. Hexagons are generated in
    EPSG:3857 (Web Mercator — the basemap's own projection), so they render as
    regular hexagons at every latitude (no polar shearing) and get progressively
    smaller in REAL area toward the poles (finer resolution for future polar
    layers). Each row has geom_3857 (for point binning) and the 4326 polygon (for
    display). NOT equal-area: a polar cell's count is not directly comparable to an
    equatorial one. Rebuilt when missing, the edge changed, or _HEX_BUILD_V changed."""
    async with db.pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT to_regclass('public.density_hex_cells')"
        )
        up_to_date = False
        if exists:
            current_edge = await conn.fetchval(
                "SELECT edge_m FROM density_hex_cells LIMIT 1"
            )
            has_bv = await conn.fetchval(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'density_hex_cells' AND column_name = 'build_v'"
            )
            current_bv = (
                await conn.fetchval("SELECT build_v FROM density_hex_cells LIMIT 1")
                if has_bv else None
            )
            up_to_date = (current_edge == _HEX_EDGE_M and current_bv == _HEX_BUILD_V)
        if not up_to_date:
            # The rebuild used to run only at startup, before anything was serving.
            # It now runs from migrate.py, pre-restart, while the OLD process is
            # still answering requests. `conn.execute` is autocommit — without an
            # explicit transaction, the DROP commits before the CREATE begins, and
            # every land-density query in that window sees no table at all
            # (UndefinedTableError -> 500 at the edge, the exact outcome this body
            # of work exists to remove). Wrapping drop+create+indexes in one
            # transaction means other sessions still see the OLD table (MVCC) until
            # this commits, then atomically see the NEW one — never neither.
            async with conn.transaction():
                await conn.execute("DROP TABLE IF EXISTS density_hex_cells CASCADE")
                await conn.execute(f"""
                    CREATE TABLE density_hex_cells AS
                    -- Tile the Web-Mercator world square in EPSG:3857, then transform to
                    -- 4326 for display. Clip to the 3857 box first so edge cells don't
                    -- transform out of the projection domain (NaN/Inf). Result: regular
                    -- hexagons on the Mercator basemap at every latitude, finer (smaller
                    -- real area) toward the poles.
                    WITH box AS (
                        SELECT ST_MakeEnvelope(-{_MERC_WORLD}, -{_MERC_WORLD},
                                                {_MERC_WORLD},  {_MERC_WORLD}, 3857) AS g
                    ),
                    hexes AS (
                        SELECT (ST_HexagonGrid({_HEX_EDGE_M}, box.g)).*
                        FROM box
                    ),
                    clipped AS (
                        SELECT h.i, h.j, ST_Intersection(h.geom, box.g) AS geom_3857
                        FROM hexes h, box
                        WHERE ST_Intersects(h.geom, box.g)
                    )
                    SELECT
                        i || ',' || j                 AS cell_id,
                        i, j,
                        {_HEX_EDGE_M}::float8          AS edge_m,
                        {_HEX_BUILD_V}::smallint        AS build_v,
                        geom_3857,
                        ST_Transform(geom_3857, 4326)  AS geom
                    FROM clipped
                    WHERE NOT ST_IsEmpty(geom_3857)
                """)
                await conn.execute(
                    "CREATE UNIQUE INDEX density_hex_cells_pk ON density_hex_cells (cell_id)"
                )
                await conn.execute(
                    "CREATE INDEX density_hex_cells_g3857_gix ON density_hex_cells USING GIST (geom_3857)"
                )
                await conn.execute(
                    "CREATE INDEX density_hex_cells_g4326_gix ON density_hex_cells USING GIST (geom)"
                )
            log.info("density_hex_cells built (edge=%s m 3857, build_v=%s)", _HEX_EDGE_M, _HEX_BUILD_V)


async def ensure_density_source_indexes():
    """Composite (lon,lat) b-tree indexes so the hex bbox pre-filter is index-
    served on the large source tables. Idempotent; cheap no-op once present."""
    stmts = [
        "CREATE INDEX IF NOT EXISTS noaa_corals_records_lonlat_idx ON noaa_corals_records (lon, lat)",
        "CREATE INDEX IF NOT EXISTS deepdata_occurrences_lonlat_idx ON deepdata_occurrences (lon, lat)",
        "CREATE INDEX IF NOT EXISTS mbari_vars_records_lonlat_idx ON mbari_vars_records (lon, lat)",
        "CREATE INDEX IF NOT EXISTS wod_profiles_lonlat_idx ON wod_profiles (lon, lat)",
        "CREATE INDEX IF NOT EXISTS obis_seamap_records_lonlat_idx ON obis_seamap_records (lon, lat)",
    ]
    async with db.pool.acquire() as conn:
        for s in stmts:
            await conn.execute(s)
    log.info("density source (lon,lat) indexes ensured")


async def ensure_monitoring_density_matview():
    """Create (or migrate) the monitoring_density_grid materialized view.
    Rebuilds when the definition changed (e.g. switched to hex binning) or a
    new source was added. Requires density_hex_cells to exist first."""
    async with db.pool.acquire() as conn:
        exists = await conn.fetchval("""
            SELECT 1 FROM pg_matviews WHERE matviewname = 'monitoring_density_grid'
        """)
        needs_rebuild = False
        if exists:
            stale = await conn.fetchval("""
                SELECT definition ~ 'ST_MakeEnvelope'
                    OR definition !~ 'density_hex_cells'
                    OR definition !~ 'noaa_corals_records'
                    OR definition ~ 'geom_6933'   -- old 6933 equal-area version: rebuild to 3857
                FROM pg_matviews WHERE matviewname = 'monitoring_density_grid'
            """)
            needs_rebuild = bool(stale)
        if needs_rebuild:
            await conn.execute("DROP MATERIALIZED VIEW IF EXISTS monitoring_density_grid")
            await conn.execute("DROP INDEX IF EXISTS monitoring_density_grid_geom_idx")
        await conn.execute(_MONITORING_DENSITY_SQL)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS monitoring_density_grid_geom_idx
            ON monitoring_density_grid USING GIST (geom)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS monitoring_density_grid_g3857_idx
            ON monitoring_density_grid USING GIST (geom_3857)
        """)
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS monitoring_density_grid_cell_id_idx
            ON monitoring_density_grid (cell_id)
        """)
    log.info("monitoring_density_grid materialized view ensured")


async def refresh_monitoring_density():
    """Refresh the monitoring_density_grid matview and clear the endpoint cache.
    CONCURRENTLY avoids a full read lock — requires the unique cell_id index."""
    global _monitoring_density_cache
    async with db.pool.acquire() as conn:
        await conn.execute("SET statement_timeout = '10min'")
        await conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY monitoring_density_grid")
    _monitoring_density_cache = None
    log.info("monitoring_density_grid refreshed")

# ── DeepData sampling stations (TIER 2 analytics layer) ────────────────────
# This layer surfaces platform-derived aggregations of contractor DwC archives.
# Tier 1 raw mirror lives in `deepdata_occurrences` (untouched). The panel UI
# always badges these rows as "platform-derived analysis".


@router.get("/deepdata-stations")
async def get_deepdata_stations():
    """GeoJSON FeatureCollection of all platform-derived DeepData sampling
    stations. ~5–10k Point features, color-keyed in the frontend by
    `contractor_code`."""
    global _deepdata_stations_cache
    if _deepdata_stations_cache:
        return Response(content=_deepdata_stations_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        row = await conn.fetchval("""
            SELECT json_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(json_agg(
                    json_build_object(
                        'type', 'Feature',
                        'geometry', json_build_object(
                            'type', 'Point',
                            'coordinates', json_build_array(lon, lat)
                        ),
                        'properties', json_build_object(
                            'station_id',        station_id,
                            'archive_slug',      archive_slug,
                            'contractor_code',   contractor_code,
                            'occurrence_count',  occurrence_count,
                            'species_count',     species_count,
                            'sampling_protocol', sampling_protocol,
                            'event_id_raw',      event_id_raw,
                            'location_id',       location_id,
                            'depth_m_min',       depth_m_min,
                            'depth_m_max',       depth_m_max,
                            'first_event_date',  first_event_date,
                            'last_event_date',   last_event_date,
                            'top_species',       top_species,
                            'top_phyla',         top_phyla,
                            'sediment_horizons', sediment_horizons
                        )
                    )
                ), '[]'::json)
            )::text
            FROM deepdata_stations
        """)
    _deepdata_stations_cache = row
    return Response(content=row, media_type="application/json")


@router.get("/deepdata-stations/by-id/{station_id}")
async def get_deepdata_station_detail(station_id: str):
    """Full detail for one station including the parent archive's verbatim
    citation and license. Used by the click-target detail panel."""
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
                s.station_id, s.archive_slug, s.contractor_code,
                s.event_id_raw, s.location_id, s.sampling_protocol,
                s.lat, s.lon, s.depth_m_min, s.depth_m_max, s.coord_uncertainty_m,
                s.first_event_date, s.last_event_date,
                s.occurrence_count, s.species_count,
                s.top_species, s.top_phyla, s.sediment_horizons,
                s.derived_at,
                a.title          AS archive_title,
                a.citation       AS archive_citation,
                a.license        AS archive_license,
                a.rights_holder  AS archive_rights_holder,
                a.pub_date       AS archive_pub_date
            FROM deepdata_stations s
            JOIN deepdata_dwc_archives a ON a.slug = s.archive_slug
            WHERE s.station_id = $1
        """, station_id)
    if not row:
        return Response(content='{"error":"not found"}', status_code=404,
                        media_type="application/json")
    return dict(row)

@router.get("/monitoring-density")
async def get_monitoring_density():
    """Return baseline monitoring density as a display-uniform hex grid (EPSG:3857)
    GeoJSON. Dark cells = few monitoring records. Hexagons render as regular hexagons
    at every latitude (no polar shearing) and are finer (smaller real area) toward
    the poles. NOT equal-area: counts are not directly comparable across latitudes."""
    global _monitoring_density_cache
    if _monitoring_density_cache:
        return Response(content=_monitoring_density_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        row = await conn.fetchval("""
            SELECT json_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(json_agg(
                    json_build_object(
                        'type', 'Feature',
                        'geometry', ST_AsGeoJSON(ST_ForcePolygonCCW(geom))::json,
                        'properties', json_build_object(
                            'cell_id', cell_id,
                            'centroid_lon', centroid_lon,
                            'centroid_lat', centroid_lat,
                            'cell_lon', centroid_lon,
                            'cell_lat', centroid_lat,
                            'point_count', point_count,
                            'source_count', source_count
                        )
                    )
                ), '[]'::json)
            )::text
            FROM monitoring_density_grid
        """)
    _monitoring_density_cache = row
    return Response(content=row, media_type="application/json")


_CELL_SAMPLE_LIMIT = 5


async def _lookup_cell(conn, lon: float, lat: float):
    """Find the hex cell containing a clicked point. Returns a dict with the
    cell_id, the 4326 polygon (as WKB), and its lon/lat bbox (index-friendly
    pre-filter), plus centroid, or None if the click is outside any cell."""
    row = await conn.fetchrow("""
        SELECT cell_id,
               ST_AsBinary(geom)            AS geom_wkb,
               ST_XMin(geom) AS minlon, ST_XMax(geom) AS maxlon,
               ST_YMin(geom) AS minlat, ST_YMax(geom) AS maxlat,
               centroid_lon, centroid_lat
        FROM monitoring_density_grid
        WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326))
        LIMIT 1
    """, lon, lat)
    return dict(row) if row else None


async def _cell_samples(src: str, cell: dict) -> list[dict]:
    """Fetch up to _CELL_SAMPLE_LIMIT sample records from one source table for a
    cell. Acquires its own connection so callers can fan out via asyncio.gather."""
    async with db.pool.acquire() as conn:
        return await _cell_samples_impl(conn, src, cell, _CELL_SAMPLE_LIMIT)


async def _cell_samples_impl(conn, src: str, cell: dict, limit: int = _CELL_SAMPLE_LIMIT) -> list[dict]:
    # Shared membership args: bbox pre-filter (index-friendly) + exact hex test.
    # Param order in every query below: $1 minlon $2 maxlon $3 minlat $4 maxlat $5 geom_wkb $6 limit
    bb = (cell["minlon"], cell["maxlon"], cell["minlat"], cell["maxlat"], cell["geom_wkb"])
    if src == "pangaea":
        rows = await conn.fetch("""
            SELECT pangaea_id AS id, title, year
            FROM pangaea_records
            WHERE lon BETWEEN $1 AND $2 AND lat BETWEEN $3 AND $4
              AND ST_Contains(ST_GeomFromWKB($5, 4326), ST_SetSRID(ST_MakePoint(lon, lat), 4326))
            ORDER BY year DESC NULLS LAST LIMIT $6
        """, *bb, limit)
        return [{"id": r["id"], "title": r["title"] or "", "year": r["year"]} for r in rows]
    if src == "bco-dmo":
        rows = await conn.fetch("""
            SELECT doi AS id, title, year
            FROM bco_dmo_datasets
            WHERE lon BETWEEN $1 AND $2 AND lat BETWEEN $3 AND $4
              AND ST_Contains(ST_GeomFromWKB($5, 4326), ST_SetSRID(ST_MakePoint(lon, lat), 4326))
            ORDER BY year DESC NULLS LAST LIMIT $6
        """, *bb, limit)
        return [{"id": r["id"], "title": r["title"] or "", "year": r["year"]} for r in rows]
    if src == "noaa":
        rows = await conn.fetch("""
            SELECT doi AS id, title, year
            FROM noaa_datasets
            WHERE lon BETWEEN $1 AND $2 AND lat BETWEEN $3 AND $4
              AND ST_Contains(ST_GeomFromWKB($5, 4326), ST_SetSRID(ST_MakePoint(lon, lat), 4326))
            ORDER BY year DESC NULLS LAST LIMIT $6
        """, *bb, limit)
        return [{"id": r["id"], "title": r["title"] or "", "year": r["year"]} for r in rows]
    if src == "wod":
        rows = await conn.fetch("""
            SELECT CONCAT(COALESCE(dataset,''), ' ', COALESCE(region,'')) AS id,
                   CONCAT(COALESCE(dataset,'WOD'), ' — ', COALESCE(region,'')) AS title,
                   year
            FROM wod_profiles
            WHERE lon BETWEEN $1 AND $2 AND lat BETWEEN $3 AND $4
              AND ST_Contains(ST_GeomFromWKB($5, 4326), ST_SetSRID(ST_MakePoint(lon, lat), 4326))
            ORDER BY year DESC NULLS LAST LIMIT $6
        """, *bb, limit)
        return [{"id": r["id"], "title": r["title"] or "", "year": r["year"]} for r in rows]
    if src == "onc":
        rows = await conn.fetch("""
            SELECT device_code AS id,
                   CONCAT(COALESCE(device_name,''), ' @ ', COALESCE(site_name,'')) AS title,
                   NULL::int AS year
            FROM onc_instruments
            WHERE ST_X(geom) BETWEEN $1 AND $2 AND ST_Y(geom) BETWEEN $3 AND $4
              AND geom IS NOT NULL
              AND ST_Contains(ST_GeomFromWKB($5, 4326), geom)
            LIMIT $6
        """, *bb, limit)
        return [{"id": r["id"], "title": r["title"] or "", "year": r["year"]} for r in rows]
    if src == "oceansites":
        rows = await conn.fetch("""
            SELECT ref AS id,
                   CONCAT(name, CASE WHEN network <> '' THEN ' (' || network || ')' ELSE '' END) AS title,
                   NULL::int AS year
            FROM oceansites_stations
            WHERE lon BETWEEN $1 AND $2 AND lat BETWEEN $3 AND $4
              AND ST_Contains(ST_GeomFromWKB($5, 4326), ST_SetSRID(ST_MakePoint(lon, lat), 4326))
            LIMIT $6
        """, *bb, limit)
        return [{"id": r["id"], "title": r["title"] or "", "year": r["year"]} for r in rows]
    if src == "chess":
        rows = await conn.fetch("""
            SELECT occurrence_id AS id,
                   CONCAT(COALESCE(species,''), CASE WHEN locality <> '' THEN ' — ' || locality ELSE '' END) AS title,
                   NULL::int AS year
            FROM chess_occurrences
            WHERE lon BETWEEN $1 AND $2 AND lat BETWEEN $3 AND $4
              AND ST_Contains(ST_GeomFromWKB($5, 4326), ST_SetSRID(ST_MakePoint(lon, lat), 4326))
            LIMIT $6
        """, *bb, limit)
        # date_precision "none" is a FINDING, not a shrug, and it is why the NULL year
        # above needs no apology. ChEssBase on GBIF carries no sample date at all —
        # verified 2026-09-08 against the live API four ways: the 70-field record has no
        # temporal key; GBIF's own facet=year over all 3,715 records comes back empty; an
        # eventDate range query returns 0; and the /verbatim endpoint has no date field
        # either, so it is not an interpretation failure at GBIF's end.
        #
        # ⛔ Do not "fix" this by re-fetching — there is nothing upstream to fetch. Sending
        # "none" makes the panel say "no date at source"; leaving it absent made the panel
        # render blank, which reads as "not loaded yet". Those are different claims and the
        # data-passthrough rule exists to keep them apart.
        return [{"id": r["id"], "title": r["title"] or "", "year": r["year"],
                 "date_precision": "none"} for r in rows]
    if src == "argo":
        rows = await conn.fetch("""
            SELECT profile_id AS id,
                   CONCAT('Float ', platform_id,
                          CASE WHEN max_depth_m IS NOT NULL THEN ' · ' || max_depth_m::int || ' m' ELSE '' END) AS title,
                   EXTRACT(year FROM profile_date)::int AS year
            FROM argo_profiles
            WHERE ST_X(geom) BETWEEN $1 AND $2 AND ST_Y(geom) BETWEEN $3 AND $4
              AND geom IS NOT NULL
              AND ST_Contains(ST_GeomFromWKB($5, 4326), geom)
            ORDER BY profile_date DESC NULLS LAST LIMIT $6
        """, *bb, limit)
        return [{"id": r["id"], "title": r["title"] or "", "year": r["year"]} for r in rows]
    if src == "sio_bic":
        rows = await conn.fetch("""
            SELECT catalog_no AS id,
                   CONCAT(COALESCE(genus, ''), ' ', COALESCE(species, ''),
                          CASE WHEN locality IS NOT NULL AND locality <> ''
                               THEN ' — ' || locality ELSE '' END) AS title,
                   EXTRACT(year FROM collection_date)::int AS year
            FROM sio_bic_records
            WHERE lon BETWEEN $1 AND $2 AND lat BETWEEN $3 AND $4
              AND ST_Contains(ST_GeomFromWKB($5, 4326), ST_SetSRID(ST_MakePoint(lon, lat), 4326))
            ORDER BY collection_date DESC NULLS LAST LIMIT $6
        """, *bb, limit)
        return [{"id": r["id"], "title": r["title"] or "", "year": r["year"]} for r in rows]
    if src == "deepdata_isa":
        rows = await conn.fetch("""
            SELECT obis_id::text AS id,
                   CONCAT(
                       COALESCE(NULLIF(scientific_name, ''), 'Specimen'),
                       CASE WHEN contractor_code IS NOT NULL
                            THEN ' — ' || contractor_code ELSE '' END,
                       CASE WHEN rights_holder IS NOT NULL AND rights_holder <> ''
                            THEN ' (' || rights_holder || ')' ELSE '' END
                   ) AS title,
                   EXTRACT(year FROM event_date)::int AS year
            FROM deepdata_occurrences
            WHERE lon BETWEEN $1 AND $2 AND lat BETWEEN $3 AND $4
              AND ST_Contains(ST_GeomFromWKB($5, 4326), ST_SetSRID(ST_MakePoint(lon, lat), 4326))
            ORDER BY event_date DESC NULLS LAST LIMIT $6
        """, *bb, limit)
        return [{"id": r["id"], "title": r["title"] or "", "year": r["year"]} for r in rows]
    if src == "mbari_vars":
        rows = await conn.fetch("""
            SELECT obis_id::text AS id,
                   CONCAT(
                       COALESCE(NULLIF(scientific_name, ''), 'MBARI specimen'),
                       CASE WHEN locality IS NOT NULL AND locality <> ''
                            THEN ' — ' || locality ELSE '' END
                   ) AS title,
                   EXTRACT(year FROM event_date)::int AS year
            FROM mbari_vars_records
            WHERE lon BETWEEN $1 AND $2 AND lat BETWEEN $3 AND $4
              AND ST_Contains(ST_GeomFromWKB($5, 4326), ST_SetSRID(ST_MakePoint(lon, lat), 4326))
            ORDER BY event_date DESC NULLS LAST LIMIT $6
        """, *bb, limit)
        return [{"id": r["id"], "title": r["title"] or "", "year": r["year"]} for r in rows]
    if src == "noaa_corals":
        rows = await conn.fetch("""
            SELECT catalog_number AS id,
                   CONCAT(
                       COALESCE(NULLIF(scientific_name, ''), 'Coral/sponge specimen'),
                       CASE WHEN locality IS NOT NULL AND locality <> ''
                            THEN ' — ' || locality ELSE '' END
                   ) AS title,
                   COALESCE(observation_year, EXTRACT(year FROM event_date)::int) AS year
            FROM noaa_corals_records
            WHERE lon BETWEEN $1 AND $2 AND lat BETWEEN $3 AND $4
              AND ST_Contains(ST_GeomFromWKB($5, 4326), ST_SetSRID(ST_MakePoint(lon, lat), 4326))
            ORDER BY event_date DESC NULLS LAST LIMIT $6
        """, *bb, limit)
        return [{"id": r["id"], "title": r["title"] or "", "year": r["year"]} for r in rows]
    if src == "cchdo":
        rows = await conn.fetch("""
            SELECT DISTINCT ON (expocode) expocode AS id,
                   CONCAT(COALESCE(ship, 'R/V'),
                          CASE WHEN woce_line <> '' AND woce_line IS NOT NULL
                               THEN ' · ' || woce_line ELSE '' END,
                          CASE WHEN country IS NOT NULL
                               THEN ' (' || country || ')' ELSE '' END) AS title,
                   year, campaign_start, campaign_end, date_precision
            FROM cchdo_stations
            WHERE lon BETWEEN $1 AND $2 AND lat BETWEEN $3 AND $4
              AND ST_Contains(ST_GeomFromWKB($5, 4326), ST_SetSRID(ST_MakePoint(lon, lat), 4326))
            ORDER BY expocode, year DESC NULLS LAST LIMIT $6
        """, *bb, limit)
        # A row here is a vertex of the cruise track, not a station, so the cruise
        # WINDOW is the whole of what the source dated — see _cchdo_cruise_dates().
        # date_precision is NULL only on rows the backfill has not reached yet; those
        # keep the old bare-year rendering rather than claiming a window we do not have.
        return [{"id": r["id"], "title": r["title"] or "", "year": r["year"],
                 "date_precision": r["date_precision"],
                 "campaign_start": r["campaign_start"].isoformat() if r["campaign_start"] else None,
                 "campaign_end":   r["campaign_end"].isoformat()   if r["campaign_end"]   else None}
                for r in rows]
    # obis (hotspot_grid) and seamap have no per-record titles
    return []


@router.get("/monitoring-density/cell")
async def get_monitoring_density_cell(lon: float, lat: float):
    """Per-source breakdown + sample records for the hex cell containing (lon,lat)."""
    async with db.pool.acquire() as conn:
        cell = await _lookup_cell(conn, lon, lat)
        if cell is None:
            return {"cell_id": None, "centroid_lon": lon, "centroid_lat": lat,
                    "cell_lon": lon, "cell_lat": lat, "sources": [], "total": 0}
        bb = (cell["minlon"], cell["maxlon"], cell["minlat"], cell["maxlat"], cell["geom_wkb"])
        count_rows = await conn.fetch("""
            WITH cell AS (SELECT ST_GeomFromWKB($5, 4326) AS g)
            SELECT src, COUNT(*)::int AS cnt FROM (
                SELECT lon, lat, 'chess'        AS src FROM chess_occurrences
                UNION ALL SELECT ST_X(geom), ST_Y(geom), 'argo'        FROM argo_profiles WHERE geom IS NOT NULL
                UNION ALL SELECT lon, lat,             'oceansites'  FROM oceansites_stations
                UNION ALL SELECT ST_X(geom), ST_Y(geom), 'onc'         FROM onc_instruments WHERE geom IS NOT NULL
                UNION ALL SELECT cell_lon, cell_lat,    'obis'        FROM hotspot_grid WHERE resolution = 'coarse'
                UNION ALL SELECT lon, lat,             'wod'         FROM wod_profiles
                UNION ALL SELECT lon, lat,             'pangaea'     FROM pangaea_records
                UNION ALL SELECT lon, lat,             'bco-dmo'     FROM bco_dmo_datasets
                UNION ALL SELECT lon, lat,             'noaa'        FROM noaa_datasets
                UNION ALL SELECT lon, lat,             'seamap'      FROM obis_seamap_records
                UNION ALL SELECT lon, lat,             'sio_bic'     FROM sio_bic_records
                UNION ALL SELECT lon, lat,             'deepdata_isa' FROM deepdata_occurrences
                UNION ALL SELECT lon, lat,             'mbari_vars'  FROM mbari_vars_records
                UNION ALL SELECT lon, lat,             'noaa_corals' FROM noaa_corals_records
                UNION ALL SELECT lon, lat,             'cchdo'       FROM cchdo_stations
            ) pts(lon, lat, src), cell
            WHERE pts.lon BETWEEN $1 AND $2 AND pts.lat BETWEEN $3 AND $4
              AND ST_Contains(cell.g, ST_SetSRID(ST_MakePoint(pts.lon, pts.lat), 4326))
            GROUP BY src
            ORDER BY cnt DESC
        """, *bb)

        # Distinct WoRMS-resolved species across the four name-bearing tables.
        # All four arms share the same cell bbox ($2..$5) + geometry ($1).
        # biodiversity_hotspots has only a `geom` column (GIST-indexed); the other
        # three tables have lon/lat columns. $2=minlon $3=maxlon $4=minlat $5=maxlat.
        distinct_species = await conn.fetchval(
            """
            WITH cell AS (SELECT ST_GeomFromWKB($1, 4326) AS g),
            cell_names AS (
                SELECT scientific_name FROM biodiversity_hotspots, cell
                WHERE geom && ST_MakeEnvelope($2, $4, $3, $5, 4326)
                  AND ST_Contains(cell.g, geom)
                UNION ALL
                SELECT scientific_name FROM deepdata_occurrences, cell
                WHERE lon BETWEEN $2 AND $3 AND lat BETWEEN $4 AND $5
                  AND ST_Contains(cell.g, ST_SetSRID(ST_MakePoint(lon, lat), 4326))
                UNION ALL
                SELECT scientific_name FROM mbari_vars_records, cell
                WHERE lon BETWEEN $2 AND $3 AND lat BETWEEN $4 AND $5
                  AND ST_Contains(cell.g, ST_SetSRID(ST_MakePoint(lon, lat), 4326))
                UNION ALL
                SELECT scientific_name FROM noaa_corals_records, cell
                WHERE lon BETWEEN $2 AND $3 AND lat BETWEEN $4 AND $5
                  AND ST_Contains(cell.g, ST_SetSRID(ST_MakePoint(lon, lat), 4326))
            )
            SELECT COUNT(DISTINCT m.matched_aphia_id)
            FROM cell_names c
            JOIN taxon_name_map m ON m.raw_name = regexp_replace(trim(c.scientific_name), '\\s+', ' ', 'g')
            WHERE m.verified AND m.matched_aphia_id IS NOT NULL
            """,
            cell["geom_wkb"], cell["minlon"], cell["maxlon"], cell["minlat"], cell["maxlat"],
        )

        sampleable = {"pangaea", "bco-dmo", "noaa", "wod", "onc", "oceansites", "chess",
                      "argo", "sio_bic", "deepdata_isa", "mbari_vars", "noaa_corals", "cchdo"}
        present = {r["src"] for r in count_rows if r["cnt"] > 0 and r["src"] in sampleable}

    sample_results = await asyncio.gather(*[_cell_samples(src, cell) for src in present])
    samples_by_src = dict(zip(present, sample_results))

    sources = [
        {"src": r["src"], "count": r["cnt"], "samples": samples_by_src.get(r["src"], [])}
        for r in count_rows
    ]
    return {
        "cell_id": cell["cell_id"],
        "centroid_lon": cell["centroid_lon"],
        "centroid_lat": cell["centroid_lat"],
        "cell_lon": cell["centroid_lon"],
        "cell_lat": cell["centroid_lat"],
        "sources": sources,
        "total": sum(r["cnt"] for r in count_rows),
        "distinct_species": distinct_species or 0,
    }


@router.get("/monitoring-density/source-all")
async def get_monitoring_density_source_all(lon: float, lat: float, src: str):
    """Return all records for one source in the hex cell containing (lon,lat) (up to 500)."""
    async with db.pool.acquire() as conn:
        cell = await _lookup_cell(conn, lon, lat)
        if cell is None:
            return []
        return await _cell_samples_impl(conn, src, cell, limit=500)


@router.get("/monitoring-density/chess-species")
async def get_monitoring_density_chess_species(lon: float, lat: float):
    """Return all ChEssBase occurrences for the hex cell containing (lon,lat)."""
    async with db.pool.acquire() as conn:
        cell = await _lookup_cell(conn, lon, lat)
        if cell is None:
            return []
        bb = (cell["minlon"], cell["maxlon"], cell["minlat"], cell["maxlat"], cell["geom_wkb"])
        rows = await conn.fetch("""
            SELECT occurrence_id, species, phylum, depth_m, institution_code
            FROM chess_occurrences
            WHERE lon BETWEEN $1 AND $2 AND lat BETWEEN $3 AND $4
              AND ST_Contains(ST_GeomFromWKB($5, 4326), ST_SetSRID(ST_MakePoint(lon, lat), 4326))
            ORDER BY species NULLS LAST, occurrence_id
            LIMIT 500
        """, *bb)
    return [
        {
            "id":          r["occurrence_id"],
            "species":     r["species"] or "",
            "phylum":      r["phylum"] or "",
            "depth_m":     r["depth_m"],
            "institution": r["institution_code"] or "",
        }
        for r in rows
    ]

# ═══════════════════════════════════════════════════════════════════════════
# DataCite helper — used by both wod_profiles and pangaea_records
# ═══════════════════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════════════════
# WOD profiles — physical oceanography datasets (CTD, hydrography)
# via PANGAEA/DataCite. NOAA WOD lacks a geographic REST API; PANGAEA
# re-publishes many WOD-derived datasets and is fully indexed in DataCite.
# ═══════════════════════════════════════════════════════════════════════════

# ISA mining zone bboxes for geographic filtering: (minlon, minlat, maxlon, maxlat)
_WOD_BBOXES = [
    (-180.0, -90.0, 180.0, 90.0),   # global (DataCite returns global coordinates)
]

_WOD_QUERIES = [
    "CTD temperature salinity profiles deep ocean",
    "hydrographic station oceanographic profiles",
    "water column chemistry deep sea",
    "bottle data ocean chemistry profiles",
    "ocean temperature salinity pressure profiles",
]

async def _sync_wod_profiles() -> int:
    """Fetch physical oceanography dataset coordinates from PANGAEA via DataCite.
    Focuses on CTD/bottle/hydrographic datasets complementary to pangaea_records.
    One-time sync (static historical archive)."""
    async with db.pool.acquire() as conn:
        existing = await conn.fetchval("SELECT COUNT(*) FROM wod_profiles")
        if existing and existing > 5000:
            log.info("wod_profiles: already have %d records, skipping", existing)
            return 0

    seen_dois: set[str] = set()
    async with db.pool.acquire() as conn:
        rows_db = await conn.fetch("SELECT dataset FROM wod_profiles")
        seen_dois = {r["dataset"] for r in rows_db if r["dataset"]}

    inserted = 0
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for query in _WOD_QUERIES:
            items = await _datacite_paginate(client, "pangaea", query, max_records=2000)
            rows: list[tuple] = []
            for it in items:
                doi = it.get("id") or ""
                if not doi or doi in seen_dois:
                    continue
                seen_dois.add(doi)
                attrs = it.get("attributes") or {}
                coords = _datacite_extract_coords(attrs)
                if not coords:
                    continue
                lon, lat = coords
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    continue
                year = attrs.get("publicationYear")
                region = "global"
                rows.append((round(lon, 4), round(lat, 4), year, doi[:200], region))
            if rows:
                async with db.pool.acquire() as conn:
                    await conn.executemany("""
                        INSERT INTO wod_profiles (lon, lat, year, dataset, region)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (lon, lat, year, dataset) DO NOTHING
                    """, rows)
                inserted += len(rows)
            log.info("wod_profiles: '%s' → %d new records", query, len(rows))

    async with db.pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM wod_profiles")
    await _log_land_sync("wod_profiles", inserted, total or 0)
    log.info("wod_profiles: sync complete — %d inserted, %d total", inserted, total or 0)
    return inserted


# ═══════════════════════════════════════════════════════════════════════════
# PANGAEA records — deep-sea ecology/mining baseline datasets
# via DataCite API (api.datacite.org). provider-id=pangaea covers all
# PANGAEA-published datasets including ISA contractor baseline studies.
# ═══════════════════════════════════════════════════════════════════════════

_PANGAEA_QUERIES = [
    "manganese nodules deep sea",
    "polymetallic nodules baseline",
    "Clarion-Clipperton Zone sediment",
    "mid atlantic ridge baseline survey",
    "deep sea mining environmental",
    "hydrothermal vent baseline biology",
    "ISA contractor baseline",
    "abyssal plain biodiversity",
    "GEOTRACES section ocean",
    "trace element seawater profile",
    "dissolved iron manganese deep ocean",
]


async def _sync_pangaea_records() -> int:
    """Fetch PANGAEA deep-sea ecology/mining dataset coordinates via DataCite.
    Uses api.datacite.org with provider-id=pangaea. One-time sync."""
    async with db.pool.acquire() as conn:
        existing = await conn.fetchval("SELECT COUNT(*) FROM pangaea_records")
        if existing and existing > 5000:
            log.info("pangaea_records: already have %d records, skipping", existing)
            return 0

    seen_dois: set[str] = set()
    async with db.pool.acquire() as conn:
        rows_db = await conn.fetch("SELECT pangaea_id FROM pangaea_records")
        seen_dois = {r["pangaea_id"] for r in rows_db}

    inserted = 0
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for query in _PANGAEA_QUERIES:
            items = await _datacite_paginate(client, "pangaea", query, max_records=2000)
            rows: list[tuple] = []
            for it in items:
                doi = it.get("id") or ""
                if not doi or doi in seen_dois:
                    continue
                seen_dois.add(doi)
                attrs = it.get("attributes") or {}
                coords = _datacite_extract_coords(attrs)
                if not coords:
                    continue
                lon, lat = coords
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    continue
                year = attrs.get("publicationYear")
                title = ((attrs.get("titles") or [{}])[0].get("title") or "")[:200]
                rows.append((doi, round(lon, 4), round(lat, 4), year, title))
            if rows:
                async with db.pool.acquire() as conn:
                    await conn.executemany("""
                        INSERT INTO pangaea_records (pangaea_id, lon, lat, year, title)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (pangaea_id) DO NOTHING
                    """, rows)
                inserted += len(rows)
            log.info("pangaea_records: '%s' → %d new records", query, len(rows))

    async with db.pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM pangaea_records")
    await _log_land_sync("pangaea_records", inserted, total or 0)
    log.info("pangaea_records: sync complete — %d inserted, %d total", inserted, total or 0)
    return inserted


# ═══════════════════════════════════════════════════════════════════════════
# BCO-DMO datasets — US NSF biological/chemical oceanography
# via DataCite provider "bbwx". All 2900+ datasets carry geoLocationPoint
# or geoLocationBox, covering global ocean cruises and time-series.
# ═══════════════════════════════════════════════════════════════════════════

async def _sync_bco_dmo() -> int:
    """Fetch BCO-DMO dataset coordinates from DataCite (provider bbwx).
    BCO-DMO is a specialized ocean research archive — all ~3k datasets are
    relevant so we fetch the full catalog rather than using keyword queries.
    One-time sync."""
    async with db.pool.acquire() as conn:
        existing = await conn.fetchval("SELECT COUNT(*) FROM bco_dmo_datasets")
        if existing and existing > 5000:
            log.info("bco_dmo_datasets: already have %d records, skipping", existing)
            return 0

    seen_dois: set[str] = set()
    async with db.pool.acquire() as conn:
        rows_db = await conn.fetch("SELECT doi FROM bco_dmo_datasets")
        seen_dois = {r["doi"] for r in rows_db if r["doi"]}

    inserted = 0
    # Fetch entire BCO-DMO catalog — small enough for one paginated pass
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        items = await _datacite_paginate(client, "bbwx", "*", max_records=5000)
        rows: list[tuple] = []
        for it in items:
            doi = it.get("id") or ""
            if not doi or doi in seen_dois:
                continue
            seen_dois.add(doi)
            attrs = it.get("attributes") or {}
            coords = _datacite_extract_coords(attrs)
            if not coords:
                continue
            lon, lat = coords
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                continue
            year = attrs.get("publicationYear")
            title = ((attrs.get("titles") or [{}])[0].get("title") or "")[:200]
            rows.append((doi, round(lon, 4), round(lat, 4), year, title))
        if rows:
            async with db.pool.acquire() as conn:
                await conn.executemany("""
                    INSERT INTO bco_dmo_datasets (doi, lon, lat, year, title)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (doi) DO NOTHING
                """, rows)
            inserted += len(rows)
        log.info("bco_dmo_datasets: full catalog → %d new records", len(rows))

    async with db.pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM bco_dmo_datasets")
    await _log_land_sync("bco_dmo_datasets", inserted, total or 0)
    log.info("bco_dmo_datasets: sync complete — %d inserted, %d total", inserted, total or 0)
    return inserted


# ═══════════════════════════════════════════════════════════════════════════
# NOAA datasets — National Oceanic and Atmospheric Administration
# via DataCite provider "noaa". ~20k datasets, filtered to ocean/deep-sea
# to avoid pulling in atmospheric or coastal-only data.
# ═══════════════════════════════════════════════════════════════════════════

_NOAA_QUERIES = [
    "ocean temperature salinity CTD",
    "marine mammal sea turtle survey",
    "coral reef fish survey",
    "ocean current mooring buoy",
    "fish trawl survey stock",
]


async def _sync_noaa_datasets() -> int:
    """Fetch NOAA dataset coordinates from DataCite (provider noaa).
    Targets ocean/marine datasets via targeted queries. One-time sync."""
    async with db.pool.acquire() as conn:
        existing = await conn.fetchval("SELECT COUNT(*) FROM noaa_datasets")
        if existing and existing > 5000:
            log.info("noaa_datasets: already have %d records, skipping", existing)
            return 0

    seen_dois: set[str] = set()
    async with db.pool.acquire() as conn:
        rows_db = await conn.fetch("SELECT doi FROM noaa_datasets")
        seen_dois = {r["doi"] for r in rows_db if r["doi"]}

    inserted = 0
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for query in _NOAA_QUERIES:
            items = await _datacite_paginate(client, "noaa", query, max_records=1000)
            rows: list[tuple] = []
            for it in items:
                doi = it.get("id") or ""
                if not doi or doi in seen_dois:
                    continue
                seen_dois.add(doi)
                attrs = it.get("attributes") or {}
                coords = _datacite_extract_coords(attrs)
                if not coords:
                    continue
                lon, lat = coords
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    continue
                # Skip global-coverage gridded products (lat/lon span >60°×120°)
                geo = (attrs.get("geoLocations") or [{}])[0]
                box = geo.get("geoLocationBox") or {}
                if box:
                    try:
                        lat_span = abs(float(box.get("northBoundLatitude", 0)) - float(box.get("southBoundLatitude", 0)))
                        lon_span = abs(float(box.get("eastBoundLongitude", 0)) - float(box.get("westBoundLongitude", 0)))
                        if lat_span > 60 and lon_span > 120:
                            continue
                    except (TypeError, ValueError):
                        pass
                year = attrs.get("publicationYear")
                title = ((attrs.get("titles") or [{}])[0].get("title") or "")[:200]
                rows.append((doi, round(lon, 4), round(lat, 4), year, title))
            if rows:
                async with db.pool.acquire() as conn:
                    await conn.executemany("""
                        INSERT INTO noaa_datasets (doi, lon, lat, year, title)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (doi) DO NOTHING
                    """, rows)
                inserted += len(rows)
            log.info("noaa_datasets: '%s' → %d new records", query, len(rows))

    async with db.pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM noaa_datasets")
    await _log_land_sync("noaa_datasets", inserted, total or 0)
    log.info("noaa_datasets: sync complete — %d inserted, %d total", inserted, total or 0)
    return inserted


# ═══════════════════════════════════════════════════════════════════════════
# OBIS-SEAMAP proxy — cetacean and pinniped occurrences from OBIS
# WoRMS taxon 2688 (Cetartiodactyla, effectively cetaceans in OBIS marine
# context). SEAMAP focuses on megavertebrates; cetacean presence near
# mining zones is the key ISA noise-impact framing.
# ═══════════════════════════════════════════════════════════════════════════

_SEAMAP_TAXON_IDS = ["2688"]  # Cetartiodactyla (whales, dolphins in OBIS)


async def _sync_obis_seamap() -> int:
    """Fetch cetacean occurrence coordinates from OBIS as a SEAMAP-proxy source.
    Limits to 10k records to avoid excessive API calls."""
    async with db.pool.acquire() as conn:
        existing = await conn.fetchval("SELECT COUNT(*) FROM obis_seamap_records")
        if existing and existing > 10000:
            log.info("obis_seamap_records: already have %d records, skipping", existing)
            return 0

    inserted = 0
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for taxon_id in _SEAMAP_TAXON_IDS:
            offset = 0
            page_size = 5000
            while offset < 10000:
                try:
                    r = await client.get(
                        "https://api.obis.org/v3/occurrence",
                        params={
                            "taxonid": taxon_id,
                            "fields": "decimalLongitude,decimalLatitude,date_year",
                            "size": page_size,
                            "offset": offset,
                        },
                    )
                    r.raise_for_status()
                    data = r.json()
                except Exception as e:
                    log.warning("obis_seamap fetch error (taxon=%s offset=%d): %s", taxon_id, offset, e)
                    break
                results = data.get("results") or []
                if not results:
                    break
                rows: list[tuple] = []
                for rec in results:
                    lon = rec.get("decimalLongitude")
                    lat = rec.get("decimalLatitude")
                    if lon is None or lat is None:
                        continue
                    try:
                        lon, lat = float(lon), float(lat)
                    except (TypeError, ValueError):
                        continue
                    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                        continue
                    year = rec.get("date_year")
                    rows.append((round(lon, 4), round(lat, 4), year))
                if rows:
                    async with db.pool.acquire() as conn:
                        await conn.executemany("""
                            INSERT INTO obis_seamap_records (lon, lat, year)
                            VALUES ($1, $2, $3)
                            ON CONFLICT (lon, lat, year) DO NOTHING
                        """, rows)
                    inserted += len(rows)
                offset += page_size
                if len(results) < page_size:
                    break

    async with db.pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM obis_seamap_records")
    await _log_land_sync("obis_seamap_records", inserted, total or 0)
    log.info("obis_seamap_records: sync complete — %d inserted, %d total", inserted, total or 0)
    return inserted


# ═══════════════════════════════════════════════════════════════════════════
# NCEI ICOADS Global Marine — file-level monthly tile metadata
# Uses NCEI Search API paginated by year (offset > 10k fails; per-year <10k).
# Each result = monthly 10°×10° CSV tile with bbox + station count + data types.
# ═══════════════════════════════════════════════════════════════════════════

_NCEI_SEARCH_URL = "https://www.ncei.noaa.gov/access/services/search/v1/data"
_NCEI_YEARS = list(range(2005, 2026))  # last ~20 years; older files also available


# Waits BETWEEN attempts, so N attempts need N-1 waits. The old loop paired one
# wait with every attempt and therefore slept 8 s AFTER the final failure —
# pure waste, and `_NCEI_YEARS` holds 21 years, so nearly three minutes of it
# per run.
_NCEI_BACKOFF = (2, 4)


async def _fetch_ncei_year(client, year: int, params: dict) -> dict | None:
    """One year of NCEI Search v1, retrying only what is worth retrying.

    NCEI Search v1 throws intermittent 500s — 21 of them in one run on
    2026-09-02, which is why this table sat at 0 rows.

    ⛔ Three failure classes, three different answers:
      - transport failure (connect reset, read timeout): RETRY. The old code
        caught these under `except Exception: break`, so a dropped connection
        got ZERO retries while a 500 got three. That is backwards — the 500 is
        the upstream's considered answer, the dropped connection is noise. The
        VPS's IPv6 route to NCEI has been black-holed before, which makes this
        the more likely failure, not the rarer one.
      - 5xx: RETRY. Their known flake.
      - 4xx or a malformed body: DO NOT RETRY. That is OUR bad request, and
        repeating it only burns their quota and our time.

    Returns the decoded payload, or None once every attempt is spent.
    """
    attempts = len(_NCEI_BACKOFF) + 1
    for attempt in range(1, attempts + 1):
        last = attempt == attempts
        try:
            r = await client.get(_NCEI_SEARCH_URL, params=params)
        except Exception as exc:            # transport-level: connect/read/timeout
            log.warning("ncei year=%d attempt %d: %s", year, attempt, exc)
            if last:
                break
            await asyncio.sleep(_NCEI_BACKOFF[attempt - 1])
            continue

        if r.status_code >= 500:
            log.warning("ncei year=%d attempt %d: HTTP %d", year, attempt, r.status_code)
            if last:
                break
            await asyncio.sleep(_NCEI_BACKOFF[attempt - 1])
            continue

        try:
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            log.warning("ncei year=%d: %s — not retrying", year, exc)
            return None

    log.warning("ncei year=%d: giving up after %d attempts", year, attempts)
    return None


async def _sync_ncei_icoads() -> int:
    """Fetch NCEI ICOADS Global Marine file-level metadata for recent decades.
    Each file = monthly 10°×10° tile with station_count + observed data types.
    One DB row per file, using bbox centroid for the density grid."""
    async with db.pool.acquire() as conn:
        existing = await conn.fetchval("SELECT COUNT(*) FROM ncei_icoads_files")
        seen_paths_rows = await conn.fetch("SELECT file_path FROM ncei_icoads_files")
    seen_paths: set[str] = {r["file_path"] for r in seen_paths_rows if r["file_path"]}
    if existing and existing > 80000:
        log.info("ncei_icoads_files: already have %d records, skipping", existing)
        return 0

    inserted = 0
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        for year in _NCEI_YEARS:
            params = {
                "dataset": "global-marine",
                "startDate": f"{year}-01-01T00:00:00",
                "endDate": f"{year}-12-31T23:59:59",
                "limit": 10000,
                "offset": 0,
            }
            data = await _fetch_ncei_year(client, year, params)
            if data is None:
                continue

            rows: list[tuple] = []
            for item in data.get("results") or []:
                fp = item.get("filePath") or ""
                if not fp or fp in seen_paths:
                    continue
                bp = item.get("boundingPoints") or []
                if len(bp) < 2:
                    continue
                try:
                    p0 = bp[0].get("point") or [None, None]
                    p1 = bp[1].get("point") or [None, None]
                    lon = (float(p0[0]) + float(p1[0])) / 2
                    lat = (float(p0[1]) + float(p1[1])) / 2
                except (TypeError, ValueError, IndexError):
                    continue
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    continue
                start = item.get("startDate") or ""
                file_year = None
                if len(start) >= 4:
                    try:
                        file_year = int(start[:4])
                    except ValueError:
                        pass
                stations = item.get("stations") or []
                station_count = len(stations)
                dtypes: set[str] = set()
                for st in stations:
                    for dt in st.get("dataTypes") or []:
                        dtid = dt.get("id")
                        if dtid:
                            dtypes.add(dtid)
                # Keep a small, stable subset for the panel (ocean-relevant vars first)
                priority = [
                    "SEA_SURF_TEMP", "SST", "SEA_LEV_PRES", "WIND_SPEED",
                    "WIND_DIR", "WAVE_HGT", "AIR_TEMP", "SALINITY"
                ]
                top_types = [d for d in priority if d in dtypes][:5]
                if len(top_types) < 5:
                    top_types += sorted(dtypes - set(top_types))[:5 - len(top_types)]
                seen_paths.add(fp)
                rows.append((fp, round(lon, 4), round(lat, 4), file_year, station_count, top_types))

            if rows:
                async with db.pool.acquire() as conn:
                    await conn.executemany("""
                        INSERT INTO ncei_icoads_files
                          (file_path, lon, lat, year, station_count, data_types)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (file_path) DO NOTHING
                    """, rows)
                inserted += len(rows)
            log.info("ncei_icoads_files: year=%d → %d new records", year, len(rows))

    async with db.pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM ncei_icoads_files")
    await _log_land_sync("ncei_icoads_files", inserted, total or 0)
    log.info("ncei_icoads_files: sync complete — %d inserted, %d total", inserted, total or 0)
    return inserted


# ═══════════════════════════════════════════════════════════════════════════
# CCHDO — CLIVAR & Carbon Hydrographic Data Office
# GO-SHIP repeat hydrography cruise tracks. Each cruise has a LineString of
# station coordinates; we subsample to ~30 pts/cruise to keep the row count
# manageable while retaining spatial fidelity.
# ═══════════════════════════════════════════════════════════════════════════

_CCHDO_API_BASE = "https://cchdo.ucsd.edu/api/v1"
_CCHDO_MAX_POINTS_PER_CRUISE = 30


def _subsample_track(coords: list, max_points: int) -> list:
    """Evenly sample up to max_points from a LineString coordinate list."""
    if not coords:
        return []
    if len(coords) <= max_points:
        return coords
    step = len(coords) / max_points
    return [coords[int(i * step)] for i in range(max_points)]


def _cchdo_cruise_dates(detail: dict) -> tuple[date | None, date | None, str, int | None]:
    """(campaign_start, campaign_end, date_precision, year) for one CCHDO cruise.

    ⛔ The precision is never finer than `campaign`, and that is a statement about
    the SOURCE, not a limitation of this parser. The rows this feeds are vertices
    of `geometry.track` — a LineString of [lon, lat] pairs with no time on any
    point. CCHDO dates the CRUISE (`startDate`/`endDate`), not the vertex. Calling
    a track point `2007-07-06` would attach a day to a position that may have been
    occupied four days later; `campaign: 2007-07-06 → 2007-07-10` is the whole of
    what the source actually said.

    `endDate` was being dropped entirely before 2026-09-08, and `startDate` was
    truncated with `int(start[:4])` — which threw away the window and kept the one
    part of it that cannot express a window.

    Roughly 3.5% of cruises carry no usable date (14 of a 400-cruise sample). Those
    get `none`, never a silent NULL: `none` is the answer "the source has no date",
    and it also stops the backfill asking about that cruise again.
    """
    def _one(key: str) -> date | None:
        raw = (detail.get(key) or "").strip()
        if len(raw) < 10:
            return None
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None

    start, end = _one("startDate"), _one("endDate")
    if start is None and end is None:
        return None, None, "none", None
    # year stays derived from the start of the window, never from the end: a cruise
    # crossing New Year would otherwise report the year it finished in.
    return start, end, "campaign", (start or end).year


async def _backfill_cchdo_dates() -> int:
    """Give the cruise window to rows that were ingested before it was stored.

    ⚠️ Uses `/cruise/all`, NOT `/cruise`. The two names are one segment apart and
    return completely different payloads: `/cruise` is an index — `{expocode, id}`
    and nothing else, zero dates on all 2,558 entries — while `/cruise/all` is the
    full dump and carries `startDate`/`endDate` for 2,510 of them. The ingest above
    walks `/cruise` and then fetches each cruise individually because it needs the
    track geometry; a backfill needs only the dates, so it costs ONE request here
    instead of 2,558.

    `date_precision` is the queue and every cruise leaves it after one pass —
    including the 48 (1.9%) the source does not date, which get 'none'. Without
    that, the undated ones would be re-requested on every sync for ever.
    """
    async with db.pool.acquire() as conn:
        pending = await conn.fetchval(
            "SELECT count(*) FROM cchdo_stations WHERE date_precision IS NULL")
    if not pending:
        return 0

    try:
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
            r = await client.get(f"{_CCHDO_API_BASE}/cruise/all")
            r.raise_for_status()
            payload = r.json()
    except Exception as e:
        log.warning("cchdo backfill: cruise/all failed, dates left untouched: %s", e)
        return 0

    entries = payload if isinstance(payload, list) else (payload.get("cruises") or [])
    if not entries:
        log.warning("cchdo backfill: cruise/all returned 0 entries — not marking anything")
        return 0

    updates: list[tuple] = []
    for entry in entries:
        expocode = (entry.get("expocode") or "").strip()
        if not expocode:
            continue
        camp_start, camp_end, precision, year = _cchdo_cruise_dates(entry)
        updates.append((camp_start, camp_end, precision, year, expocode))

    filled = 0
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            for camp_start, camp_end, precision, year, expocode in updates:
                # COALESCE on year: the existing value was already derived from the same
                # startDate, so this must not blank it out for a cruise the dump omits.
                filled += int((await conn.execute("""
                    UPDATE cchdo_stations
                       SET campaign_start = $1,
                           campaign_end   = $2,
                           date_precision = $3,
                           year           = COALESCE($4, year)
                     WHERE expocode = $5 AND date_precision IS NULL
                """, camp_start, camp_end, precision, year, expocode)).split()[-1])

    log.info("cchdo backfill: %d rows dated from %d cruises (%d rows were pending)",
             filled, len(updates), pending)
    return filled


async def _sync_cchdo_cruises() -> int:
    """Fetch CCHDO cruise track coordinates (GO-SHIP repeat hydrography).
    ~2500 cruises, each with an expanded track LineString."""
    async with db.pool.acquire() as conn:
        existing = await conn.fetchval("SELECT COUNT(*) FROM cchdo_stations")
    if existing and existing > 40000:
        # The track geometry is complete; what the 41,102 pre-2026-09-08 rows lack is
        # the cruise window. Fill that in place. Re-ingesting 2,558 cruises to rewrite
        # two columns would fetch the same coordinates back at ~2,558 requests.
        filled = await _backfill_cchdo_dates()
        log.info("cchdo_stations: already have %d records; dated %d rows", existing, filled)
        return 0

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        try:
            r = await client.get(f"{_CCHDO_API_BASE}/cruise")
            r.raise_for_status()
            cruises = (r.json() or {}).get("cruises") or []
        except Exception as e:
            log.warning("cchdo cruise list error: %s", e)
            return 0
        log.info("cchdo: fetched %d cruise IDs", len(cruises))

        inserted = 0
        async with db.pool.acquire() as conn:
            existing_expocodes = await conn.fetch("SELECT DISTINCT expocode FROM cchdo_stations")
        seen: set[str] = {r["expocode"] for r in existing_expocodes if r["expocode"]}

        for i, entry in enumerate(cruises):
            cid = entry.get("id")
            expocode = entry.get("expocode") or ""
            if not cid or not expocode or expocode in seen:
                continue
            try:
                r2 = await client.get(f"{_CCHDO_API_BASE}/cruise/{cid}")
                r2.raise_for_status()
                detail = r2.json() or {}
            except Exception as e:
                log.warning("cchdo cruise %s error: %s", cid, e)
                continue

            track = ((detail.get("geometry") or {}).get("track") or {}).get("coordinates") or []
            points = _subsample_track(track, _CCHDO_MAX_POINTS_PER_CRUISE)
            if not points:
                continue
            ship = (detail.get("ship") or "")[:100]
            country = (detail.get("country") or "")[:8]
            camp_start, camp_end, precision, year = _cchdo_cruise_dates(detail)
            woce_lines = (detail.get("collections") or {}).get("woce_lines") or []
            woce_line = (woce_lines[0] if woce_lines else "")[:32]

            rows: list[tuple] = []
            for p in points:
                try:
                    lon = float(p[0]); lat = float(p[1])
                except (TypeError, ValueError, IndexError):
                    continue
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    continue
                rows.append((expocode, ship, country, year, woce_line, round(lon, 4), round(lat, 4),
                             camp_start, camp_end, precision))

            if rows:
                async with db.pool.acquire() as conn:
                    await conn.executemany("""
                        INSERT INTO cchdo_stations
                          (expocode, ship, country, year, woce_line, lon, lat,
                           campaign_start, campaign_end, date_precision)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        ON CONFLICT (expocode, lon, lat) DO NOTHING
                    """, rows)
                inserted += len(rows)
                seen.add(expocode)

            if i % 100 == 0 and i > 0:
                log.info("cchdo: processed %d/%d cruises (%d points inserted)", i, len(cruises), inserted)
            # Light throttle
            await asyncio.sleep(0.05)

    async with db.pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM cchdo_stations")
    await _log_land_sync("cchdo_stations", inserted, total or 0)
    log.info("cchdo_stations: sync complete — %d inserted, %d total", inserted, total or 0)
    return inserted
