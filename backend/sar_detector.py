# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Sentinel-1 SAR vessel detection via CDSE (Copernicus Data Space Ecosystem).

Phase 2 of the vessel-tracking rebuild. Replaces the old single-source
GFW feed with an independent, tamper-resistant satellite signal.

Flow per run:
  1. For each AOI of kind='isa_concession', query the CDSE OData Catalog
     for new Sentinel-1 GRD IW VV scenes acquired since the AOI's last
     processed timestamp.
  2. For each new scene × AOI intersection, call the Sentinel Hub
     Process API (hosted on CDSE) with a threshold evalscript over
     sigma0_VV. The mask comes back as a 512×512 PNG — cloud-side
     processing means we never download multi-GB GRD rasters.
  3. Decode the mask, label connected components, convert pixel centroids
     back to lat/lon using the requested bbox, and insert one row per
     detection into ``sar_detections``.

Intentional scope decisions (April 2026):
  - Two AOI kinds only:
      * 'isa_concession'      — fixed polygons from mining_contracts.
      * 'contractor_watchbox' — 10 km buffer around each contractor
        vessel's most recent AIS ping (rebuilt each run).
    Coastal mining_footprint AOIs are excluded — urban/port/refinery
    clutter lights up the sigma0 threshold and produces tens of thousands
    of false positives per coastal scene. The watchbox approach instead
    follows specific vessels we already track, keeping detections
    purposeful and avoiding generic coastal noise.
  - CFAR-lite detection: evalscript returns grayscale sigma0, Python
    applies a per-tile 99.5th-percentile threshold floored at
    CFAR_MIN_ABSOLUTE. Auto-adapts to sea state; calm tiles produce
    nothing instead of firing on noise.
  - Admin-triggered only. No auto-poll yet — we want to watch CDSE
    processing-unit usage before opening the faucet.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import numpy as np
from PIL import Image
from scipy import ndimage

import db

log = logging.getLogger("sar_detector")

# ── Config ────────────────────────────────────────────────────────────────────

CDSE_TOKEN_URL   = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
CDSE_CATALOG_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
SH_PROCESS_URL   = "https://sh.dataspace.copernicus.eu/api/v1/process"

CDSE_CLIENT_ID     = os.getenv("CDSE_CLIENT_ID", "")
CDSE_CLIENT_SECRET = os.getenv("CDSE_CLIENT_SECRET", "")

# Detection tile: 512×512 px at ~40m/px = ~20×20 km. Larger AOIs are split
# into multiple tiles client-side (see split_aoi_into_tiles).
TILE_PX              = 512
TILE_SIDE_DEG        = 0.2                   # ≈ 22 km at the equator
MIN_DETECTION_PIXELS = 3                     # reject single-pixel noise
MAX_DETECTION_PIXELS = 500                   # reject land / platforms
INITIAL_LOOKBACK_DAYS = 14                   # first scene query per AOI

# Contractor vessel watchboxes: bbox around each contractor's most recent AIS
# ping. Buffer must cover realistic vessel drift between the last AIS
# broadcast and the SAR acquisition — at cruising speed (~12 kn ≈ 22 km/h)
# and ±10 min AIS windows, ~10 km is generous.
WATCHBOX_RADIUS_KM       = 10.0
WATCHBOX_AIS_STALENESS_DAYS = 14             # skip contractors idle this long

# Per-run caps so a single admin button press can't DDoS CDSE.
MAX_SCENES_PER_RUN     = 20
MAX_TILES_PER_RUN      = 60
SH_REQUEST_CONCURRENCY = 2


# ── OAuth2 token cache ────────────────────────────────────────────────────────

_token: dict[str, Any] = {"value": None, "expires_at": 0.0}
_token_lock = asyncio.Lock()


async def _get_token(client: httpx.AsyncClient) -> str:
    """Return a cached CDSE OAuth2 bearer token, refreshing 60s before expiry."""
    async with _token_lock:
        if _token["value"] and time.time() < _token["expires_at"] - 60:
            return _token["value"]
        if not CDSE_CLIENT_ID or not CDSE_CLIENT_SECRET:
            raise RuntimeError("CDSE_CLIENT_ID / CDSE_CLIENT_SECRET not set")
        r = await client.post(
            CDSE_TOKEN_URL,
            data={
                "grant_type":    "client_credentials",
                "client_id":     CDSE_CLIENT_ID,
                "client_secret": CDSE_CLIENT_SECRET,
            },
            timeout=30.0,
        )
        r.raise_for_status()
        payload = r.json()
        _token["value"]      = payload["access_token"]
        _token["expires_at"] = time.time() + int(payload.get("expires_in", 3600))
        return _token["value"]


