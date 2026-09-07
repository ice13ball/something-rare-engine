# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Vessel events: dark-vessel / SAR×AIS correlation layer.

Replaces the retired GFW-based loitering+encounter pipeline. Rows are
produced by the SAR×AIS correlator (Phase 3); this module owns the
storage schema, contractor auto-discovery, and the read API.

Endpoints under /v2/map to match the existing land_layers.py convention.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import Response

import db
from auth import get_api_key
from land_layers import _log_land_sync

log = logging.getLogger("vessel_events")

router = APIRouter(
    prefix="/v2/map",
    tags=["vessel-events"],
    dependencies=[Depends(get_api_key)],
)

# Cleared on any write that changes what the unfiltered query returns.
_vessel_events_cache: str | None = None


# ── Schema ────────────────────────────────────────────────────────────────────

async def ensure_vessel_events_schema() -> None:
    """Ensure post-migration vessel_events + contractor_vessels exist.

    For fresh DBs (e.g. dev reinstall) we create the new shape directly.
    For the live VPS, migrations/0001_retire_gfw.sql has already rewritten
    vessel_events in place, so the CREATE IF NOT EXISTS is a no-op.
    """
    async with db.pool.acquire() as conn:
        await conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'vessel_event_class') THEN
                    CREATE TYPE vessel_event_class AS ENUM ('matched', 'dark', 'ambiguous');
                END IF;
            END$$;
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS vessel_events (
                event_id            TEXT PRIMARY KEY,
                ts                  TIMESTAMPTZ NOT NULL,
                lat                 DOUBLE PRECISION NOT NULL,
                lon                 DOUBLE PRECISION NOT NULL,
                geom                GEOMETRY(Point, 4326)
                                    GENERATED ALWAYS AS
                                    (ST_SetSRID(ST_MakePoint(lon, lat), 4326)) STORED,
                classification      vessel_event_class,
                matched_mmsi        BIGINT,
                ais_gap_seconds     INTEGER,
                sar_detection_id    TEXT,
                s2_thumbnail_url    TEXT,
                inside_polygon_type TEXT,
                inside_polygon_id   TEXT,
                raw                 JSONB
            )
        """)
        await conn.execute(
            "ALTER TABLE vessel_events ADD COLUMN IF NOT EXISTS coverage_neighbors INTEGER"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_vessel_events_geom ON vessel_events USING GIST (geom)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_vessel_events_ts ON vessel_events (ts DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_vessel_events_classification ON vessel_events (classification)")
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_vessel_events_matched_mmsi
                ON vessel_events (matched_mmsi) WHERE matched_mmsi IS NOT NULL
        """)

        # Reap any auto_discover_contractors backends orphaned by a previous
        # SIGKILL. They hold row/index locks on contractor_vessels and will
        # deadlock the CREATE INDEX calls below. Only targets queries that
        # have been running > 5 min so we don't kill a legitimately fast run.
        await conn.execute("""
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE state = 'active'
              AND query ILIKE '%INSERT INTO contractor_vessels%'
              AND query ILIKE '%FROM ais_positions%'
              AND pid <> pg_backend_pid()
              AND query_start < NOW() - INTERVAL '5 minutes'
        """)

        # contractor_vessels — imo/mmsi → ISA contractor mapping.
        # Populated automatically by auto_discover_contractors() from
        # observed AIS loitering inside ISA concessions. No manual CSV.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contractor_vessels (
                imo              TEXT PRIMARY KEY,
                mmsi             TEXT,
                vessel_name      TEXT NOT NULL,
                contractor_name  TEXT NOT NULL,
                contractor_short TEXT,
                role             TEXT,
                source_url       TEXT,
                verified_at      DATE,
                created_at       TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_contractor_vessels_contractor
                ON contractor_vessels (contractor_name)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_contractor_vessels_mmsi
                ON contractor_vessels (mmsi) WHERE mmsi IS NOT NULL
        """)


# ── Contractor auto-discovery ────────────────────────────────────────────────

# Membership rule: any AIS-broadcasting vessel that lingers inside an ISA
# concession polygon for at least this long, within the lookback window, is
# treated as a contractor vessel. 2h filters out transiting cargo cutting
# across CCZ corridors; mining/survey ships routinely loiter for days.
DISCOVERY_LOOKBACK_DAYS = 7   # 30 → 7 in April, briefly 1 on 2026-09-02, then
                              # back to 7 once the real cost was fixed in the
                              # query itself (see the cells/candidates CTEs).
                              # ais_positions carries no spatial index — only
                              # mmsi_ts, the pkey and a BRIN on ts — so the old
                              # query built a geography point for EVERY row in
                              # the window and tested it against 1318 polygons.
                              # Shrinking the window only bought time; three
                              # separate cap increases (15min → 25min → 5min)
                              # never touched the cause.
                              # Measured on production 2026-09-02, same 7d window:
                              #     unfiltered  → 51,900,000 rows → >25 min (capped)
                              #     grid-filtered → 2 candidates  →   51.9 s
# ⛔ Do NOT "fix" the cost here by adding a GIST index on ST_MakePoint(lon, lat).
# Measured 2026-09-02: 78 MB of index per 1M rows → 8.2 GB across the 105M rows
# now in ais_positions, growing ~515 MB/day at the current ingest rate, and
# taxing every insert on a table that takes 6.6M rows/day. It would buy a faster
# answer to a query whose answer is empty:
#     43,045 AIS positions inside the Clarion-Clipperton bbox over 7 days,
#     0 of them within 100 km of any ISA concession, 0 inside one,
#     contractor_vessels empty since at least 2026-08-23.
# The query is correct and the AOIs are sound (0 null, 0 invalid, 6.0M km²).
# Our AIS feed follows shipping lanes; the concessions sit off them on the
# abyssal plain. There is nothing to find yet — so keep this cheap and let it
# report an honest zero until coverage changes.

DISCOVERY_MIN_DURATION  = "2 hours"
# Skip re-discovery if the last run completed within this window.
# Prevents every dev-branch restart (60s poll) from queueing the discovery scan.
MIN_REDISCOVERY_HOURS = 4


async def auto_discover_contractors(force: bool = False) -> int:
    """Populate ``contractor_vessels`` from observed AIS behaviour.

    A vessel is a contractor if its AIS pings spent ≥ DISCOVERY_MIN_DURATION
    inside any ``isa_concession`` AOI within the last
    ``DISCOVERY_LOOKBACK_DAYS``. Contractor attribution is taken from the
    ISA concession polygon the vessel was seen inside (``aois.name`` is the
    ISA contractor_name).

    Schema preserved (IMO PK) so the read API & DetailPanel keep working —
    only the source of rows changes from manual CSV to a SQL discovery query.
    Returns total rows in contractor_vessels after the run.
    """
    if not force:
        async with db.pool.acquire() as conn:
            recent = await conn.fetchval("""
                SELECT last_synced_at > NOW() - INTERVAL '4 hours'
                FROM sync_log WHERE source = 'contractor_vessels'
            """)
        if recent:
            log.info("contractor_vessels: skipping auto-discovery (last run < %dh ago)",
                     MIN_REDISCOVERY_HOURS)
            async with db.pool.acquire() as conn:
                return int(await conn.fetchval(
                    "SELECT COUNT(*) FROM contractor_vessels") or 0)

    global _vessel_events_cache
    async with db.pool.acquire() as conn:
        # The cap keeps a runaway from outliving the service process and holding
        # locks past the next deploy restart. SET LOCAL scopes it to the
        # transaction — the explicit transaction() block is load-bearing here.
        async with conn.transaction():
            # 5-min cap: the 24h window measures 99.6 s in production, so this is
            # ~3x headroom. The old 25-min cap meant a runaway burned 25 minutes
            # of CPU every 6 hours and still failed. Raising the limit is what
            # got us here (15min → 25min → still timing out); this one goes down.
            await conn.execute("SET LOCAL statement_timeout = '5min'")
            # Stitch IMO from ais_vessels static data; fall back to a synthetic
            # 'mmsi:<n>' key for vessels that haven't broadcast Type 5/24 yet,
            # so the discovery still produces a row (IMO can backfill later via
            # the ON CONFLICT update path on the next run).
            result = await conn.execute(f"""
                -- cells: every whole-degree square touched by a concession
                -- bbox, padded one degree out. 1318 polygons collapse to ~511
                -- cells in ~0.5 ms. This is a SUPERSET filter: a point inside a
                -- polygon necessarily falls in one of its bbox cells, so nothing
                -- true is excluded. The padding covers geography great-circle
                -- edges bowing outside the planar bbox (~111 km of slack, far
                -- more than these polygons can bow).
                -- ⚠️ An AOI crossing the antimeridian would span every longitude
                -- here and degrade this to a full scan — still correct, just
                -- slow. None does today (extent is -157.1..160.4).
                -- ⚠️ MATERIALIZED is load-bearing, not decoration. PostgreSQL 12+
                -- inlines CTEs by default, and the planner cannot estimate the
                -- selectivity of floor(lon)/floor(lat) against `cells` — it
                -- guesses ~49M surviving rows against an actual 2, then picks a
                -- sort-based GroupAggregate over that phantom. Measured
                -- 2026-09-02 on the same 7-day window: inlined → >300 s (capped),
                -- materialized → 86 s. Do not remove these two keywords.
                WITH cells AS MATERIALIZED (
                    SELECT DISTINCT gx, gy
                      FROM aois a,
                           LATERAL generate_series(
                               floor(ST_XMin(a.geom::geometry))::int - 1,
                               floor(ST_XMax(a.geom::geometry))::int + 1) gx,
                           LATERAL generate_series(
                               floor(ST_YMin(a.geom::geometry))::int - 1,
                               floor(ST_YMax(a.geom::geometry))::int + 1) gy
                     WHERE a.kind = 'isa_concession'
                ),
                -- Integer equality on floor(lon)/floor(lat) costs nothing per
                -- row, so the expensive geography work below only ever sees the
                -- handful of pings that could plausibly be in a concession.
                -- Measured 2026-09-02: 51.9M rows over 7 days → 2 candidates in
                -- 51.9 s, against >25 min for the unfiltered join.
                candidates AS MATERIALIZED (
                    SELECT ap.mmsi, ap.ts, ap.lon, ap.lat
                      FROM ais_positions ap
                      JOIN cells c
                        ON c.gx = floor(ap.lon)::int
                       AND c.gy = floor(ap.lat)::int
                     WHERE ap.ts > NOW() - INTERVAL '{DISCOVERY_LOOKBACK_DAYS} days'
                ),
                inside AS (
                    SELECT cd.mmsi,
                           MIN(cd.ts) AS first_seen,
                           MAX(cd.ts) AS last_seen,
                           (array_agg(a.name      ORDER BY cd.ts DESC))[1] AS contractor_name,
                           (array_agg(a.source_id ORDER BY cd.ts DESC))[1] AS isa_id
                    FROM candidates cd
                    JOIN aois a
                      ON a.kind = 'isa_concession'
                     AND ST_Intersects(
                            ST_SetSRID(ST_MakePoint(cd.lon, cd.lat), 4326)::geography,
                            a.geom)
                    GROUP BY cd.mmsi
                    HAVING (MAX(cd.ts) - MIN(cd.ts)) > INTERVAL '{DISCOVERY_MIN_DURATION}'
                )
                INSERT INTO contractor_vessels
                    (imo, mmsi, vessel_name, contractor_name, contractor_short,
                     role, source_url, verified_at)
                SELECT
                    COALESCE(av.imo::text, 'mmsi:' || i.mmsi::text)        AS imo,
                    i.mmsi::text                                           AS mmsi,
                    COALESCE(av.name, 'MMSI ' || i.mmsi::text)             AS vessel_name,
                    COALESCE(i.contractor_name, 'Unknown contractor')      AS contractor_name,
                    NULL                                                   AS contractor_short,
                    'auto-discovered (loiter ≥ {DISCOVERY_MIN_DURATION} in ISA concession)' AS role,
                    'isa:' || COALESCE(i.isa_id, '')                       AS source_url,
                    CURRENT_DATE                                           AS verified_at
                FROM inside i
                LEFT JOIN ais_vessels av ON av.mmsi = i.mmsi
                ON CONFLICT (imo) DO UPDATE SET
                    mmsi            = EXCLUDED.mmsi,
                    vessel_name     = EXCLUDED.vessel_name,
                    contractor_name = EXCLUDED.contractor_name,
                    source_url      = EXCLUDED.source_url,
                    verified_at     = EXCLUDED.verified_at
            """)
        # asyncpg returns "INSERT 0 N" for plain INSERT … SELECT
        try:
            inserted_or_updated = int(result.split()[-1])
        except (ValueError, IndexError):
            inserted_or_updated = 0

        total = await conn.fetchval("SELECT COUNT(*) FROM contractor_vessels")

    _vessel_events_cache = None
    log.info("contractor_vessels: auto-discovered touched=%d total=%d",
             inserted_or_updated, total)
    await _log_land_sync("contractor_vessels", inserted_or_updated, int(total or 0))
    return int(total or 0)


# ── SAR×AIS full pipeline (Phase 2 + 3) ───────────────────────────────────────

async def sync_vessel_events_stub() -> int:
    """Run the full SAR×AIS pipeline: discover scenes, detect, correlate.

    Name kept for backwards compat with ``_SYNC_SOURCES`` / admin endpoints;
    despite the historical name this is the real Phase 2+3 entrypoint.

    Sequence:
      1. sar_detector.sync_sar_detections() — CDSE scene discovery + CFAR-lite
         detection for ISA AOIs. Writes to sar_scenes / sar_detections.
      2. sar_correlator.correlate_sar_detections() — joins new detections
         against ais_positions within ±10min / ±500m, writes vessel_events.

    Returns total vessel_events rows inserted this run (matched + dark).
    """
    global _vessel_events_cache
    from sar_detector   import sync_sar_detections, ensure_sar_schema
    from sar_correlator import correlate_sar_detections, reclassify_dark_events
    from sar_confirm    import confirm_recent_events
    from alerts         import alert_new_dark_events

    await ensure_sar_schema()
    # Refresh contractor_vessels from observed loitering BEFORE the detector
    # runs, so seed_contractor_watchboxes inside sync_sar_detections sees
    # the latest fleet. Wrap in try/except: this is enrichment, and a
    # statement_timeout here must not bail the SAR pipeline downstream
    # (without this the wrapper exits before _log_land_sync, and the
    # vessel_events freshness alarm fires even though the pipeline itself
    # was healthy).
    try:
        await auto_discover_contractors()
    except Exception:
        log.exception("auto_discover_contractors failed — continuing with stale contractor_vessels")
    det_summary    = await sync_sar_detections()
    cor_summary    = await correlate_sar_detections()
    reclass_summary = await reclassify_dark_events()
    s2_summary     = await confirm_recent_events()
    alert_summary  = await alert_new_dark_events()
    log.info("vessel_events sync: detector=%s correlator=%s reclass=%s s2=%s alerts=%s",
             det_summary, cor_summary, reclass_summary, s2_summary, alert_summary)

    _vessel_events_cache = None
    inserted = int(cor_summary.get("processed", 0))
    total    = int(det_summary.get("detections", 0))
    await _log_land_sync("vessel_events", inserted, total)
    return inserted


# ── Read endpoints ────────────────────────────────────────────────────────────

@router.get("/vessel-events")
async def get_vessel_events(
    since:            str | None = None,
    until:            str | None = None,
    classification:   str | None = None,  # comma-separated: matched,dark,ambiguous
    dark_only:        bool       = False,
    contractor_only:  bool       = False,
) -> Response:
    """GeoJSON of recent dark-vessel / SAR×AIS events.

    Joins contractor_vessels on matched_mmsi so the frontend can show
    contractor attribution for the AIS side of each correlation.
    """
    global _vessel_events_cache
    params_present = any([since, until, classification, dark_only, contractor_only])
    if _vessel_events_cache is not None and not params_present:
        return Response(content=_vessel_events_cache, media_type="application/json")

    clauses = ["ve.ts > NOW() - INTERVAL '90 days'"]
    params: list = []
    i = 1

    if since:
        clauses.append(f"ve.ts >= ${i}"); params.append(since); i += 1
    if until:
        clauses.append(f"ve.ts <= ${i}"); params.append(until); i += 1
    if dark_only:
        clauses.append("ve.classification = 'dark'")
    elif classification:
        cls = [c.strip() for c in classification.split(",") if c.strip()]
        placeholders = ",".join(f"${j}" for j in range(i, i + len(cls)))
        clauses.append(f"ve.classification::text IN ({placeholders})")
        params.extend(cls); i += len(cls)
    if contractor_only:
        clauses.append("cv.contractor_name IS NOT NULL")

    where = " AND ".join(clauses)
    # contractor_vessels.mmsi is TEXT; matched_mmsi is BIGINT — cast to compare.
    # Joining aois on (kind, source_id) surfaces the AOI's human-readable name
    # so the DetailPanel can show "Inside NORI-D" instead of "Inside isa_concession".
    sql = f"""
        SELECT
            ve.event_id, ve.ts, ve.lat, ve.lon,
            ve.classification::text AS classification,
            ve.matched_mmsi, ve.ais_gap_seconds, ve.coverage_neighbors,
            ve.sar_detection_id, ve.s2_thumbnail_url,
            ve.inside_polygon_type, ve.inside_polygon_id,
            aoi.name AS inside_polygon_name,
            cv.vessel_name, cv.contractor_name, cv.contractor_short,
            cv.role AS contractor_role
        FROM vessel_events ve
        LEFT JOIN contractor_vessels cv
            ON cv.mmsi IS NOT NULL
           AND ve.matched_mmsi IS NOT NULL
           AND cv.mmsi = ve.matched_mmsi::text
        LEFT JOIN aois aoi
            ON aoi.kind = ve.inside_polygon_type
           AND aoi.source_id = ve.inside_polygon_id
        WHERE {where}
        ORDER BY ve.ts DESC
        LIMIT 5000
    """

    async with db.pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    features = []
    for r in rows:
        props = dict(r)
        props["__type"] = "vessel_event"
        if props.get("ts"):
            props["ts"] = props["ts"].isoformat()
        features.append({
            "type":       "Feature",
            "geometry":   {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": props,
        })

    geojson = json.dumps({"type": "FeatureCollection", "features": features})
    if not params_present:
        _vessel_events_cache = geojson
    return Response(content=geojson, media_type="application/json")


@router.get("/vessel-events/{event_id}/thumb.png")
async def get_vessel_event_thumb(event_id: str) -> Response:
    """Serve the Sentinel-2 RGB thumbnail for one vessel_event."""
    # event_id is deterministic 'sar_<16-hex>' from sar_correlator — safe
    # against path traversal, but clamp to that shape anyway.
    if not event_id.startswith("sar_") or len(event_id) > 32 or "/" in event_id:
        return Response(status_code=404)
    from sar_confirm import _thumb_path
    path = _thumb_path(event_id)
    if not path.exists():
        return Response(status_code=404)
    return Response(
        content=path.read_bytes(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/contractors")
async def list_contractors() -> Response:
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT contractor_name, contractor_short
            FROM contractor_vessels
            ORDER BY contractor_name
        """)
    data = [{"name": r["contractor_name"], "short": r["contractor_short"]} for r in rows]
    return Response(content=json.dumps(data), media_type="application/json")
