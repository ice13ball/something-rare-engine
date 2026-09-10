# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import pathlib
import shutil
from collections import OrderedDict
from datetime import datetime
from enum import Enum
from typing import Annotated, Optional

import asyncpg
import db
import raster_tiles
from auth import get_api_key
from fastapi import APIRouter, Depends, HTTPException, Path, Response
from PIL import Image
from pydantic import BaseModel, Field, model_validator

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v2/spatial", tags=["spatial-v2"])

# Limit concurrent PostGIS tile queries — each MVT query on WDPA/KBA/water-risk
# can saturate a full CPU core for 10-60 s. Without this, a burst of tile
# requests (pan/zoom) pegs all cores simultaneously (load > 8 on a 4-core VPS).
# Bumped 3 → 6 after offshore-activities raster tiles started getting starved
# at low zoom (Mexico/GoM cold tiles).
_TILE_SEM = asyncio.Semaphore(6)

# ── Two-tier tile cache ──────────────────────────────────────────────────────
# Tier 1: hot in-memory LRU (256 entries) — sub-ms, avoids disk reads for
#         frequently requested tiles (e.g. zoom-0 WDPA tile requested by every
#         user).
# Tier 2: on-disk cache — survives restarts, shared across uvicorn workers.
#         Each tile is a file at {TILE_CACHE_DIR}/{layer}/{z}/{x}/{y}.mvt.
#         Empty tiles (204) are stored as 0-byte files.
#         Writes are atomic (tmp-file + rename) to avoid half-written tiles.
#
# Invalidation: clear_tile_cache() removes both tiers. Called by sync fns.
_TILE_CACHE_DIR = pathlib.Path(os.getenv("TILE_CACHE_DIR", "/var/cache/abyssal-tiles"))

_MEM_CACHE: OrderedDict[str, bytes | None] = OrderedDict()
_MEM_CACHE_MAX = 256

_RASTER_CACHE_DIR = pathlib.Path(
    os.getenv("RASTER_TILE_CACHE_DIR", "/var/cache/abyssal-tiles-raster")
)
_RASTER_MEM: OrderedDict[str, bytes] = OrderedDict()
_RASTER_MEM_MAX = 512  # bumped 256 → 512 to keep more low-zoom tiles hot in memory

_MISS = object()

_EMPTY_MVT = Response(
    content=b"",
    status_code=204,
    headers={"Cache-Control": "no-store"},
)


def _disk_path(key: str) -> pathlib.Path:
    layer, z, x, y = key.split("/")
    return _TILE_CACHE_DIR / layer / z / x / f"{y}.mvt"


def _cache_get(key: str) -> bytes | None | object:
    if key in _MEM_CACHE:
        _MEM_CACHE.move_to_end(key)
        return _MEM_CACHE[key]
    p = _disk_path(key)
    try:
        data = p.read_bytes()
        if not data:
            # 0-byte file means the tile timed out when it was originally rendered.
            # Force a fresh render rather than serving 204 forever.
            return _MISS
        _mem_put(key, data)
        return data
    except (FileNotFoundError, OSError):
        return _MISS


def _mem_put(key: str, tile: bytes | None) -> None:
    _MEM_CACHE[key] = tile
    if len(_MEM_CACHE) > _MEM_CACHE_MAX:
        _MEM_CACHE.popitem(last=False)


def _cache_put(key: str, tile: bytes | None) -> None:
    _mem_put(key, tile)
    p = _disk_path(key)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(tile if tile is not None else b"")
        tmp.rename(p)
    except OSError as exc:
        log.warning("tile disk cache write failed: %s", exc)


def clear_tile_cache() -> int:
    n = len(_MEM_CACHE)
    _MEM_CACHE.clear()
    n += len(_RASTER_MEM)
    _RASTER_MEM.clear()
    for cache_dir in (_TILE_CACHE_DIR, _RASTER_CACHE_DIR):
        try:
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
                cache_dir.mkdir(parents=True, exist_ok=True)
                n += 1
        except OSError as exc:
            log.warning("tile disk cache clear failed (%s): %s", cache_dir, exc)
    return n


def clear_layer_tile_cache(layer: str) -> int:
    """Drop one layer's tiles from the in-memory LRU and the disk cache.

    Cache keys are `{layer}/{z}/{x}/{y}` and disk tiles live under
    `{_TILE_CACHE_DIR}/{layer}/`. Use this instead of `clear_tile_cache()` when
    only one layer's data changed — the global clear forces every other layer to
    re-render from PostGIS.
    """
    prefix = f"{layer}/"
    stale = [k for k in _MEM_CACHE if k.startswith(prefix)]
    for k in stale:
        _MEM_CACHE.pop(k, None)
    n = len(stale)
    layer_dir = _TILE_CACHE_DIR / layer
    try:
        if layer_dir.exists():
            shutil.rmtree(layer_dir)
            n += 1
    except OSError as exc:
        log.warning("tile disk cache clear failed (%s): %s", layer_dir, exc)
    return n


# ── Raster tile cache helpers (offshore-activities PNG tiles) ────────────────


_BAKED_DIR = pathlib.Path(
    os.getenv("RASTER_TILE_CACHE_DIR", "/var/cache/abyssal-tiles-raster")
) / "offshore-activities" / "_baked"


def _baked_path(z: int, x: int, y: int) -> pathlib.Path:
    return _BAKED_DIR / str(z) / str(x) / f"{y}.png"


def _transparent_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _raster_disk_path(z: int, x: int, y: int, filter_key: str) -> pathlib.Path:
    # `filter_key` is built from the raw `types`/`countries` query params (only
    # split-and-stripped, no allowlist) and must never be interpolated into a
    # filesystem path directly — a value like "../../../etc/passwd" or a
    # leading "/" would escape _RASTER_CACHE_DIR (arbitrary file write via
    # _raster_put). Hash it instead: a hex digest can't contain "/", ".." or a
    # null byte, so no input can traverse out, and it self-caps filename
    # length (a raw filter_key with many countries could exceed the ~255-byte
    # filename limit on most filesystems). This intentionally invalidates any
    # on-disk cache files written under the old `{y}__{filter_key}.png` naming
    # — they are a regenerable render cache, not data, so they are simply
    # orphaned (not migrated, not deleted) and get pruned by normal cache
    # eviction/disk-cleanup over time.
    digest = hashlib.sha256(filter_key.encode()).hexdigest()[:32]
    return _RASTER_CACHE_DIR / "offshore-activities" / "_ondemand" / str(z) / str(x) / f"{y}__{digest}.png"


def _raster_get(z: int, x: int, y: int, filter_key: str) -> bytes | None:
    k = f"{z}/{x}/{y}/{filter_key}"
    if k in _RASTER_MEM:
        _RASTER_MEM.move_to_end(k)
        return _RASTER_MEM[k]
    try:
        data = _raster_disk_path(z, x, y, filter_key).read_bytes()
        _RASTER_MEM[k] = data
        if len(_RASTER_MEM) > _RASTER_MEM_MAX:
            _RASTER_MEM.popitem(last=False)
        return data
    except (FileNotFoundError, OSError):
        return None


