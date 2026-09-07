# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
SAR × AIS correlator (Phase 3).

For every ``sar_detection`` that hasn't been correlated yet, find the
nearest AIS position within a ±10 min / ±500 m spatiotemporal window
and write one row into ``vessel_events``:

  - match found → classification = 'matched', matched_mmsi + ais_gap_seconds
  - no match    → classification = 'dark'   (vessel visible on SAR but
                                             not broadcasting AIS)
  - ambiguous   → reserved for Phase 4 when Sentinel-2 can't confirm

The correlator is idempotent: it only looks at detections where
``correlated_at IS NULL`` and marks them after writing to vessel_events.
Re-running is safe.
"""
from __future__ import annotations

import hashlib
import logging

import db

log = logging.getLogger("sar_correlator")

MATCH_WINDOW_SECONDS = 10 * 60     # ±10 minutes
MATCH_RADIUS_METERS  = 500         # ±500 m
COVERAGE_RADIUS_METERS  = 50_000   # 50 km — "was AIS being received near here?"
COVERAGE_WINDOW_SECONDS = 60 * 60  # ±1 hour
MIN_COVERAGE_NEIGHBORS  = 1        # ≥N other vessels heard ⇒ coverage exists


def classify(has_match: bool, neighbors: int, min_neighbors: int = MIN_COVERAGE_NEIGHBORS) -> str:
    """matched (AIS match) | dark (no match but AIS heard nearby) | ambiguous (no match, no AIS nearby)."""
    if has_match:
        return "matched"
    return "dark" if neighbors >= min_neighbors else "ambiguous"


def _event_id(scene_id: str, det_id: int) -> str:
    """Deterministic, short event_id derived from scene + detection row."""
    h = hashlib.sha1(f"{scene_id}:{det_id}".encode()).hexdigest()[:16]
    return f"sar_{h}"


async def _count_ais_neighbors(conn, lon: float, lat: float, when,
                               radius_m: int = COVERAGE_RADIUS_METERS,
                               window_s: int = COVERAGE_WINDOW_SECONDS) -> int:
    """Distinct other vessels whose AIS was received within radius_m / ±window_s of (lon,lat,when).
    ais_positions has no geom column — geography is built inline, same as the match query."""
    row = await conn.fetchrow("""
        WITH target AS (
            SELECT ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography AS g
        )
        SELECT COUNT(DISTINCT mmsi) AS n
        FROM ais_positions, target
        WHERE ts BETWEEN $3::timestamptz - make_interval(secs => $4)
                     AND $3::timestamptz + make_interval(secs => $4)
          AND ST_DWithin(
                  ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography,
                  target.g,
                  $5
              )
    """, lon, lat, when, window_s, radius_m)
    return int(row["n"] or 0)


async def correlate_sar_detections() -> dict[str, int]:
    """Populate vessel_events for any sar_detections not yet correlated.

    Returns counts: processed, matched, dark.
    """
    summary = {"processed": 0, "matched": 0, "dark": 0, "ambiguous": 0}

    async with db.pool.acquire() as conn:
        # Pull uncorrelated detections in batches of up to 1000. Each admin
        # force-sync run is expected to produce O(10²) detections; 1000 is a
        # generous cap that keeps memory bounded.
        detections = await conn.fetch("""
            SELECT id, scene_id, acquired_at, lon, lat, confidence,
                   aoi_kind, aoi_source_id
            FROM sar_detections
            WHERE correlated_at IS NULL
            ORDER BY acquired_at ASC
            LIMIT 1000
        """)

        for d in detections:
            # ais_positions stores lon/lat columns, not geom — build point
            # geometry inline. The ts BETWEEN bound narrows rows before the
            # geography distance calc so the scan stays cheap.
            match = await conn.fetchrow("""
                WITH target AS (
                    SELECT ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography AS g
                )
                SELECT mmsi, ts,
                       ST_Distance(
                           ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography,
                           target.g
                       ) AS dist_m,
                       EXTRACT(EPOCH FROM ($3::timestamptz - ts)) AS dt_s
                FROM ais_positions, target
                WHERE ts BETWEEN $3::timestamptz - make_interval(secs => $4)
                             AND $3::timestamptz + make_interval(secs => $4)
                  AND ST_DWithin(
                          ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography,
                          target.g,
                          $5
                      )
                ORDER BY ST_Distance(
                    ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography,
                    target.g
                ) ASC
                LIMIT 1
            """,
                d["lon"], d["lat"], d["acquired_at"],
                MATCH_WINDOW_SECONDS, MATCH_RADIUS_METERS,
            )

            if match is not None:
                classification     = "matched"
                matched_mmsi       = int(match["mmsi"])
                ais_gap_seconds    = int(abs(float(match["dt_s"])))
                coverage_neighbors = None
                summary["matched"] += 1
            else:
                try:
                    neighbors = await _count_ais_neighbors(
                        conn, d["lon"], d["lat"], d["acquired_at"])
                except Exception:
                    log.exception("coverage query failed for detection %s — treating as ambiguous", d["id"])
                    neighbors = 0
                classification    = classify(False, neighbors)   # "dark" or "ambiguous"
                matched_mmsi      = None
                ais_gap_seconds   = None
                coverage_neighbors = neighbors
                summary[classification] = summary.get(classification, 0) + 1

            event_id = _event_id(d["scene_id"], int(d["id"]))

            async with conn.transaction():
                await conn.execute("""
                    INSERT INTO vessel_events
                        (event_id, ts, lat, lon, classification,
                         matched_mmsi, ais_gap_seconds, coverage_neighbors,
                         sar_detection_id, inside_polygon_type, inside_polygon_id)
                    VALUES ($1, $2, $3, $4, $5::vessel_event_class,
                            $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (event_id) DO NOTHING
                """,
                    event_id, d["acquired_at"], d["lat"], d["lon"],
                    classification, matched_mmsi, ais_gap_seconds, coverage_neighbors,
                    str(d["id"]), d["aoi_kind"], d["aoi_source_id"],
                )
                await conn.execute(
                    "UPDATE sar_detections SET correlated_at = NOW() WHERE id = $1",
                    d["id"],
                )
            summary["processed"] += 1

    log.info("SAR×AIS correlation done: %s", summary)
    return summary


async def reclassify_dark_events(batch: int = 2000) -> dict[str, int]:
    """One-shot: re-evaluate already-classified 'dark' events against AIS coverage.
    Events whose ts predates the retained AIS window find 0 neighbors → ambiguous
    (coverage unassessable). Idempotent via the coverage_neighbors IS NULL guard."""
    summary = {"processed": 0, "kept_dark": 0, "to_ambiguous": 0}
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT event_id, ts, lat, lon FROM vessel_events
            WHERE classification = 'dark' AND coverage_neighbors IS NULL
            ORDER BY ts ASC
            LIMIT $1
        """, batch)
        for r in rows:
            try:
                neighbors = await _count_ais_neighbors(conn, r["lon"], r["lat"], r["ts"])
            except Exception:
                log.exception("reclassify coverage query failed for %s — ambiguous", r["event_id"])
                neighbors = 0
            new_class = classify(False, neighbors)   # dark or ambiguous
            await conn.execute("""
                UPDATE vessel_events
                SET classification = $2::vessel_event_class, coverage_neighbors = $3
                WHERE event_id = $1
            """, r["event_id"], new_class, neighbors)
            summary["processed"] += 1
            summary["kept_dark" if new_class == "dark" else "to_ambiguous"] += 1
    if summary.get("processed"):
        import vessel_events as _ve
        _ve._vessel_events_cache = None
        log.info("reclassify_dark_events: invalidated _vessel_events_cache")
    log.info("reclassify_dark_events: %s", summary)
    return summary
