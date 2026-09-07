# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
AIS ingestion + live vessel endpoints.

Phase 0 of the vessel-tracking rebuild (replaces the retired GFW
data path). Ingests raw AIS we collect ourselves from AISStream.io
(free WebSocket). This module defines:

  * `ais_vessels`   — identity (MMSI PK, name, flag, type, dimensions)
  * `ais_positions` — time-series positions, weekly partitioned on `ts`
  * `aois`          — areas of interest (ISA concessions, coastal mining)
                      used to derive WebSocket bbox subscriptions
  * endpoints under /v2/vessels/* for the `ais-live` frontend layer

The long-running WebSocket client lives in a sibling script
(`ais_ingestor.py`) and runs as its own systemd service so a transient
FastAPI reload never drops the vessel stream.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

import db
from auth import get_api_key
from sync_log import log_sync as _log_sync

log = logging.getLogger("ais_sync")

router = APIRouter(
    prefix="/v2/vessels",
    tags=["ais"],
    dependencies=[Depends(get_api_key)],
)

AOI_BUFFER_KM = float(os.getenv("AIS_AOI_BUFFER_KM", "25"))
POSITION_RETENTION_DAYS = int(os.getenv("AIS_RETENTION_DAYS", "14"))
FEATURE_AIS_LIVE = os.getenv("FEATURE_AIS_LIVE", "1") == "1"
FEATURE_WIDE_AIS = os.getenv("FEATURE_WIDE_AIS", "1") == "1"

# 30-second TTL cache for /live — AIS data lags ≥30 s from AISStream.io anyway.
# Key: (bbox, max_age_min, limit). Value: (expire_ts, geojson_dict).
_LIVE_CACHE: dict[tuple, tuple[float, dict]] = {}
_LIVE_CACHE_TTL = 30.0

# Macro-basin bboxes covering the world's main shipping corridors. Added to the
# AIS subscription in addition to mining-derived AOIs so coastal vessels are
# visible even when no mining claim is nearby.
# Format: (min_lon, min_lat, max_lon, max_lat)
_MACRO_BBOXES: list[tuple[float, float, float, float]] = [
    (-6.0,  30.0,  37.0,  46.0),    # Mediterranean basin
    ( 32.0,  12.0,  44.0,  31.0),   # Red Sea
    ( 47.0,  23.0,  57.0,  31.0),   # Persian Gulf + Strait of Hormuz
    ( 95.0, -11.0, 120.0,  10.0),   # Malacca / Singapore Strait / Java Sea
    (105.0,  -5.0, 125.0,  25.0),   # South China Sea (expanded coastal coverage)
    (118.0,  20.0, 135.0,  41.0),   # East China Sea + Yellow Sea (expanded)
    (128.0,  30.0, 146.0,  46.0),   # Japan + Korea Strait (expanded)
    (-10.0,  48.0,  32.0,  62.0),   # North Sea + Baltic
    (-90.0,   8.0, -58.0,  32.0),   # Caribbean + Gulf of Mexico
    (-85.0, -60.0, -30.0,  13.0),   # South American Atlantic coast (expanded)
    ( 10.0, -38.0,  52.0,  12.0),   # African east coast + Madagascar
    (-20.0, -20.0,  20.0,  36.0),   # African west coast (Gulf of Guinea)
    (100.0, -46.0, 155.0, -10.0),   # Australia approaches (expanded N/NW)
    (155.0, -46.0,  180.0, 12.0),   # Western Pacific island chain (expanded)
    ( 20.0,  60.0,  180.0, 82.0),   # Arctic / Northern Sea Route (expanded)
]

_aoi_bbox_cache: list[tuple[float, float, float, float]] | None = None
_live_cache: str | None = None
_live_cache_ts: datetime | None = None


# ── Schema ────────────────────────────────────────────────────────────────────

async def ensure_ais_schema() -> None:
    """Idempotent. Safe to call on every boot."""
    async with db.pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ais_vessels (
                mmsi          BIGINT PRIMARY KEY,
                name          TEXT,
                callsign      TEXT,
                imo           BIGINT,
                flag          TEXT,         -- ISO 3166-1 alpha-2 derived from MMSI MID
                ship_type     SMALLINT,     -- AIS ITU-R M.1371 type code
                length_m      REAL,
                width_m       REAL,
                draught_m     REAL,
                destination   TEXT,
                eta           TIMESTAMPTZ,
                first_seen    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_seen     TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_ais_vessels_last_seen
                ON ais_vessels (last_seen DESC);
            CREATE INDEX IF NOT EXISTS idx_ais_vessels_flag
                ON ais_vessels (flag);
            """
        )

        # Partitioned positions table. Declarative weekly range partitions on ts.
        # Position stored as lon/lat columns + PostGIS geography for spatial queries.
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ais_positions (
                mmsi        BIGINT NOT NULL,
                ts          TIMESTAMPTZ NOT NULL,
                lon         DOUBLE PRECISION NOT NULL,
                lat         DOUBLE PRECISION NOT NULL,
                sog_knots   REAL,
                cog_deg     REAL,
                heading_deg SMALLINT,
                nav_status  SMALLINT,
                PRIMARY KEY (mmsi, ts)
            ) PARTITION BY RANGE (ts);
            """
        )

        # Ensure current + next week partitions exist so inserts never land in
        # the "default" partition (which we don't create — writes will fail
        # loudly if partition maintenance stops).
        await _ensure_weekly_partitions(conn, weeks_ahead=2)

        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ais_positions_mmsi_ts
                ON ais_positions (mmsi, ts DESC);
            CREATE INDEX IF NOT EXISTS idx_ais_positions_ts_brin
                ON ais_positions USING BRIN (ts);
            """
        )

        # AOIs drive WebSocket bbox subscriptions. Seeded from existing
        # mining_contracts + mining_footprints tables.
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS aois (
                id         BIGSERIAL PRIMARY KEY,
                name       TEXT NOT NULL,
                kind       TEXT NOT NULL
                           CHECK (kind IN ('isa_concession','coastal_mining','buffer','manual','contractor_watchbox','high_interest_watch')),
                source_id  TEXT,            -- FK-ish pointer to originating row
                geom       GEOGRAPHY(MULTIPOLYGON, 4326) NOT NULL,
                buffer_km  REAL NOT NULL DEFAULT 25,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (kind, source_id)
            );
            CREATE INDEX IF NOT EXISTS idx_aois_geom
                ON aois USING GIST (geom);
            """
        )
        # Migrate older deployments: widen the kind CHECK constraint to allow
        # 'high_interest_watch' (added 2026-04). Idempotent.
        await conn.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'aois_kind_check'
                      AND pg_get_constraintdef(oid) NOT LIKE '%high_interest_watch%'
                ) THEN
                    ALTER TABLE aois DROP CONSTRAINT aois_kind_check;
                    ALTER TABLE aois ADD CONSTRAINT aois_kind_check
                        CHECK (kind IN ('isa_concession','coastal_mining','buffer',
                                        'manual','contractor_watchbox','high_interest_watch'));
                END IF;
            END$$;
            """
        )

    log.info("AIS schema ensured")


async def _ensure_weekly_partitions(conn: asyncpg.Connection, weeks_ahead: int = 2) -> None:
    """Create the partition covering 'now' plus `weeks_ahead` future weeks.

    Partition naming: ais_positions_YYYYWW (ISO week). Range: Monday 00:00 UTC
    inclusive → next Monday 00:00 UTC exclusive.
    """
    now = datetime.now(timezone.utc)
    # Monday of current ISO week
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    for offset in range(-1, weeks_ahead + 1):  # include previous week for late arrivals
        start = monday + timedelta(weeks=offset)
        end = start + timedelta(weeks=1)
        iso_year, iso_week, _ = start.isocalendar()
        name = f"ais_positions_{iso_year}{iso_week:02d}"
        await conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {name}
                PARTITION OF ais_positions
                FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}');
            """
        )


async def drop_expired_partitions() -> int:
    """Drop ais_positions partitions whose end is older than retention window.

    Returns count dropped. Called by a periodic task.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=POSITION_RETENTION_DAYS)
    dropped = 0
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.relname AS name,
                   pg_get_expr(c.relpartbound, c.oid) AS bound
            FROM pg_inherits i
            JOIN pg_class c   ON c.oid = i.inhrelid
            JOIN pg_class p   ON p.oid = i.inhparent
            WHERE p.relname = 'ais_positions'
            """
        )
        for r in rows:
            # bound looks like: FOR VALUES FROM ('2025-12-30 00:00:00+00') TO ('2026-01-06 00:00:00+00')
            bound = r["bound"] or ""
            try:
                end_str = bound.split(" TO ('")[1].rstrip("')")
                end = datetime.fromisoformat(end_str.replace(" ", "T"))
            except (IndexError, ValueError):
                continue
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            if end < cutoff:
                await conn.execute(f'DROP TABLE IF EXISTS "{r["name"]}"')
                dropped += 1
                log.info("Dropped expired AIS partition %s (ended %s)", r["name"], end.isoformat())
    return dropped


# ── AOI seeding ──────────────────────────────────────────────────────────────

async def seed_aois_from_existing_layers() -> int:
    """Populate `aois` from mining_contracts + mining_footprints.

    Called on boot (idempotent via UNIQUE (kind, source_id)). The buffered
    geometries drive which AIS bboxes we subscribe to — vessels outside any
    AOI are ignored, dramatically reducing AISStream volume.

    TODO (user decision): the current selection is "all non-relinquished
    ISA concessions" + "all mining_footprints". If you want to narrow
    further — e.g. only concessions whose expiry_date > today, or only
    footprints larger than some size — edit the WHERE clauses below.
    Over-broad AOIs = more data + more $$ on CDSE later; too narrow =
    missed dark vessels.
    """
    global _aoi_bbox_cache
    _aoi_bbox_cache = None

    inserted = 0
    buffer_m = AOI_BUFFER_KM * 1000.0
    async with db.pool.acquire() as conn:
        # ISA concessions → use contract polygons, buffered
        res = await conn.execute(
            """
            INSERT INTO aois (name, kind, source_id, geom, buffer_km)
            SELECT
                COALESCE(mc.contractor_name, mc.isa_id) AS name,
                'isa_concession' AS kind,
                mc.isa_id::text AS source_id,
                ST_Multi(ST_Buffer(mc.geom::geography, $1)::geometry)::geography(MULTIPOLYGON, 4326) AS geom,
                $2
            FROM mining_contracts mc
            WHERE mc.geom IS NOT NULL
            ON CONFLICT (kind, source_id) DO UPDATE
                SET geom = EXCLUDED.geom, buffer_km = EXCLUDED.buffer_km;
            """,
            buffer_m, AOI_BUFFER_KM,
        )
        inserted += int(res.split()[-1]) if res.startswith("INSERT") else 0

        # Coastal mining footprints (only if table exists — land layers may
        # not be populated on fresh dev DBs)
        exists = await conn.fetchval(
            "SELECT to_regclass('public.mining_footprints')"
        )
        if exists:
            res = await conn.execute(
                """
                INSERT INTO aois (name, kind, source_id, geom, buffer_km)
                SELECT
                    COALESCE(NULLIF(mf.country, ''), 'mining_footprint') || '_' || mf.id::text AS name,
                    'coastal_mining' AS kind,
                    mf.id::text AS source_id,
                    ST_Multi(ST_Buffer(mf.geom::geography, $1)::geometry)::geography(MULTIPOLYGON, 4326) AS geom,
                    $2
                FROM mining_footprints mf
                WHERE mf.geom IS NOT NULL
                  AND ST_DWithin(mf.geom::geography,
                                 ST_GeogFromText('SRID=4326;POINT(0 0)'),
                                 40075000)  -- any coastal footprint; replace if you want sea-adjacent only
                ON CONFLICT (kind, source_id) DO UPDATE
                    SET geom = EXCLUDED.geom, buffer_km = EXCLUDED.buffer_km;
                """,
                buffer_m, AOI_BUFFER_KM,
            )
            inserted += int(res.split()[-1]) if res.startswith("INSERT") else 0

        total = await conn.fetchval("SELECT COUNT(*) FROM aois")
    log.info("AOIs seeded: %d total (buffer %.1f km)", total, AOI_BUFFER_KM)
    return total


async def get_aoi_bboxes() -> list[tuple[float, float, float, float]]:
    """Return bounding boxes (min_lon, min_lat, max_lon, max_lat) for all AOIs.

    AISStream supports up to 50 bboxes per subscription; we merge overlapping
    AOIs into a single bbox when it would otherwise exceed that. Cached until
    AOIs change (call seed_aois_from_existing_layers to refresh).
    """
    global _aoi_bbox_cache
    if _aoi_bbox_cache is not None:
        return _aoi_bbox_cache

    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT ST_XMin(geom::geometry) AS min_lon,
                   ST_YMin(geom::geometry) AS min_lat,
                   ST_XMax(geom::geometry) AS max_lon,
                   ST_YMax(geom::geometry) AS max_lat
            FROM aois
            ORDER BY ST_Area(geom::geography) DESC
            """
        )
    mining_bboxes = [(r["min_lon"], r["min_lat"], r["max_lon"], r["max_lat"]) for r in rows]

    # Union macro-basins first so coastal coverage is guaranteed, then fill
    # remaining slots with the largest mining AOIs.
    macros = list(_MACRO_BBOXES) if FEATURE_WIDE_AIS else []
    cap = 50
    remaining = max(0, cap - len(macros))
    primary = mining_bboxes[:remaining]
    tail = mining_bboxes[remaining:]
    bboxes = macros + primary
    if tail:
        merged = (
            min(b[0] for b in tail), min(b[1] for b in tail),
            max(b[2] for b in tail), max(b[3] for b in tail),
        )
        if len(bboxes) < cap:
            bboxes.append(merged)
        else:
            # Replace the last slot with the tail-union so we lose nothing.
            bboxes[-1] = (
                min(bboxes[-1][0], merged[0]), min(bboxes[-1][1], merged[1]),
                max(bboxes[-1][2], merged[2]), max(bboxes[-1][3], merged[3]),
            )
    _aoi_bbox_cache = bboxes
    log.info(
        "AOI bboxes: %d total (%d macros + %d mining%s)",
        len(bboxes), len(macros), len(primary),
        f", tail-merged {len(tail)}" if tail else "",
    )
    return bboxes


# ── Write helpers (called by ingestor) ───────────────────────────────────────

async def upsert_vessel(conn: asyncpg.Connection, v: dict[str, Any]) -> None:
    """Upsert static vessel identity. Called when we receive ShipStaticData."""
    await conn.execute(
        """
        INSERT INTO ais_vessels (mmsi, name, callsign, imo, flag, ship_type,
                                  length_m, width_m, draught_m, destination, eta,
                                  first_seen, last_seen)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11, NOW(), NOW())
        ON CONFLICT (mmsi) DO UPDATE SET
            name        = COALESCE(EXCLUDED.name, ais_vessels.name),
            callsign    = COALESCE(EXCLUDED.callsign, ais_vessels.callsign),
            imo         = COALESCE(EXCLUDED.imo, ais_vessels.imo),
            flag        = COALESCE(EXCLUDED.flag, ais_vessels.flag),
            ship_type   = COALESCE(EXCLUDED.ship_type, ais_vessels.ship_type),
            length_m    = COALESCE(EXCLUDED.length_m, ais_vessels.length_m),
            width_m     = COALESCE(EXCLUDED.width_m, ais_vessels.width_m),
            draught_m   = COALESCE(EXCLUDED.draught_m, ais_vessels.draught_m),
            destination = COALESCE(EXCLUDED.destination, ais_vessels.destination),
            eta         = COALESCE(EXCLUDED.eta, ais_vessels.eta),
            last_seen   = NOW()
        """,
        v["mmsi"], v.get("name"), v.get("callsign"), v.get("imo"), v.get("flag"),
        v.get("ship_type"), v.get("length_m"), v.get("width_m"), v.get("draught_m"),
        v.get("destination"), v.get("eta"),
    )


async def append_positions(conn: asyncpg.Connection, rows: list[dict[str, Any]]) -> int:
    """Batch-insert positions. ON CONFLICT DO NOTHING — duplicate messages
    from multiple base stations are silently discarded.
    """
    if not rows:
        return 0
    await conn.executemany(
        """
        INSERT INTO ais_positions (mmsi, ts, lon, lat, sog_knots, cog_deg, heading_deg, nav_status)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        ON CONFLICT (mmsi, ts) DO NOTHING
        """,
        [
            (r["mmsi"], r["ts"], r["lon"], r["lat"],
             r.get("sog_knots"), r.get("cog_deg"), r.get("heading_deg"), r.get("nav_status"))
            for r in rows
        ],
    )
    # Also bump last_seen on the vessel (cheap: single UPDATE over distinct MMSIs)
    mmsis = list({r["mmsi"] for r in rows})
    await conn.execute(
        "UPDATE ais_vessels SET last_seen = NOW() WHERE mmsi = ANY($1::bigint[])",
        mmsis,
    )
    return len(rows)


# ── API endpoints ────────────────────────────────────────────────────────────

def _flag_from_mmsi(mmsi: int) -> str | None:
    """Derive ISO country from MMSI MID (first 3 digits of 9-digit MMSI).

    Stub — the real mapping is a 500-row table from ITU. For Phase 0 we
    store whatever AISStream gives us; this helper is here for when we
    backfill from raw positions.
    """
    return None


@router.get("/live")
async def live_vessels(
    bbox: str | None = Query(None, description="min_lon,min_lat,max_lon,max_lat"),
    max_age_min: int = Query(60, ge=1, le=1440),
    limit: int = Query(5000, ge=1, le=20000),
):
    """Recent AIS positions, bbox-filtered.

    Returns latest position per MMSI within `max_age_min` minutes. Joined
    against `ais_vessels` for identity. Intended to back the `ais-live`
    frontend layer — the client requests a bbox matching the viewport and
    only at zoom >= 4 to avoid flooding.
    """
    if not FEATURE_AIS_LIVE:
        return {"type": "FeatureCollection", "features": []}

    if bbox:
        try:
            min_lon, min_lat, max_lon, max_lat = map(float, bbox.split(","))
        except ValueError:
            raise HTTPException(400, "bbox must be 'min_lon,min_lat,max_lon,max_lat'")
    else:
        min_lon, min_lat, max_lon, max_lat = -180.0, -90.0, 180.0, 90.0

    cache_key = (bbox, max_age_min, limit)
    now = time.monotonic()
    if cache_key in _LIVE_CACHE:
        expire_ts, cached_result = _LIVE_CACHE[cache_key]
        if now < expire_ts:
            return cached_result

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_min)
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH latest AS (
                SELECT DISTINCT ON (mmsi)
                    mmsi, ts, lon, lat, sog_knots, cog_deg, heading_deg, nav_status
                FROM ais_positions
                WHERE ts >= $1
                  AND lon BETWEEN $2 AND $4
                  AND lat BETWEEN $3 AND $5
                ORDER BY mmsi, ts DESC
            )
            SELECT l.*, v.name, v.flag, v.ship_type, v.length_m, v.callsign, v.imo,
                   v.destination
            FROM latest l
            LEFT JOIN ais_vessels v USING (mmsi)
            ORDER BY l.ts DESC
            LIMIT $6
            """,
            cutoff, min_lon, min_lat, max_lon, max_lat, limit,
        )

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": {
                "__type": "ais_vessel",
                "mmsi": r["mmsi"],
                "name": r["name"],
                "callsign": r["callsign"],
                "imo": r["imo"],
                "flag": r["flag"],
                "ship_type": r["ship_type"],
                "length_m": r["length_m"],
                "sog_knots": r["sog_knots"],
                "cog_deg": r["cog_deg"],
                "heading_deg": r["heading_deg"],
                "nav_status": r["nav_status"],
                "destination": r["destination"],
                "ts": r["ts"].isoformat() if r["ts"] else None,
            },
        }
        for r in rows
    ]
    result = {"type": "FeatureCollection", "features": features}
    _LIVE_CACHE[cache_key] = (now + _LIVE_CACHE_TTL, result)
    # Evict stale entries to keep dict bounded
    if len(_LIVE_CACHE) > 128:
        stale = [k for k, (exp, _) in _LIVE_CACHE.items() if exp < now]
        for k in stale:
            del _LIVE_CACHE[k]
    return result


@router.get("/{mmsi}")
async def vessel_detail(mmsi: int):
    async with db.pool.acquire() as conn:
        v = await conn.fetchrow(
            "SELECT * FROM ais_vessels WHERE mmsi = $1", mmsi,
        )
    if not v:
        raise HTTPException(404, f"Unknown vessel mmsi={mmsi}")
    return {
        "mmsi": v["mmsi"],
        "name": v["name"],
        "callsign": v["callsign"],
        "imo": v["imo"],
        "flag": v["flag"],
        "ship_type": v["ship_type"],
        "length_m": v["length_m"],
        "width_m": v["width_m"],
        "draught_m": v["draught_m"],
        "destination": v["destination"],
        "eta": v["eta"].isoformat() if v["eta"] else None,
        "first_seen": v["first_seen"].isoformat(),
        "last_seen": v["last_seen"].isoformat(),
    }


@router.get("/{mmsi}/history")
async def vessel_history(
    mmsi: int,
    days: int = Query(30, ge=1, le=90),
    max_points: int = Query(1000, ge=10, le=5000),
):
    """Recent track as a FeatureCollection: one LineString + one Point per sample."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with db.pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM ais_positions WHERE mmsi = $1 AND ts >= $2",
            mmsi, cutoff,
        )
        vessel = await conn.fetchrow(
            "SELECT name, destination FROM ais_vessels WHERE mmsi = $1", mmsi,
        )
        if not total:
            return {
                "type": "FeatureCollection",
                "features": [],
                "properties": {"mmsi": mmsi, "count": 0, "total_points": 0},
            }
        stride = max(1, total // max_points)
        rows = await conn.fetch(
            """
            SELECT lon, lat, ts, sog_knots, cog_deg, heading_deg, nav_status FROM (
                SELECT lon, lat, ts, sog_knots, cog_deg, heading_deg, nav_status,
                       ROW_NUMBER() OVER (ORDER BY ts) AS rn
                FROM ais_positions
                WHERE mmsi = $1 AND ts >= $2
            ) x WHERE rn % $3 = 0 ORDER BY ts
            """,
            mmsi, cutoff, stride,
        )

    coords = [[r["lon"], r["lat"]] for r in rows]
    name = vessel["name"] if vessel else None
    destination = vessel["destination"] if vessel else None

    features: list[dict] = [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "kind": "track",
                "mmsi": mmsi,
                "name": name,
                "count": len(coords),
            },
        }
    ]
    for i, r in enumerate(rows):
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": {
                "kind": "point",
                "mmsi": mmsi,
                "name": name,
                "index": i,
                "ts": r["ts"].isoformat() if r["ts"] else None,
                "sog_knots": r["sog_knots"],
                "cog_deg": r["cog_deg"],
                "heading_deg": r["heading_deg"],
                "nav_status": r["nav_status"],
                "destination": destination,
            },
        })
    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "mmsi": mmsi,
            "name": name,
            "count": len(coords),
            "total_points": total,
            "from": cutoff.isoformat(),
        },
    }


@router.get("/aois/bboxes")
async def aoi_bboxes():
    """Debug endpoint — returns the bboxes the ingestor subscribes to."""
    return {"buffer_km": AOI_BUFFER_KM, "bboxes": await get_aoi_bboxes()}


# ── Sync entrypoint for _SYNC_SOURCES wiring ─────────────────────────────────

async def run_aoi_seed() -> None:
    """Admin-dashboard force-sync target. Refreshes AOIs + logs."""
    await ensure_ais_schema()
    total = await seed_aois_from_existing_layers()
    await _log_sync("ais_aois", total, total)


async def run_partition_maintenance() -> None:
    """Create next week's partition and drop expired ones. Daily."""
    async with db.pool.acquire() as conn:
        await _ensure_weekly_partitions(conn, weeks_ahead=2)
    dropped = await drop_expired_partitions()
    log.info("Partition maintenance: dropped=%d", dropped)