def _raster_put(z: int, x: int, y: int, filter_key: str, png: bytes) -> None:
    k = f"{z}/{x}/{y}/{filter_key}"
    _RASTER_MEM[k] = png
    if len(_RASTER_MEM) > _RASTER_MEM_MAX:
        _RASTER_MEM.popitem(last=False)
    p = _raster_disk_path(z, x, y, filter_key)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(png)
        tmp.rename(p)
    except OSError as exc:
        log.warning("raster disk cache write failed: %s", exc)


class SpatialLayer(str, Enum):
    mining_contracts = "mining_contracts"
    hydrothermal_vents = "hydrothermal_vents"
    mining_footprints = "mining_footprints"
    water_risk = "water_risk"
    offshore_activities = "offshore-activities"
    offshore_zones = "offshore-zones"
    wod_oxygen = "wod-oxygen"
    memento = "memento"
    geotraces = "geotraces"
    mosaic = "mosaic"
    arctic_catchments = "arctic-catchments"


# (source, status) tuples that are aggregate ZONE classifications, NOT specific
# concessions. Mirrors frontend/src/utils/offshoreZones.ts ZONE_RULES — keep
# the two lists in sync. The MVT pipeline serves these on a separate layer
# so the concession layer stays clickable and visually clean.
_ZONE_TUPLES: tuple[tuple[str, str], ...] = (
    ("anh_co",  "sin asignar"),       # Colombia: "available" — not a concession
    ("anh_co",  "ambiental"),         # Colombia: environmental zone
    ("pasa",    "available_block"),   # South Africa: open for licensing
    # EMODnet 'planned' and 'other' previously listed here turned out to be
    # actual concessions in those statuses (344 planned wind farms, 21 oil/gas
    # 'other'), not zone metadata. Removed Apr 2026 after they kept appearing
    # under wrong filter selections.
)

# SQL fragment: "AND (source, status) NOT IN ((...))" / "AND (source, status) IN ((...))"
# COALESCE(status,''): a NULL status makes both IN and NOT IN evaluate to NULL,
# which would silently drop the row from BOTH the concession layer and the zone
# layer (invisible everywhere). No source ships NULL today — this is insurance
# against the next registry that does.
_ZONE_PREDICATE_VALUES = ", ".join(f"('{s}','{st}')" for s, st in _ZONE_TUPLES)
_ZONE_EXCLUDE_SQL = f"AND (oa.source, COALESCE(oa.status, '')) NOT IN ({_ZONE_PREDICATE_VALUES})"
_ZONE_INCLUDE_SQL = f"AND (oa.source, COALESCE(oa.status, '')) IN ({_ZONE_PREDICATE_VALUES})"


class TileCoord(BaseModel):
    z: Annotated[int, Field(ge=0, le=22)]
    x: Annotated[int, Field(ge=0)]
    y: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def coords_within_zoom(self) -> TileCoord:
        max_coord = (1 << self.z) - 1
        if self.x > max_coord or self.y > max_coord:
            raise ValueError(
                f"x={self.x} or y={self.y} out of range for z={self.z} (max {max_coord})"
            )
        return self


_MVT_MINING = """
WITH bounds AS (
    SELECT ST_TileEnvelope($1::int, $2::int, $3::int) AS env
),
mvt AS (
    SELECT
        ST_AsMVTGeom(
            ST_Transform(ST_SetSRID(mc.geom, 4326), 3857),
            b.env, 4096, 256, true
        ) AS geom,
        mc.isa_id,
        mc.contractor_name,
        mc.resource_type,
        ROUND(mc.area_km2::numeric, 2)::float8 AS area_km2,
        mc.is_high_risk
    FROM mining_contracts mc CROSS JOIN bounds b
    WHERE ST_Intersects(ST_SetSRID(mc.geom, 4326), ST_Transform(b.env, 4326))
)
SELECT ST_AsMVT(mvt, 'mining_contracts', 4096, 'geom') FROM mvt
"""

_MVT_MINING_SIMPLIFIED = """
WITH bounds AS (
    SELECT ST_TileEnvelope($1::int, $2::int, $3::int) AS env
),
mvt AS (
    SELECT
        ST_AsMVTGeom(
            ST_SimplifyPreserveTopology(
                ST_Transform(ST_SetSRID(mc.geom, 4326), 3857),
                $4::float8
            ),
            b.env, 4096, 256, true
        ) AS geom,
        mc.isa_id,
        mc.contractor_name,
        mc.resource_type,
        ROUND(mc.area_km2::numeric, 2)::float8 AS area_km2,
        mc.is_high_risk
    FROM mining_contracts mc CROSS JOIN bounds b
    WHERE ST_Intersects(ST_SetSRID(mc.geom, 4326), ST_Transform(b.env, 4326))
)
SELECT ST_AsMVT(mvt, 'mining_contracts', 4096, 'geom') FROM mvt
"""

_MVT_VENTS = """
WITH bounds AS (
    SELECT ST_TileEnvelope($1::int, $2::int, $3::int) AS env
),
mvt AS (
    SELECT
        ST_AsMVTGeom(
            ST_Transform(hv.geom::geometry, 3857),
            b.env, 4096, 256, true
        ) AS geom,
        hv.id,
        hv.name,
        hv.status,
        COALESCE(hv.depth_m, 0)::float8 AS depth_m,
        hv.latitude,
        hv.longitude
    FROM hydrothermal_vents hv CROSS JOIN bounds b
    WHERE ST_Intersects(hv.geom::geometry, ST_Transform(b.env, 4326))
)
SELECT ST_AsMVT(mvt, 'hydrothermal_vents', 4096, 'geom') FROM mvt
"""

# ── WOD Oxygen Profiles MVT query (point layer — no simplification) ───────

_MVT_WOD_OXYGEN = """
WITH bounds AS (
    SELECT ST_TileEnvelope($1::int, $2::int, $3::int) AS env
),
mvt AS (
    SELECT ST_AsMVTGeom(ST_Transform(w.geom, 3857), b.env, 4096, 256, true) AS geom,
           w.id, w.decade, to_char(w.profile_date, 'YYYY-MM-DD') AS profile_date
    FROM wod_oxygen_profiles w CROSS JOIN bounds b
    WHERE w.geom && ST_Transform(b.env, 4326)
      -- Low-zoom decimation: a world/basin tile spans hundreds of thousands of the
      -- ~1M global casts; thinning by id-modulo keeps ST_AsMVT under statement_timeout
      -- (a timed-out tile caches 0-byte/blank → "dots disappear"). Full detail from
      -- z>=5 (modulo 1). ids run in ingest (year/cruise) order, so each cruise track is
      -- uniformly subsampled — spatially representative at overview zoom.
      AND (w.id % (CASE WHEN $1 <= 1 THEN 48
                        WHEN $1 = 2 THEN 16
                        WHEN $1 = 3 THEN 6
                        WHEN $1 = 4 THEN 2
                        ELSE 1 END)) = 0
)
SELECT ST_AsMVT(mvt, 'wod_oxygen', 4096, 'geom') FROM mvt
"""

# ── GEOTRACES trace-metal stations MVT query (point layer — no simplification) ─
# Low-zoom decimation by stable hash of station_id keeps overview tiles well under
# statement_timeout. Full detail from z>=4 (modulo 1). $1=z, $2=x, $3=y.