# ── Schema ────────────────────────────────────────────────────────────────────

async def ensure_sar_schema() -> None:
    async with db.pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sar_scenes (
                scene_id      TEXT PRIMARY KEY,
                platform      TEXT NOT NULL,
                acquired_at   TIMESTAMPTZ NOT NULL,
                footprint     GEOGRAPHY(MULTIPOLYGON, 4326),
                processed_at  TIMESTAMPTZ,
                n_detections  INTEGER DEFAULT 0,
                error         TEXT
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sar_scenes_acquired ON sar_scenes (acquired_at DESC)"
        )
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sar_detections (
                id                BIGSERIAL PRIMARY KEY,
                scene_id          TEXT NOT NULL REFERENCES sar_scenes(scene_id) ON DELETE CASCADE,
                acquired_at       TIMESTAMPTZ NOT NULL,
                lon               DOUBLE PRECISION NOT NULL,
                lat               DOUBLE PRECISION NOT NULL,
                geom              GEOMETRY(Point, 4326)
                                  GENERATED ALWAYS AS
                                  (ST_SetSRID(ST_MakePoint(lon, lat), 4326)) STORED,
                confidence        REAL,
                n_pixels          INTEGER,
                aoi_kind          TEXT,
                aoi_source_id     TEXT,
                correlated_at     TIMESTAMPTZ,
                created_at        TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sar_detections_geom ON sar_detections USING GIST (geom)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sar_detections_time ON sar_detections (acquired_at DESC)"
        )
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sar_detections_uncorrelated
                ON sar_detections (acquired_at DESC) WHERE correlated_at IS NULL
        """)
    log.info("SAR schema ensured")


# ── CDSE Catalog (OData) ──────────────────────────────────────────────────────

@dataclass
class Scene:
    scene_id: str                           # CDSE product ID (UUID)
    name:     str                           # granule name e.g. S1A_IW_GRDH_...
    acquired_at: datetime
    footprint_geojson: str | None           # GeoFootprint as JSON string (MultiPolygon)


async def discover_recent_scenes(
    client: httpx.AsyncClient,
    since: datetime,
    page_size: int = 1000,
    max_pages: int = 5,
) -> list[Scene]:
    """One broad CDSE OData query for all Sentinel-1 GRD scenes since `since`.

    Returns up to `page_size * max_pages` scenes. We then intersect each
    scene's footprint against `aois` in PostGIS to pick which AOIs to tile.
    That's vastly cheaper than per-AOI catalog calls (there are ≤few thousand
    S1 scenes/day globally vs 46k AOIs).
    """
    filt = (
        "Collection/Name eq 'SENTINEL-1' "
        "and contains(Name,'_GRD') "
        f"and ContentDate/Start gt {since.isoformat().replace('+00:00', 'Z')}"
    )
    out: list[Scene] = []
    for page in range(max_pages):
        params = {
            "$filter":  filt,
            "$orderby": "ContentDate/Start desc",
            "$top":     str(page_size),
            "$skip":    str(page * page_size),
        }
        r = await client.get(CDSE_CATALOG_URL, params=params, timeout=120.0)
        r.raise_for_status()
        items = r.json().get("value", [])
        if not items:
            break
        for item in items:
            try:
                geo = item.get("GeoFootprint")
                out.append(Scene(
                    scene_id=item["Id"],
                    name=item["Name"],
                    acquired_at=datetime.fromisoformat(
                        item["ContentDate"]["Start"].replace("Z", "+00:00")
                    ),
                    footprint_geojson=(
                        geo if isinstance(geo, str)
                        else (None if geo is None else json.dumps(geo))
                    ),
                ))
            except (KeyError, ValueError):
                continue
        if len(items) < page_size:
            break
    return out


# ── Sentinel Hub Process API (CFAR-lite) ──────────────────────────────────────

# CFAR detection percentile: per-tile threshold = this percentile of pixel
# values. Vessels are always a tiny fraction of ocean pixels, so 99.5 means
# "brightest 0.5% of this tile's ocean" — auto-adapts to sea state, cloudy
# days, coastal glint. Far more robust than a fixed SIGMA0_THRESHOLD.
CFAR_PERCENTILE = 99.5
CFAR_MIN_ABSOLUTE = 60   # UINT8; below this the tile is calm sea — skip.

def _evalscript_for(pol: str) -> str:
    """Return grayscale sigma0 as UINT8 for per-tile CFAR in Python.

    Sentinel Hub pre-validates that requested bands exist on the scene, so we
    must pick VV (for SDV/SSV products) or HH (for SDH/SSH products) per
    request. Pixel value = min(255, sigma0 * 255): VV sigma0 over ocean
    typically sits ~0.01 (calm) to ~0.1 (rough); vessels spike to 0.3-0.8,
    which lands at pixel ≥ ~80.
    """
    return f"""