_MVT_GEOTRACES = """
WITH bounds AS (SELECT ST_TileEnvelope($1::int, $2::int, $3::int) AS env),
mvt AS (
  SELECT ST_AsMVTGeom(ST_Transform(s.geom, 3857), b.env, 4096, 64, true) AS geom,
         abs(hashtext(s.station_id)) AS fid,
         s.station_id, s.cruise, s.station, s.decade,
         s.has_mn, s.has_fe, s.has_co, s.has_ni, s.has_cu,
         s.mn_max, s.fe_max, s.co_max, s.ni_max, s.cu_max
  FROM geotraces_stations s CROSS JOIN bounds b
  WHERE s.geom && ST_Transform(b.env, 4326)
    AND abs(hashtext(s.station_id))
        % (CASE WHEN $1 <= 0 THEN 12 WHEN $1 = 1 THEN 6 WHEN $1 = 2 THEN 4 WHEN $1 = 3 THEN 2 ELSE 1 END) = 0
)
SELECT ST_AsMVT(mvt, 'geotraces', 4096, 'geom') FROM mvt
"""

_MVT_MOSAIC = """
WITH bounds AS (SELECT ST_TileEnvelope($1::int, $2::int, $3::int) AS env),
mvt AS (
  SELECT ST_AsMVTGeom(ST_Transform(s.geom, 3857), b.env, 4096, 64, true) AS geom,
         s.core_id AS fid,
         s.core_id, s.core_name, s.decade,
         s.has_toc, s.has_tn, s.has_d13c, s.has_d14c,
         s.toc_surf, s.tn_surf, s.d13c_surf, s.d14c_surf
  FROM mosaic_cores s CROSS JOIN bounds b
  WHERE s.geom && ST_Transform(b.env, 4326)
    AND (s.core_id
        % (CASE WHEN $1 <= 0 THEN 12 WHEN $1 = 1 THEN 6 WHEN $1 = 2 THEN 4 WHEN $1 = 3 THEN 2 ELSE 1 END)) = 0
)
SELECT ST_AsMVT(mvt, 'mosaic', 4096, 'geom') FROM mvt
"""

# ── ARCTIC CATCHMENTS polygon MVT queries (choropleth, geom_3857 precomputed) ─
# Slim tile: gid + 5 recolor variables. Everything else fetched lazily by /by-id.
# Simplified variant used at z ≤ 6 (SpatialLayer.arctic_catchments: 6 in _SIMPLIFY_THRESHOLD).

_MVT_ARCTIC_CATCHMENTS = """
WITH bounds AS (SELECT ST_TileEnvelope($1,$2,$3) AS env)
SELECT ST_AsMVT(t, 'arctic-catchments', 4096, 'geom') FROM (
  SELECT ac.gid, ac.ocs_mean, ac.oc_tot, ac.runoff_mean, ac.pf_frac, ac.t_2m_mean,
         ST_AsMVTGeom(ac.geom_3857, bounds.env, 4096, 64, true) AS geom
  FROM arctic_catchments ac, bounds
  WHERE ac.geom_3857 && bounds.env
) t
"""

_MVT_ARCTIC_CATCHMENTS_SIMPLIFIED = """
WITH bounds AS (SELECT ST_TileEnvelope($1,$2,$3) AS env)
SELECT ST_AsMVT(t, 'arctic-catchments', 4096, 'geom') FROM (
  SELECT ac.gid, ac.ocs_mean, ac.oc_tot, ac.runoff_mean, ac.pf_frac, ac.t_2m_mean,
         ST_AsMVTGeom(ST_SimplifyPreserveTopology(ac.geom_3857, $4),
                      bounds.env, 4096, 64, true) AS geom
  FROM arctic_catchments ac, bounds
  WHERE ac.geom_3857 && bounds.env
    AND ac.area_km2 >= $5   -- zoom-dependent area floor: drop sub-pixel basins at low zoom
) t
"""

# ── MEMENTO marine CH₄/N₂O casts MVT query (point layer — no simplification) ─

_MVT_MEMENTO = """
WITH bounds AS (
    SELECT ST_TileEnvelope($1::int, $2::int, $3::int) AS env
),
mvt AS (
    SELECT ST_AsMVTGeom(ST_Transform(c.geom, 3857), b.env, 4096, 256, true) AS geom,
           abs(hashtext(c.cast_id)) AS fid,
           c.cast_id, c.decade, c.has_ch4, c.has_n2o, c.ch4_surf, c.n2o_surf
    FROM memento_casts c CROSS JOIN bounds b
    WHERE c.geom && ST_Transform(b.env, 4326)
      -- low-zoom decimation by a stable hash of cast_id (casts << 1M, but keep
      -- overview tiles under statement_timeout and visually thinned)
      AND abs(hashtext(c.cast_id))
          % (CASE WHEN $1 <= 1 THEN 12 WHEN $1 = 2 THEN 6 WHEN $1 = 3 THEN 3 ELSE 1 END) = 0
)
SELECT ST_AsMVT(mvt, 'memento', 4096, 'geom') FROM mvt
"""


_MVT_FOOTPRINTS = """
WITH bounds AS (
    SELECT ST_TileEnvelope($1::int, $2::int, $3::int) AS env
),
mvt AS (
    SELECT
        ST_AsMVTGeom(
            ST_Transform(ST_SetSRID(mf.geom, 4326), 3857),
            b.env, 4096, 256, true
        ) AS geom,
        mf.id,
        mf.country,
        mf.ftype,
        ROUND(mf.area_km2::numeric, 2)::float8 AS area_km2
    FROM mining_footprints mf CROSS JOIN bounds b
    WHERE ST_Intersects(ST_SetSRID(mf.geom, 4326), ST_Transform(b.env, 4326))
)
SELECT ST_AsMVT(mvt, 'mining_footprints', 4096, 'geom') FROM mvt
"""

_MVT_FOOTPRINTS_SIMPLIFIED = """
WITH bounds AS (
    SELECT ST_TileEnvelope($1::int, $2::int, $3::int) AS env
),
mvt AS (
    SELECT
        ST_AsMVTGeom(
            ST_SimplifyPreserveTopology(
                ST_Transform(ST_SetSRID(mf.geom, 4326), 3857),
                $4::float8
            ),
            b.env, 4096, 256, true
        ) AS geom,
        mf.id,
        mf.country,
        mf.ftype,
        ROUND(mf.area_km2::numeric, 2)::float8 AS area_km2
    FROM mining_footprints mf CROSS JOIN bounds b
    WHERE ST_Intersects(ST_SetSRID(mf.geom, 4326), ST_Transform(b.env, 4326))
)
SELECT ST_AsMVT(mvt, 'mining_footprints', 4096, 'geom') FROM mvt
"""

# ── KBA MVT queries — REMOVED 2026-09-03 ───────────────────────────────────
# The tile SQL served full KBA geometry plus site_name, country, status and
# criteria. BirdLife's KBA terms forbid redistributing KBA through an
# interactive web map without prior written permission from the KBA
# Secretariat, plus a separate no-commercial-use clause.
# ⛔ Do not restore this SQL "just to have it" — a dormant tile query is one
# elif away from serving again. Restore it only alongside the permission.

# ── WDPA MVT queries — REMOVED 2026-09-03 ──────────────────────────────────
# The tile SQL served full protected-area geometry plus wdpa_id, name, desig
# and iucn_cat. Protected Planet's terms forbid redistributing WDPA through an
# interactive web map without prior written permission from UNEP-WCMC.
# ⛔ Do not restore this SQL "just to have it" — a dormant tile query is one
# elif away from serving again. Restore it only alongside the permission.

# ── Water Risk MVT queries ────────────────────────────────────────────────

_MVT_WATER_RISK = """
WITH bounds AS (
    SELECT ST_TileEnvelope($1::int, $2::int, $3::int) AS env
),
mvt AS (
    SELECT
        ST_AsMVTGeom(
            ST_Transform(w.geom, 3857),
            b.env, 4096, 256, true
        ) AS geom,
        w.string_id,
        w.name_0,
        w.name_1,
        w.w_awr_min_tot_cat,
        w.w_awr_min_tot_label
    FROM water_risk w CROSS JOIN bounds b
    WHERE ST_Intersects(w.geom, ST_Transform(b.env, 4326))
)
SELECT ST_AsMVT(mvt, 'water_risk', 4096, 'geom') FROM mvt
"""

_MVT_WATER_RISK_SIMPLIFIED = """
WITH bounds AS (
    SELECT ST_TileEnvelope($1::int, $2::int, $3::int) AS env
),
mvt AS (
    SELECT
        ST_AsMVTGeom(
            ST_SimplifyPreserveTopology(
                ST_Transform(w.geom, 3857),
                $4::float8
            ),
            b.env, 4096, 256, true
        ) AS geom,
        w.string_id,
        w.name_0,
        w.name_1,
        w.w_awr_min_tot_cat,
        w.w_awr_min_tot_label
    FROM water_risk w CROSS JOIN bounds b
    WHERE ST_Intersects(w.geom, ST_Transform(b.env, 4326))
)
SELECT ST_AsMVT(mvt, 'water_risk', 4096, 'geom') FROM mvt
"""


# ── Offshore Activities MVT queries ──────────────────────────────────────────

# EMODnet returns hierarchical lease data — parent licence boundaries + sub-block /
# wind-farm polygons inside them — and we ingest both. ~6.4k overlapping pairs across
# ~4k features. ORDER BY ST_Area(geom) DESC ensures the smallest polygon is the last
# feature in the MVT, so deck.gl's SolidPolygonLayer (which renders in array order,
# later-on-top) draws sub-blocks on top of their parent. Without this, e.g. B 3
# (26 km²) gets visually swallowed by Łeba (1153 km²) once you zoom past z≈7.5.
# Tile SQL keeps only the columns deck.gl needs for rendering (id/activity_type/sovereign)
# and the columns the panel renders during the brief window between click and /by-id arrival
# (name/operator/status/source/source_id). Everything else (JSONB extractions, dates,
# portal_url, area_km2) is fetched lazily on click via /offshore-activities/by-id/{id}.
# Removing the 8 JSONB extractions and date casts cut per-tile CPU dramatically at z=7-8.
_MVT_OFFSHORE = f"""
WITH bounds AS (
    SELECT ST_TileEnvelope($1::int, $2::int, $3::int) AS env
),
mvt AS (
    SELECT
        ST_AsMVTGeom(oa.geom_3857, b.env, 4096, 256, true) AS geom,
        oa.id,
        oa.activity_type,
        oa.name,
        oa.operator,
        oa.sovereign,
        oa.status,
        oa.source,
        oa.source_id
    FROM offshore_activities oa CROSS JOIN bounds b
    WHERE ST_Intersects(oa.geom, ST_Transform(b.env, 4326))
      AND (oa.name IS NOT NULL OR oa.operator IS NOT NULL)
      {_ZONE_EXCLUDE_SQL}
    ORDER BY ST_Area(oa.geom) DESC
)
SELECT ST_AsMVT(mvt, 'offshore_activities', 4096, 'geom') FROM mvt
"""

_MVT_OFFSHORE_SIMPLIFIED = f"""
WITH bounds AS (
    SELECT ST_TileEnvelope($1::int, $2::int, $3::int) AS env
),
mvt AS (
    SELECT
        ST_AsMVTGeom(
            ST_SimplifyPreserveTopology(oa.geom_3857, $4::float8),
            b.env, 4096, 256, true
        ) AS geom,
        oa.id,
        oa.activity_type,
        oa.name,
        oa.operator,
        oa.sovereign,
        oa.status,
        oa.source,
        oa.source_id
    FROM offshore_activities oa CROSS JOIN bounds b
    WHERE ST_Intersects(oa.geom, ST_Transform(b.env, 4326))
      AND (oa.name IS NOT NULL OR oa.operator IS NOT NULL)
      {_ZONE_EXCLUDE_SQL}
    ORDER BY ST_Area(oa.geom) DESC
)
SELECT ST_AsMVT(mvt, 'offshore_activities', 4096, 'geom') FROM mvt
"""

# Zone-classification tile: ONLY the (source, status) tuples in _ZONE_TUPLES.
# Rendered on top of the concession layer with constant slate fill, non-pickable.
_MVT_OFFSHORE_ZONES = f"""
WITH bounds AS (
    SELECT ST_TileEnvelope($1::int, $2::int, $3::int) AS env
),
mvt AS (
    SELECT
        ST_AsMVTGeom(oa.geom_3857, b.env, 4096, 256, true) AS geom,
        oa.id,
        oa.activity_type,
        oa.source,
        oa.status,
        oa.sovereign
    FROM offshore_activities oa CROSS JOIN bounds b
    WHERE ST_Intersects(oa.geom, ST_Transform(b.env, 4326))
      {_ZONE_INCLUDE_SQL}
    ORDER BY ST_Area(oa.geom) DESC
)
SELECT ST_AsMVT(mvt, 'offshore_zones', 4096, 'geom') FROM mvt
"""

_MVT_OFFSHORE_ZONES_SIMPLIFIED = f"""
WITH bounds AS (
    SELECT ST_TileEnvelope($1::int, $2::int, $3::int) AS env
),
mvt AS (
    SELECT
        ST_AsMVTGeom(
            ST_SimplifyPreserveTopology(oa.geom_3857, $4::float8),
            b.env, 4096, 256, true
        ) AS geom,
        oa.id,
        oa.activity_type,
        oa.source,
        oa.status,
        oa.sovereign
    FROM offshore_activities oa CROSS JOIN bounds b
    WHERE ST_Intersects(oa.geom, ST_Transform(b.env, 4326))
      {_ZONE_INCLUDE_SQL}
    ORDER BY ST_Area(oa.geom) DESC
)
SELECT ST_AsMVT(mvt, 'offshore_zones', 4096, 'geom') FROM mvt
"""


class MiningContractDetail(BaseModel):
    isa_id: str
    contractor_name: str
    resource_type: Optional[str]
    area_km2: Optional[float]
    act_date: Optional[datetime]
    expiry_date: Optional[datetime]
    is_high_risk: bool
    jurisdiction_text: Optional[str]
    nearest_eez_country: Optional[str]
    nearest_eez_dist_km: Optional[float]
    nearest_unesco_site: Optional[str]
    nearest_unesco_dist_km: Optional[float]
    centroid_lon: Optional[float]
    centroid_lat: Optional[float]