//VERSION=3
function setup() {{
  return {{
    input: [{{ bands: ["{pol}", "dataMask"] }}],
    output: {{ bands: 1, sampleType: "UINT8" }}
  }};
}}
function evaluatePixel(s) {{
  if (s.dataMask < 1) return [0];
  return [Math.min(255, s.{pol} * 255)];
}}
"""


def _polarization_from_name(scene_name: str) -> str | None:
    """Parse '..._1SDV_...' / '..._1SDH_...' / '..._1SSV_...' / '..._1SSH_...'."""
    parts = scene_name.split("_")
    for p in parts:
        if len(p) == 4 and p.startswith("1S") and p[2] in ("D", "S"):
            tail = p[3]
            if tail == "V":
                return "VV"
            if tail == "H":
                return "HH"
    return None


def _tile_request_body(
    bbox: tuple[float, float, float, float],
    acquired_at: datetime,
    pol: str,
) -> dict:
    """Build a Sentinel Hub Process API request body for one tile."""
    window_from = (acquired_at - timedelta(hours=6)).isoformat().replace("+00:00", "Z")
    window_to   = (acquired_at + timedelta(hours=6)).isoformat().replace("+00:00", "Z")
    return {
        "input": {
            "bounds": {
                "bbox": list(bbox),
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
            },
            "data": [{
                "type": "sentinel-1-grd",
                "dataFilter": {
                    # Tight ±6h window around the specific scene we catalogued —
                    # Sentinel Hub then picks whichever GRD (IW/GRDH over coast,
                    # EW/GRDM over open ocean) matches.
                    "timeRange": {"from": window_from, "to": window_to},
                },
                "processing": {"backCoeff": "SIGMA0_ELLIPSOID"},
            }],
        },
        "output": {
            "width":  TILE_PX,
            "height": TILE_PX,
            "responses": [{
                "identifier": "default",
                "format": {"type": "image/png"},
            }],
        },
        "evalscript": _evalscript_for(pol),
    }


async def _run_tile(
    client: httpx.AsyncClient,
    bbox: tuple[float, float, float, float],
    acquired_at: datetime,
    pol: str,
) -> np.ndarray | None:
    """POST a tile request, return the decoded mask array (or None on failure)."""
    token = await _get_token(client)
    body  = _tile_request_body(bbox, acquired_at, pol)
    r = await client.post(
        SH_PROCESS_URL,
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=120.0,
    )
    if r.status_code != 200:
        log.warning("SH Process API %d for bbox=%s: %s",
                    r.status_code, bbox, r.text[:200])
        return None
    img = Image.open(io.BytesIO(r.content)).convert("L")
    return np.asarray(img, dtype=np.uint8)


def _mask_to_detections(
    mask: np.ndarray,
    bbox: tuple[float, float, float, float],
) -> list[dict]:
    """Apply per-tile CFAR threshold, label blobs, return centroid lat/lon.

    Per-tile adaptive threshold is max(percentile, absolute-floor). The floor
    prevents false positives on glassy calm water where the 99.5th percentile
    could be ~10 (just slightly brighter noise). In that case the tile is
    legitimately empty and returns nothing.
    """
    min_lon, min_lat, max_lon, max_lat = bbox

    # Ignore zero pixels (no-data / masked) when computing the threshold.
    ocean = mask[mask > 0]
    if ocean.size < 100:
        return []
    tile_threshold = max(
        float(np.percentile(ocean, CFAR_PERCENTILE)),
        float(CFAR_MIN_ABSOLUTE),
    )
    binary = mask >= tile_threshold

    labeled, n = ndimage.label(binary)
    if n == 0:
        return []
    sizes = ndimage.sum_labels(binary, labeled, index=range(1, n + 1))
    centroids = ndimage.center_of_mass(binary, labeled, index=range(1, n + 1))

    h, w = mask.shape
    detections: list[dict] = []
    for i, (py, px) in enumerate(centroids):
        n_pix = int(sizes[i])
        if n_pix < MIN_DETECTION_PIXELS or n_pix > MAX_DETECTION_PIXELS:
            continue
        # PNG origin is top-left; lat decreases as row increases
        frac_x = px / max(w - 1, 1)
        frac_y = py / max(h - 1, 1)
        lon = min_lon + frac_x * (max_lon - min_lon)
        lat = max_lat - frac_y * (max_lat - min_lat)
        # Confidence: normalize pixel count into [0,1] where ~10 px = typical
        # fishing vessel at 40 m/px. Cap so a refinery doesn't score 1.0.
        confidence = float(min(1.0, n_pix / 10.0))
        detections.append({
            "lon": lon, "lat": lat,
            "n_pixels": n_pix, "confidence": confidence,
        })
    return detections


def split_aoi_into_tiles(
    bbox: tuple[float, float, float, float],
) -> list[tuple[float, float, float, float]]:
    """Slice an AOI bbox into TILE_SIDE_DEG-square tiles."""
    min_lon, min_lat, max_lon, max_lat = bbox
    tiles: list[tuple[float, float, float, float]] = []
    lat = min_lat
    while lat < max_lat:
        lon = min_lon
        next_lat = min(lat + TILE_SIDE_DEG, max_lat)
        while lon < max_lon:
            next_lon = min(lon + TILE_SIDE_DEG, max_lon)
            tiles.append((lon, lat, next_lon, next_lat))
            lon = next_lon
        lat = next_lat
    return tiles


# ── Top-level orchestration ───────────────────────────────────────────────────

async def seed_contractor_watchboxes(conn) -> int:
    """Rebuild AOIs of kind 'contractor_watchbox' from latest AIS fixes.

    One watchbox per contractor MMSI with an AIS ping inside
    ``WATCHBOX_AIS_STALENESS_DAYS``. Each box is a circular buffer of
    ``WATCHBOX_RADIUS_KM`` around the contractor's most recent ``lon, lat``.

    Rebuilt on every SAR sync so coverage follows the fleet in near-real
    time. Returns the number of watchboxes inserted.
    """
    await conn.execute("DELETE FROM aois WHERE kind = 'contractor_watchbox'")
    # contractor_vessels.mmsi is TEXT; ais_positions.mmsi is BIGINT. Cast
    # for the join. DISTINCT ON picks the freshest ping per contractor.
    rows = await conn.fetch(f"""
        SELECT DISTINCT ON (cv.mmsi)
               cv.mmsi, cv.vessel_name, ap.lon, ap.lat, ap.ts
        FROM contractor_vessels cv
        JOIN ais_positions ap ON ap.mmsi = cv.mmsi::bigint
        WHERE cv.mmsi ~ '^[0-9]+$'
          AND ap.ts > NOW() - INTERVAL '{WATCHBOX_AIS_STALENESS_DAYS} days'
        ORDER BY cv.mmsi, ap.ts DESC
    """)
    if not rows:
        return 0

    inserted = 0
    for r in rows:
        await conn.execute("""
            INSERT INTO aois (name, kind, source_id, geom, buffer_km)
            VALUES ($1, 'contractor_watchbox', $2,
                    ST_Multi(
                        ST_Buffer(
                            ST_SetSRID(ST_MakePoint($3, $4), 4326)::geography,
                            $5 * 1000
                        )::geometry
                    )::geography,
                    $5)
        """,
            f"watchbox:{r['vessel_name']}", f"watchbox_{r['mmsi']}",
            r["lon"], r["lat"], WATCHBOX_RADIUS_KM,
        )
        inserted += 1
    log.info("contractor watchboxes: rebuilt %d", inserted)
    return inserted


# Hand-picked regions where Sentinel-1 IW is routinely acquired AND there is
# active mining / proposed mining / suspected unreported extraction activity.
# Kept deliberately tight to avoid the port/refinery false-positive storm that
# scuttled the wider coastal_mining approach.
# Format: (name, min_lon, min_lat, max_lon, max_lat)
_HIGH_INTEREST_WATCHBOXES: list[tuple[str, float, float, float, float]] = [
    ("indonesia_tin_bangka",     105.0, -4.0, 108.5,  0.0),
    ("png_solwara",              149.0, -5.5, 153.0, -2.0),
    ("norwegian_seabed_zone",      2.0, 68.0,  10.0, 73.0),
    ("cook_islands_eez",        -165.0,-25.0,-155.0,-10.0),
    ("red_sea_atlantis_deep",     37.0, 20.0,  39.0, 22.5),
    ("okinawa_trough",           125.0, 26.0, 128.5, 28.5),
    ("philippines_approaches",   120.0,  5.0, 125.5, 12.0),
    ("gulf_of_thailand",         100.5,  7.0, 103.5, 13.0),
]


async def seed_high_interest_watchboxes(conn) -> int:
    """Rebuild AOIs of kind 'high_interest_watch' from the hand-picked list.

    These are stable, curated SAR watchboxes over regions with active or
    proposed mining where Sentinel-1 IW routinely passes. Seeded idempotently
    on every SAR sync.
    """
    await conn.execute("DELETE FROM aois WHERE kind = 'high_interest_watch'")
    for name, min_lon, min_lat, max_lon, max_lat in _HIGH_INTEREST_WATCHBOXES:
        await conn.execute(
            """
            INSERT INTO aois (name, kind, source_id, geom, buffer_km)
            VALUES ($1, 'high_interest_watch', $2,
                    ST_Multi(ST_MakeEnvelope($3, $4, $5, $6, 4326))::geography, 0)
            """,
            f"watch:{name}", f"watch_{name}",
            min_lon, min_lat, max_lon, max_lat,
        )
    log.info("high-interest watchboxes: rebuilt %d", len(_HIGH_INTEREST_WATCHBOXES))
    return len(_HIGH_INTEREST_WATCHBOXES)


async def _aois_intersecting_footprint(
    conn, footprint_geojson: str,
) -> list[dict]:
    """Return AOIs that intersect the given scene footprint (GeoJSON string).

    ISA concessions only. Coastal mining AOIs overlap urban/industrial
    clutter (ports, refineries, tidal mudflats) which fires the sigma0
    threshold everywhere; one run produced 60k false positives from a
    single coastal scene. Deep-ocean ISA concessions are the actual
    dark-vessel use case for this pipeline.
    """
    rows = await conn.fetch("""
        WITH scene AS (
            SELECT ST_SetSRID(ST_GeomFromGeoJSON($1), 4326) AS g
        )
        SELECT a.kind, a.source_id,
               ST_XMin(ST_Intersection(a.geom::geometry, scene.g)) AS min_lon,
               ST_YMin(ST_Intersection(a.geom::geometry, scene.g)) AS min_lat,
               ST_XMax(ST_Intersection(a.geom::geometry, scene.g)) AS max_lon,
               ST_YMax(ST_Intersection(a.geom::geometry, scene.g)) AS max_lat
        FROM aois a, scene
        WHERE a.kind IN ('isa_concession','contractor_watchbox','high_interest_watch')
          AND a.geom IS NOT NULL
          AND ST_Intersects(a.geom::geometry, scene.g)
        LIMIT 20
    """, footprint_geojson)
    return [dict(r) for r in rows]


async def sync_sar_detections(
    lookback_days: int = INITIAL_LOOKBACK_DAYS,
) -> dict[str, int]:
    """Discover recent S1 scenes, intersect with AOIs, extract detections.

    Architecture:
      1. ONE CDSE catalog query for all recent S1 GRD scenes globally.
      2. For each scene, PostGIS query: which of our AOIs does its
         footprint overlap? (skips if none — most open-ocean scenes miss
         all AOIs entirely.)
      3. For each AOI × scene intersection, tile and call SH Process API.

    Much cheaper than per-AOI catalog calls (there are ~few thousand S1
    scenes/day worldwide vs 46k AOIs, most overlapping nothing).
    """
    summary = {"scenes_found": 0, "scenes_with_aois": 0,
               "scenes_processed": 0, "tiles_processed": 0,
               "detections": 0, "watchboxes": 0}
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    sem   = asyncio.Semaphore(SH_REQUEST_CONCURRENCY)

    # Refresh contractor watchboxes before each run so SAR coverage follows
    # the fleet's last known positions.
    async with db.pool.acquire() as conn:
        summary["watchboxes"] = await seed_contractor_watchboxes(conn)
        summary["high_interest_watch"] = await seed_high_interest_watchboxes(conn)

    async with httpx.AsyncClient(http2=False) as client:
        try:
            scenes = await discover_recent_scenes(client, since)
        except Exception:
            log.exception("CDSE catalog query failed")
            return summary
        summary["scenes_found"] = len(scenes)
        log.info("SAR catalog: %d scenes since %s", len(scenes), since.isoformat())

        tile_count = 0
        for sc in scenes:
            if summary["scenes_processed"] >= MAX_SCENES_PER_RUN:
                break
            if not sc.footprint_geojson:
                continue

            async with db.pool.acquire() as conn:
                existing = await conn.fetchval(
                    "SELECT processed_at FROM sar_scenes WHERE scene_id = $1",
                    sc.scene_id,
                )
                if existing is not None:
                    continue
                try:
                    aoi_hits = await _aois_intersecting_footprint(
                        conn, sc.footprint_geojson,
                    )
                except Exception:
                    log.warning("AOI intersection failed for scene %s", sc.scene_id)
                    continue

            if not aoi_hits:
                continue
            summary["scenes_with_aois"] += 1

            pol = _polarization_from_name(sc.name)
            if pol is None:
                log.warning("scene %s: cannot parse polarization, skipping", sc.name)
                continue

            async with db.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO sar_scenes (scene_id, platform, acquired_at)
                    VALUES ($1, 'SENTINEL-1', $2)
                    ON CONFLICT (scene_id) DO NOTHING
                """, sc.scene_id, sc.acquired_at)

            n_detections_scene = 0
            for aoi in aoi_hits:
                if tile_count >= MAX_TILES_PER_RUN:
                    break
                bbox = (aoi["min_lon"], aoi["min_lat"],
                        aoi["max_lon"], aoi["max_lat"])
                if None in bbox:
                    continue
                tiles = split_aoi_into_tiles(bbox)[:MAX_TILES_PER_RUN - tile_count]
                tile_count += len(tiles)

                async def _process_tile(t: tuple[float, float, float, float]) -> int:
                    async with sem:
                        mask = await _run_tile(client, t, sc.acquired_at, pol)
                    if mask is None:
                        return 0
                    dets = _mask_to_detections(mask, t)
                    if not dets:
                        return 0
                    async with db.pool.acquire() as conn2:
                        async with conn2.transaction():
                            for d in dets:
                                await conn2.execute("""
                                    INSERT INTO sar_detections
                                        (scene_id, acquired_at, lon, lat,
                                         confidence, n_pixels,
                                         aoi_kind, aoi_source_id)
                                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                                """,
                                    sc.scene_id, sc.acquired_at,
                                    d["lon"], d["lat"],
                                    d["confidence"], d["n_pixels"],
                                    aoi["kind"], aoi["source_id"],
                                )
                    return len(dets)

                results = await asyncio.gather(
                    *[_process_tile(t) for t in tiles], return_exceptions=True,
                )
                for res in results:
                    if isinstance(res, Exception):
                        log.warning("tile failed: %s", res)
                        continue
                    n_detections_scene += res
                summary["tiles_processed"] += len(tiles)

            async with db.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE sar_scenes
                       SET processed_at = NOW(), n_detections = $2
                     WHERE scene_id = $1
                """, sc.scene_id, n_detections_scene)
            summary["scenes_processed"] += 1
            summary["detections"]       += n_detections_scene
            log.info("scene %s: %d detections across %d AOIs",
                     sc.name, n_detections_scene, len(aoi_hits))

    log.info("SAR sync done: %s", summary)
    return summary