class HydrothermalVentDetail(BaseModel):
    id: int
    name: str
    status: str
    depth_m: Optional[float]
    min_depth_m: Optional[float] = None
    max_temp_c: Optional[float] = None
    temp_category: Optional[str] = None
    ocean: Optional[str] = None
    region: Optional[str] = None
    jurisdiction: Optional[str] = None
    tectonic_setting: Optional[str] = None
    discovery_year: Optional[str] = None
    discovery_year_num: Optional[int] = None
    date_precision: Optional[str] = None
    biology_notes: Optional[str] = None
    latitude: float
    longitude: float
    source_url: Optional[str]
    created_at: Optional[datetime]
    chess_count: int = 0
    chess_species: list[dict] = []


def _tolerance(z: int, layer: "SpatialLayer | None" = None) -> float:
    """Simplification tolerance in Web Mercator metres for a given zoom level."""
    base = 40075016.68 / (256 * (1 << z))
    return base * _SIMPLIFY_SCALE.get(layer, 2.0)   # type: ignore[arg-type]


# Per-layer multiplier for ST_SimplifyPreserveTopology tolerance.
# Default 2.0 was tuned for very dense polygon sets (WDPA, KBAs).
# Smaller values preserve sub-tile features — use for layers with small polygons
# (e.g. lease blocks ≤ 15 km wide that collapse under the default ~10 km tolerance).
_SIMPLIFY_SCALE: dict["SpatialLayer", float] = {
    # offshore_activities: lease blocks are 5–15 km wide; default ~10 km tolerance at z=5
    # collapses them after ST_AsMVTGeom clip. 0.1 → ~490 m at z=5: preserves all
    # BOEM/EMODnet blocks while still giving the simplifier a path faster than raw.
    SpatialLayer.offshore_activities: 0.1,
    # Zone polygons are huge (Colombia ANH 347k km², EMODnet "planned" zones); a
    # larger tolerance is fine — we only need them as a slate background overlay.
    SpatialLayer.offshore_zones: 1.0,
    # ARCADE catchments span 3 km to 500 km wide; the default 2.0× tolerance
    # (~19.5 km at z=4) collapsed small basins and turned elongated ones into
    # degenerate slivers — the "coarse shards + horizontal banding" render bug.
    # 0.1 → ~978 m at z=4, ~244 m at z=6: preserves basin boundaries at every
    # served zoom while still trimming the densest coastlines.
    SpatialLayer.arctic_catchments: 0.1,
}

# Zoom-dependent area floor (km²) for arctic_catchments low-zoom tiles. At z≤4 the
# whole pan-Arctic is in view and ~46k of the 47k basins are sub-pixel — including
# them bloats the z2 tile to ~1 MB. Dropping small basins guts the payload with no
# visible gaps: ≥1000 km² basins (1004 of them) cover 91% of land area, ≥200 cover
# 96%, ≥50 cover 98%. z≥7 serves all basins (raw SQL, no floor).
_ARCTIC_MIN_AREA = {0: 1000.0, 1: 1000.0, 2: 1000.0, 3: 500.0, 4: 200.0, 5: 50.0, 6: 10.0}

def _arctic_min_area(z: int) -> float:
    return _ARCTIC_MIN_AREA.get(z, 0.0)

# Simplify polygons at wider zoom range for large datasets (KBAs, WDPA, footprints)
_SIMPLIFY_THRESHOLD = {
    SpatialLayer.mining_contracts: 0,  # only 1,318 polygons — no simplification needed
    SpatialLayer.mining_footprints: 6,
    SpatialLayer.water_risk: 7,  # 68k polygons — similar to KBAs
    SpatialLayer.offshore_activities: 12,  # apply simplification at ALL zooms; scale=0.1 keeps tolerances tiny (4–245 m) so block shapes are preserved
    SpatialLayer.offshore_zones: 12,
    SpatialLayer.wod_oxygen: -1,  # point layer — no simplification; -1 ensures use_simplified is always False
    SpatialLayer.memento: -1,  # point layer — no simplification
    SpatialLayer.geotraces: -1,  # point layer — no simplification
    SpatialLayer.mosaic: -1,  # point layer — no simplification
    SpatialLayer.arctic_catchments: 6,  # dense low-zoom polygons — simplify at z ≤ 6
}


@router.get(
    "/tiles/{layer}/{z}/{x}/{y}",
    response_class=Response,
    responses={
        200: {"content": {"application/vnd.mapbox-vector-tile": {}}},
        204: {"description": "Empty tile"},
    },
    dependencies=[Depends(get_api_key)],
)
async def mvt_tile(
    layer: SpatialLayer,
    z: Annotated[int, Path(ge=0, le=22)],
    x: Annotated[int, Path(ge=0)],
    y: Annotated[int, Path(ge=0)],
) -> Response:
    TileCoord(z=z, x=x, y=y)

    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")

    # Check LRU cache first
    cache_key = f"{layer.value}/{z}/{x}/{y}"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        if cached is None:
            return _EMPTY_MVT
        return Response(
            content=cached,
            media_type="application/vnd.mapbox-vector-tile",
            headers={"Cache-Control": "public, max-age=86400, stale-while-revalidate=604800"},
        )

    async with _TILE_SEM:
        async with db.pool.acquire() as conn:
            await conn.execute("SET LOCAL statement_timeout = '60s'")
            simplify_max_z = _SIMPLIFY_THRESHOLD.get(layer, 0)
            use_simplified = z <= simplify_max_z

            if layer is SpatialLayer.mining_contracts:
                sql = _MVT_MINING_SIMPLIFIED if use_simplified else _MVT_MINING
            elif layer is SpatialLayer.mining_footprints:
                sql = _MVT_FOOTPRINTS_SIMPLIFIED if use_simplified else _MVT_FOOTPRINTS
            elif layer is SpatialLayer.water_risk:
                sql = _MVT_WATER_RISK_SIMPLIFIED if use_simplified else _MVT_WATER_RISK
            elif layer is SpatialLayer.offshore_activities:
                sql = _MVT_OFFSHORE_SIMPLIFIED if use_simplified else _MVT_OFFSHORE
            elif layer is SpatialLayer.offshore_zones:
                sql = _MVT_OFFSHORE_ZONES_SIMPLIFIED if use_simplified else _MVT_OFFSHORE_ZONES
            elif layer is SpatialLayer.wod_oxygen:
                sql = _MVT_WOD_OXYGEN
            elif layer is SpatialLayer.memento:
                sql = _MVT_MEMENTO
            elif layer is SpatialLayer.geotraces:
                sql = _MVT_GEOTRACES
            elif layer is SpatialLayer.mosaic:
                sql = _MVT_MOSAIC
            elif layer is SpatialLayer.arctic_catchments:
                sql = _MVT_ARCTIC_CATCHMENTS_SIMPLIFIED if use_simplified else _MVT_ARCTIC_CATCHMENTS
            else:
                sql = _MVT_VENTS

            if layer is SpatialLayer.arctic_catchments and use_simplified:
                # simplified arctic SQL takes an extra $5 area-floor param
                args = (z, x, y, _tolerance(z, layer), _arctic_min_area(z))
            elif use_simplified:
                args = (z, x, y, _tolerance(z, layer))
            else:
                args = (z, x, y)
            try:
                tile: bytes | None = await conn.fetchval(sql, *args)
            except asyncpg.QueryCanceledError:
                log.warning("tile timeout — not caching: %s", cache_key)
                return _EMPTY_MVT

    # Cache the result
    _cache_put(cache_key, tile)

    if not tile:
        return _EMPTY_MVT

    return Response(
        content=bytes(tile),
        media_type="application/vnd.mapbox-vector-tile",
        headers={"Cache-Control": "public, max-age=86400, stale-while-revalidate=604800"},
    )


# ── Raster tile endpoints (offshore-activities) ───────────────────────────────


@router.get(
    "/raster/offshore-activities/{z}/{x}/{y}.png",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
    dependencies=[Depends(get_api_key)],
)
async def offshore_raster(
    z: Annotated[int, Path(ge=0, le=14)],
    x: Annotated[int, Path(ge=0)],
    y: Annotated[int, Path(ge=0)],
    types: str | None = None,
    countries: str | None = None,
) -> Response:
    types_list = sorted(t.strip() for t in (types or "").split(",") if t.strip()) or None
    countries_list = sorted(c.strip() for c in (countries or "").split(",") if c.strip()) or None

    # ── Fast path: pre-baked pyramid (unfiltered requests only) ──────────────
    if types_list is None and countries_list is None:
        baked = _baked_path(z, x, y)
        if baked.exists():
            return Response(
                baked.read_bytes(), media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400"},
            )
        # Bake directory for this zoom exists but tile absent → empty tile area.
        # Return transparent 1×1 so deck.gl doesn't retry on every pan.
        if (_BAKED_DIR / str(z)).exists():
            return Response(
                _transparent_png(), media_type="image/png",
                headers={"Cache-Control": "public, max-age=3600"},
            )
        # Bake hasn't run yet — fall through to on-demand rendering below.

    # ── On-demand path: filtered views or pre-bake not yet complete ──────────
    filter_key = (
        f"t={','.join(types_list) if types_list else 'ALL'}"
        f"--c={','.join(countries_list).replace(' ', '_') if countries_list else 'ALL'}"
    )
    cached = _raster_get(z, x, y, filter_key)
    if cached is not None:
        return Response(cached, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})

    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")

    async with _TILE_SEM:
        async with db.pool.acquire() as conn:
            await conn.execute("SET LOCAL statement_timeout = '60s'")
            png = await raster_tiles.render_tile(z, x, y, types_list, conn, countries_list)

    _raster_put(z, x, y, filter_key, png)
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/offshore-activities/countries", dependencies=[Depends(get_api_key)])
async def offshore_activities_countries() -> list[dict]:
    """List distinct sovereigns with feature counts for the country-filter UI."""
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT sovereign, COUNT(*)::int AS count
              FROM offshore_activities
             WHERE sovereign IS NOT NULL
               AND (name IS NOT NULL OR operator IS NOT NULL)
               -- This table is deliberately multi-type. Counting without this
               -- filter mixes oil, gas, wind, mining and CCS into one figure.
               AND activity_type IN ('oil_gas', 'offshore_wind', 'seabed_mining', 'ccs_storage')
             GROUP BY sovereign
             ORDER BY sovereign
            """
        )
    return [{"sovereign": r["sovereign"], "count": r["count"]} for r in rows]


@router.get("/offshore-activities/feature-bboxes", dependencies=[Depends(get_api_key)])
async def offshore_activities_feature_bboxes(
    types: str | None = None,
    countries: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Per-feature bboxes for filter-aware fly-to cycling.
    Ordered by area DESC so the first press lands on the largest block."""
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    types_list = sorted(t.strip() for t in (types or "").split(",") if t.strip()) or None
    countries_list = sorted(c.strip() for c in (countries or "").split(",") if c.strip()) or None
    where = ["(name IS NOT NULL OR operator IS NOT NULL)"]
    params: list = []
    if types_list:
        params.append(types_list)
        where.append(f"activity_type = ANY(${len(params)}::text[])")
    if countries_list:
        params.append(countries_list)
        where.append(f"sovereign = ANY(${len(params)}::text[])")
    params.append(max(1, min(limit, 500)))
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT id,
                       ST_XMin(geom)::float8 AS west,
                       ST_YMin(geom)::float8 AS south,
                       ST_XMax(geom)::float8 AS east,
                       ST_YMax(geom)::float8 AS north
                  FROM offshore_activities
                 WHERE {' AND '.join(where)}
                 ORDER BY ST_Area(geom::geography) DESC
                 LIMIT ${len(params)}""",
            *params,
        )
    return [dict(r) for r in rows]


_OFFSHORE_PANEL_COLUMNS = """
    id, activity_type, name, operator, sovereign, status, source, source_id,
    -- Per-feature registry URL preferred over the generic source-level portal_url.
    -- Sources that expose a per-licence URL: NSTA (URL), Sodir (prlFactPageUrl),
    -- Crown Estate (ODP_Hyperlink), ANH Colombia (URL_MINUTA → contract PDF),
    -- NOPTA (NEATS_Links). Fallback is the row-level portal_url column.
    COALESCE(
        NULLIF(attributes->>'URL',              ''),
        NULLIF(attributes->>'prlFactPageUrl',   ''),
        NULLIF(attributes->>'ODP_Hyperlink',    ''),
        NULLIF(attributes->>'URL_MINUTA',       ''),
        NULLIF(attributes->>'NEATS_Links',      ''),
        portal_url
    )                                                            AS portal_url,
    awarded_date, expires_date,
    ROUND((ST_Area(geom::geography) / 1e6)::numeric, 1)::float8 AS area_km2,
    NULLIF(attributes->>'MED_LAMINA', '')::float8                AS water_depth_m,
    NULLIF(attributes->>'REGION',     '')                        AS water_zone,
    -- Basin / sea area / sub-basin — try multiple source-specific keys.
    COALESCE(
        NULLIF(attributes->>'NOM_BACIA',   ''),     -- ANP Brazil
        NULLIF(attributes->>'BasinName',   ''),     -- NOPTA Australia
        NULLIF(attributes->>'prlMainArea', ''),     -- Sodir Norway (sea area)
        NULLIF(attributes->>'CUENCA_SED',  ''),     -- ANH Colombia
        NULLIF(attributes->>'Location',    '')      -- NZP&M New Zealand
    )                                                            AS basin,
    -- Licensing-round name/number — recurring across sources but with different keys.
    COALESCE(
        NULLIF(attributes->>'RODADA',      ''),     -- ANP Brazil
        NULLIF(attributes->>'Wind_Round',  ''),     -- Crown Estate (England/Wales/NI)
        NULLIF(attributes->>'RNDNO',       ''),     -- NSTA UK petroleum
        NULLIF(attributes->>'SALE_NUMBER', ''),     -- BOEM USA lease sale
        NULLIF(attributes->>'RONDA',       '')      -- CNH Mexico
    )                                                            AS licensing_round,
    COALESCE(
        NULLIF(attributes->>'TITLE_TYPE',  ''),
        NULLIF(attributes->>'PERMIT_TYPE', ''),
        NULLIF(attributes->>'LICTYPE',     '')
    )                                                            AS licence_type,
    -- Licence holder (group/parent), distinct from the working operator. NSTA
    -- exposes both; NOPTA distinguishes title-holder from title-operator.
    COALESCE(
        NULLIF(attributes->>'LICORGGRP', ''),       -- NSTA UK group holder
        NULLIF(attributes->>'LICORG',    ''),       -- NSTA UK primary holder
        NULLIF(attributes->>'TitleHold', '')        -- NOPTA Australia title holder
    )                                                            AS licence_holder,
    ST_AsGeoJSON(geom)::json                                     AS geometry
"""


def _decode_offshore_row(row) -> dict:
    """asyncpg returns json columns as raw strings; parse `geometry` to a dict
    so the FastAPI response is a real GeoJSON object (not a JSON-encoded string)."""
    d = dict(row)
    if isinstance(d.get("geometry"), str):
        d["geometry"] = json.loads(d["geometry"])
    return d


@router.get("/at/offshore-activities", dependencies=[Depends(get_api_key)])
async def offshore_at(lat: float, lon: float) -> dict:
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT {_OFFSHORE_PANEL_COLUMNS}
              FROM offshore_activities
             WHERE ST_Intersects(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326))
               AND (name IS NOT NULL OR operator IS NOT NULL)
             ORDER BY ST_Area(geom) ASC
             LIMIT 1
            """,
            lon, lat,
        )
    if not row:
        raise HTTPException(404, "no feature at point")
    return _decode_offshore_row(row)


@router.get("/offshore-activities/by-id/{feature_id}", dependencies=[Depends(get_api_key)])
async def offshore_by_id(feature_id: int) -> dict:
    """Return panel properties for a single offshore-activity feature by id.
    Used by fly-to cycling to open the popup for the just-flown-to block."""
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_OFFSHORE_PANEL_COLUMNS} FROM offshore_activities WHERE id = $1",
            feature_id,
        )
    if not row:
        raise HTTPException(404, "not found")
    return _decode_offshore_row(row)


# ── Detail endpoints ─────────────────────────────────────────────────────────


@router.get("/feature/mining_contracts/{isa_id}", response_model=MiningContractDetail, dependencies=[Depends(get_api_key)])
async def get_mining_contract(isa_id: str) -> MiningContractDetail:
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                isa_id, contractor_name, resource_type,
                ROUND(area_km2::numeric, 2)::float8 AS area_km2,
                act_date, expiry_date, is_high_risk,
                jurisdiction_text, nearest_eez_country,
                ROUND(nearest_eez_dist_km::numeric, 1)::float8 AS nearest_eez_dist_km,
                nearest_unesco_site,
                ROUND(nearest_unesco_dist_km::numeric, 1)::float8 AS nearest_unesco_dist_km,
                ST_X(ST_Centroid(ST_SetSRID(geom, 4326)))::float8 AS centroid_lon,
                ST_Y(ST_Centroid(ST_SetSRID(geom, 4326)))::float8 AS centroid_lat
            FROM mining_contracts
            WHERE isa_id = $1
            """,
            isa_id,
        )

    if row is None:
        raise HTTPException(404, f"Contract {isa_id!r} not found")

    return MiningContractDetail(**dict(row))


@router.get("/feature/hydrothermal_vents/{vent_id}", response_model=HydrothermalVentDetail, dependencies=[Depends(get_api_key)])
async def get_hydrothermal_vent(vent_id: int) -> HydrothermalVentDetail:
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, status, depth_m, min_depth_m, max_temp_c, temp_category,
                   ocean, region, jurisdiction, tectonic_setting, discovery_year,
                   discovery_year_num, date_precision,
                   biology_notes, latitude, longitude, source_url, created_at,
                   COALESCE(chess_count, 0) AS chess_count,
                   COALESCE(chess_species::text, '[]') AS chess_species_raw
            FROM hydrothermal_vents
            WHERE id = $1
            """,
            vent_id,
        )

    if row is None:
        raise HTTPException(404, f"Vent {vent_id} not found")

    row_dict = dict(row)
    row_dict["chess_species"] = json.loads(row_dict.pop("chess_species_raw", "[]"))
    return HydrothermalVentDetail(**row_dict)


# ── WOD Oxygen Profiles detail endpoint ────────────────────────────────────

@router.get("/wod-oxygen/by-id/{feature_id}", dependencies=[Depends(get_api_key)])
async def wod_oxygen_by_id(feature_id: int):
    """Return full profile row for a single WOD oxygen cast, incl. parsed o2_profile JSONB."""
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, wod_cast_id, lat, lon, profile_date, profile_time, time_precision,
                   decade, cruise, dataset,
                   country, probe_type, max_depth_m, n_levels, o2_profile, o2_units, qc_flag, qc_note
            FROM wod_oxygen_profiles WHERE id = $1
            """,
            feature_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    d = dict(row)
    if isinstance(d.get("o2_profile"), str):
        d["o2_profile"] = json.loads(d["o2_profile"])   # asyncpg returns JSONB as str
    if d.get("profile_date") is not None:
        d["profile_date"] = d["profile_date"].isoformat()
    if d.get("profile_time") is not None:
        d["profile_time"] = d["profile_time"].isoformat()
    return d


# ── MEMENTO cast detail endpoint ─────────────────────────────────────────────

@router.get("/memento/by-id/{cast_id}", dependencies=[Depends(get_api_key)])
async def memento_by_id(cast_id: str):
    """Full cast detail: metadata + ordered per-depth samples (all params + flags)."""
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    async with db.pool.acquire() as conn:
        cast = await conn.fetchrow(
            """SELECT cast_id,set_name,station,sample_time,lat,lon,decade,n_samples,
                      min_depth_m,max_depth_m,has_ch4,has_n2o,ch4_surf,n2o_surf
               FROM memento_casts WHERE cast_id = $1""",
            cast_id,
        )
        if cast is None:
            raise HTTPException(status_code=404, detail="not found")
        samples = await conn.fetch(
            """SELECT depth_m,sample_time,ch4,n2o,n2o_perc,o2,temp,sal,params,
                      ch4_is_atmospheric,n2o_is_atmospheric
               FROM memento_samples WHERE cast_id = $1 ORDER BY depth_m NULLS LAST""",
            cast_id,
        )
    d = dict(cast)
    if d.get("sample_time") is not None:
        d["sample_time"] = d["sample_time"].isoformat()
    out = []
    for s in samples:
        sd = dict(s)
        if isinstance(sd.get("params"), str):
            sd["params"] = json.loads(sd["params"])  # asyncpg returns JSONB as str
        if sd.get("sample_time") is not None:
            sd["sample_time"] = sd["sample_time"].isoformat()
        out.append(sd)
    d["samples"] = out
    return d


# ── GEOTRACES station detail endpoint ────────────────────────────────────────


# Hard cap on the "measurements" list in the by-id response. Cloud Run rejects
# responses over 32 MiB at the proxy — the API logs 200, the browser gets 500,
# and nothing in our own logs looks unhealthy. Measured worst-case: the
# busiest single station carries a few hundred samples x up to ~400 params,
# i.e. low tens of thousands of measurement rows — each row serializes to
# roughly 60-90 bytes of JSON, so this cap keeps the whole response in the
# tens-of-KB to low-MB range, nowhere near the limit. Capped explicitly
# rather than silently, via the "truncated" field below.
_GEOTRACES_MEASUREMENTS_CAP = 20_000


@router.get("/geotraces/by-id/{station_id}", dependencies=[Depends(get_api_key)])
async def geotraces_by_id(station_id: str):
    """Full station detail: metadata + ordered per-depth samples + param units.

    ADDITIVE (2026-09-08): adds "measurements" (the full geotraces_values rows
    per sample) and "params" (the catalogue rows for params present at this
    station) alongside the untouched legacy "station"/"units"/"samples" keys.
    """
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    async with db.pool.acquire() as conn:
        st = await conn.fetchrow(
            # ⛔ sample_time, n_samples and the three depth columns were absent
            # from this SELECT while GeotracesStationPanel read all five. Every
            # one is gated on `!= null` in the panel, so five rows — including
            # the sampling DATE and the depth range — silently rendered nothing
            # on every one of the 3,874 stations. Measured 2026-09-10: all five
            # are 100% populated in the table (bottom_depth_m 99.7%), so this
            # was data we had, stored, and hid. Checks 21e and 24d at once.
            """SELECT station_id, cruise, station, lat, lon, decade,
                      sample_time, n_samples,
                      min_depth_m, max_depth_m, bottom_depth_m,
                      has_mn, has_fe, has_co, has_ni, has_cu,
                      mn_max, fe_max, co_max, ni_max, cu_max
               FROM geotraces_stations WHERE station_id = $1""",
            station_id,
        )
        if st is None:
            raise HTTPException(status_code=404, detail="not found")
        samples = await conn.fetch(
            """SELECT sample_id, geotraces_sample_id, csv_row, depth_m, sample_time,
                      mn_d, fe_d, co_d, ni_d, cu_d,
                      mn_d_qc, fe_d_qc, co_d_qc, ni_d_qc, cu_d_qc, params
               FROM geotraces_samples WHERE station_id = $1 ORDER BY depth_m NULLS LAST""",
            station_id,
        )
        units_rows = await conn.fetch("SELECT param, unit FROM geotraces_param_units")

        # geotraces_values.sample_id is keyed on csv_row (the CSV row ordinal),
        # NOT geotraces_sample_id — that column is empty on 41% of rows and,
        # where present, only 39% of its values are distinct. See DEFECT 1,
        # 2026-09-08 audit, and the comment on geotraces_values in schema/geochem.py.
        csv_rows = [s["csv_row"] for s in samples if s["csv_row"] is not None]
        measurements_by_sample: dict[int, list[dict]] = {}
        params_seen: set[str] = set()
        truncated = False
        if csv_rows:
            value_rows = await conn.fetch(
                """SELECT sample_id, param_code, value, stddev, qc_flag
                   FROM geotraces_values WHERE sample_id = ANY($1::bigint[])
                   ORDER BY sample_id, param_code
                   LIMIT $2""",
                csv_rows,
                _GEOTRACES_MEASUREMENTS_CAP + 1,
            )
            if len(value_rows) > _GEOTRACES_MEASUREMENTS_CAP:
                value_rows = value_rows[:_GEOTRACES_MEASUREMENTS_CAP]
                truncated = True
            for vr in value_rows:
                sid = vr["sample_id"]
                params_seen.add(vr["param_code"])
                measurements_by_sample.setdefault(sid, []).append(
                    {
                        "param_code": vr["param_code"],
                        "value": vr["value"],
                        "stddev": vr["stddev"],
                        "qc_flag": vr["qc_flag"],
                    }
                )
        params_rows = (
            await conn.fetch(
                """SELECT param_code, label, unit, family, n_values
                   FROM geotraces_params WHERE param_code = ANY($1::text[])
                   ORDER BY n_values DESC""",
                list(params_seen),
            )
            if params_seen
            else []
        )
    d = dict(st)
    # asyncpg hands back a datetime; the panel and every JSON consumer want ISO.
    # The per-sample rows below already do this — the station rollup never did,
    # because it was never selected.
    if d.get("sample_time") is not None:
        d["sample_time"] = d["sample_time"].isoformat()
    units = {r["param"]: r["unit"] for r in units_rows}
    out = []
    measurements: dict[str, list[dict]] = {}
    for s in samples:
        sd = dict(s)
        sd.pop("geotraces_sample_id", None)  # informational only, not a key — see schema comment
        csv_row = sd.pop("csv_row", None)
        if isinstance(sd.get("params"), str):
            sd["params"] = json.loads(sd["params"])  # asyncpg returns JSONB as str
        if sd.get("sample_time") is not None:
            sd["sample_time"] = sd["sample_time"].isoformat()
        out.append(sd)
        if csv_row is not None:
            measurements[str(sd["sample_id"])] = measurements_by_sample.get(csv_row, [])
    params = [dict(r) for r in params_rows]
    return {
        "station": d,
        "units": units,
        "samples": out,
        "measurements": measurements,
        "params": params,
        "truncated": truncated,
    }


@router.get("/geotraces/params", dependencies=[Depends(get_api_key)])
async def geotraces_params():
    """Full geotraces_params catalogue, ordered by n_values descending."""
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT param_code, label, unit, family, n_values
               FROM geotraces_params ORDER BY n_values DESC"""
        )
    return {"params": [dict(r) for r in rows]}


# ── MOSAIC core detail endpoint ───────────────────────────────────────────────

@router.get("/mosaic/by-id/{core_id}", dependencies=[Depends(get_api_key)])
async def mosaic_by_id(core_id: int):
    """Full core detail: metadata + ordered depth sections + per-value provenance."""
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    async with db.pool.acquire() as conn:
        core = await conn.fetchrow(
            """SELECT core_id, core_name, latitude, longitude, water_depth_m, sampling_year,
                      decade, sampling_method, research_vessel, seas, eez, longhurst,
                      has_toc, has_tn, has_d13c, has_d14c, toc_surf, tn_surf, d13c_surf, d14c_surf,
                      sampling_date, sampling_month, sampling_day,
                      campaign_name, campaign_start, campaign_end,
                      core_comment, date_precision
               FROM mosaic_cores WHERE core_id = $1""",
            core_id,
        )
        if core is None:
            raise HTTPException(status_code=404, detail="not found")
        samples = await conn.fetch(
            """SELECT sample_id, depth_upper_cm, depth_bottom_cm, depth_avg_cm, material_analyzed,
                      replicate, toc, tn, d13c, d14c, fm14c, provenance
               FROM mosaic_samples WHERE core_id = $1 ORDER BY depth_avg_cm NULLS LAST""",
            core_id,
        )
    out = []
    for s in samples:
        sd = dict(s)
        if isinstance(sd.get("provenance"), str):
            sd["provenance"] = json.loads(sd["provenance"])  # asyncpg returns JSONB as str
        out.append(sd)
    return {"core": dict(core), "samples": out}


# ── ARCTIC CATCHMENTS catchment detail endpoint ───────────────────────────────

@router.get("/arctic-catchments/by-id/{gid}", dependencies=[Depends(get_api_key)])
async def arctic_catchments_by_id(gid: int):
    """Full catchment detail: all metadata + params JSONB (lazy-loaded on click)."""
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable")
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT gid, name, stream_order, continent, area_km2, center_lat, center_lon,
                      ocs_mean, oc_tot, runoff_mean, pf_frac, t_2m_mean, params
               FROM arctic_catchments WHERE gid = $1""",
            gid,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="catchment not found")
    d = dict(row)
    if isinstance(d.get("params"), str):
        d["params"] = json.loads(d["params"])  # asyncpg returns JSONB as str
    return d
