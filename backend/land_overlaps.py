# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Overlap analysis: PostGIS spatial intersections between land layers.
Results stored as materialized views, refreshed after each sync cycle.
Endpoints return pre-computed overlap summaries.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

import db
from auth import get_api_key

log = logging.getLogger("land_overlaps")
router = APIRouter(prefix="/v2/overlaps", tags=["overlaps"], dependencies=[Depends(get_api_key)])

# Module-level caches (cleared on refresh)
_tailings_landslides_cache: str | None = None
_mining_fires_cache: str | None = None
_summary_cache: str | None = None


# ── Schema: create materialized views ────────────────────────────────────────

async def ensure_overlap_views():
    """Create materialized views for high-value spatial intersections.
    Called once at startup. Safe to call repeatedly (IF NOT EXISTS)."""
    async with db.pool.acquire() as conn:
        # Stored centroid for mining_footprints — used by the fire-proximity
        # join below. Without this, the planner cannot use a spatial index
        # because ``ST_Centroid(geom)::geography`` is a derived expression
        # recomputed three times per row, which made the matview refresh
        # CPU-bound at ~12 min on 45k × 117k. With the stored column it
        # drops well under a minute.
        await conn.execute("""
            ALTER TABLE mining_footprints
            ADD COLUMN IF NOT EXISTS centroid_geog GEOGRAPHY(POINT, 4326)
            GENERATED ALWAYS AS (ST_Centroid(geom)::geography) STORED
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS mining_footprints_centroid_geog_gix
            ON mining_footprints USING GIST (centroid_geog)
        """)

        # Recreate overlap_mining_fires if its current definition still uses
        # the old ST_Centroid(m.geom) expression. pg_matviews.definition is
        # NULL when the view doesn't exist yet (first install) — needs_rebuild
        # is then NULL → falsy, and CREATE IF NOT EXISTS below handles it.
        needs_rebuild = await conn.fetchval("""
            SELECT definition !~ 'centroid_geog'
            FROM pg_matviews WHERE matviewname = 'overlap_mining_fires'
        """)
        if needs_rebuild:
            await conn.execute("DROP MATERIALIZED VIEW IF EXISTS overlap_mining_fires")

        # Same problem as overlap_mining_fires had: tailings_dams.geom and
        # landslides.geom are GEOMETRY with GIST(geom) indexes, but the matview
        # cast both sides to ::geography at JOIN time, which forces a planner
        # nested loop (~130M comparisons on 11.8k × 11k rows). Refresh took
        # ~3 minutes pegging a CPU. Stored geography columns + GIST index let
        # the planner use an index-only spatial join.
        for tbl in ("tailings_dams", "landslides"):
            await conn.execute(f"""
                ALTER TABLE {tbl}
                ADD COLUMN IF NOT EXISTS geog GEOGRAPHY(POINT, 4326)
                GENERATED ALWAYS AS (geom::geography) STORED
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS {tbl}_geog_gix
                ON {tbl} USING GIST (geog)
            """)
        # ⚠️ `CREATE MATERIALIZED VIEW IF NOT EXISTS` is a no-op against a view
        # that already exists, so an edit to the definition below reaches a
        # fresh database only. Every changed column needs a clause here or
        # production silently keeps the old shape. `risk_class` is the second
        # such clause: the column is no longer written and would read NULL for
        # every row while the view still advertised it.
        # 2026-09-23: hazard_raw/classification_system/mine_name are Global
        # Tailings Portal-derived (withdrawn, see domains/land/common.py) and
        # must not survive in an existing view's definition either.
        needs_rebuild_tl = await conn.fetchval("""
            SELECT definition !~ '\\.geog\\b' OR definition ~ 'risk_class'
                OR definition ~ 'hazard_raw' OR definition ~ 'classification_system'
                OR definition ~ 'mine_name'
            FROM pg_matviews WHERE matviewname = 'overlap_tailings_landslides'
        """)
        if needs_rebuild_tl:
            await conn.execute("DROP MATERIALIZED VIEW IF EXISTS overlap_tailings_landslides")

        # Mining footprints ∩ Key Biodiversity Areas
        await conn.execute("""
            CREATE MATERIALIZED VIEW IF NOT EXISTS overlap_mining_kba AS
            SELECT
                m.id        AS mine_id,
                m.country   AS mine_country,
                m.ftype,
                m.area_km2  AS mine_area_km2,
                k.id        AS kba_id,
                k.site_name,
                k.country   AS kba_country,
                ROUND((ST_Area(ST_Intersection(m.geom, k.geom)::geography) / 1e6)::numeric, 3)
                    AS overlap_km2
            FROM mining_footprints m
            JOIN key_biodiversity_areas k ON ST_Intersects(m.geom, k.geom)
        """)

        # Mining footprints ∩ Protected Areas (WDPA)
        await conn.execute("""
            CREATE MATERIALIZED VIEW IF NOT EXISTS overlap_mining_wdpa AS
            SELECT
                m.id        AS mine_id,
                m.country   AS mine_country,
                m.ftype,
                m.area_km2  AS mine_area_km2,
                w.wdpa_id,
                w.name      AS pa_name,
                w.desig,
                w.iucn_cat,
                w.country   AS pa_country,
                ROUND((ST_Area(ST_Intersection(m.geom, w.geom)::geography) / 1e6)::numeric, 3)
                    AS overlap_km2
            FROM mining_footprints m
            JOIN wdpa w ON ST_Intersects(m.geom, w.geom)
        """)

        # Tailings dams near landslides (10 km proximity).
        # Uses stored ``tailings_dams.geog`` and ``landslides.geog`` GIST
        # indexes — see migration above. Without them this matview took ~3 min
        # CPU-bound; with them, refresh drops to seconds.
        # ⛔ 2026-09-23: `mine_name`, `hazard_raw`, `classification_system` are
        # Global Tailings Portal-derived (withdrawn pending permission — see
        # `domains/land/common.py` TAILINGS_SERVED_WHERE /
        # TAILINGS_PORTAL_COLUMNS) and dropped from this view. `data_source =
        # 'grid'` (Portal-only) rows are excluded from the join entirely.
        await conn.execute("""
            CREATE MATERIALIZED VIEW IF NOT EXISTS overlap_tailings_landslides AS
            SELECT
                t.id          AS tailings_id,
                t.dam_name,
                t.country     AS tailings_country,
                l.id          AS landslide_id,
                l.event_date,
                l.event_type,
                l.country     AS landslide_country,
                ROUND((ST_Distance(t.geog, l.geog) / 1000)::numeric, 2)
                    AS distance_km
            FROM tailings_dams t
            JOIN landslides l ON ST_DWithin(t.geog, l.geog, 10000)
            WHERE t.data_source IS DISTINCT FROM 'grid'
        """)

        # Active fires near mining footprints (25 km proximity).
        # Uses the stored ``mining_footprints.centroid_geog`` GIST index so
        # the join is index-driven rather than a CPU-bound centroid scan.
        await conn.execute("""
            CREATE MATERIALIZED VIEW IF NOT EXISTS overlap_mining_fires AS
            SELECT
                m.id        AS mine_id,
                m.country   AS mine_country,
                m.ftype,
                f.id        AS fire_id,
                f.acq_date,
                f.confidence,
                f.frp,
                ROUND((ST_Distance(m.centroid_geog, f.geom::geography)
                       / 1000)::numeric, 1) AS distance_km
            FROM mining_footprints m
            JOIN active_fires f
              ON ST_DWithin(m.centroid_geog, f.geom::geography, 25000)
        """)

    log.info("Overlap materialized views created (IF NOT EXISTS)")


async def refresh_overlap_views():
    """Refresh all materialized views. Call after sync cycles complete."""
    global _tailings_landslides_cache
    global _mining_fires_cache, _summary_cache

    async with db.pool.acquire() as conn:
        # Cap each refresh at 15 min — prevents runaway queries that hold
        # locks on mining_contracts and block startup DDL
        await conn.execute("SET statement_timeout = '15min'")
        views = [
            "overlap_mining_kba",
            "overlap_mining_wdpa",
            "overlap_tailings_landslides",
            "overlap_mining_fires",
        ]
        refreshed = 0
        for view in views:
            try:
                # Check if source tables have data before refreshing
                await conn.execute(f"REFRESH MATERIALIZED VIEW {view}")
                refreshed += 1
            except Exception as e:
                log.warning("Could not refresh %s: %s", view, e)

    # Clear caches so next API call fetches fresh data
    _tailings_landslides_cache = None
    _mining_fires_cache = None
    _summary_cache = None

    log.info("Overlap views refreshed: %d/%d", refreshed, 4)


# ── API endpoints ────────────────────────────────────────────────────────────

@router.get("/summary")
async def overlap_summary():
    """High-level counts: how many mines overlap KBAs, WDPA, etc."""
    global _summary_cache
    if _summary_cache:
        return Response(content=_summary_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        rows = {}
        for view, label in [
            ("overlap_mining_kba", "mining_in_kba"),
            ("overlap_mining_wdpa", "mining_in_wdpa"),
            ("overlap_tailings_landslides", "tailings_near_landslides"),
            ("overlap_mining_fires", "mining_near_fires"),
        ]:
            try:
                count = await conn.fetchval(f"SELECT COUNT(*) FROM {view}")
                rows[label] = count or 0
            except Exception:
                rows[label] = 0

    import json
    _summary_cache = json.dumps(rows)
    return Response(content=_summary_cache, media_type="application/json")


@router.get("/mining-kba")
async def get_mining_kba_overlaps():
    """410 Gone — the per-site listing republished KBA records.

    Each row carried `kba_id` and `site_name` straight from the World Database
    of Key Biodiversity Areas: their records, reshaped into ours. Withheld
    2026-09-03 pending written permission from the KBA Secretariat.

    The aggregate `mining_in_kba` count on /overlaps/summary stays. A count of
    how many mines intersect a KBA is our own finding about mines; it
    identifies no KBA and reproduces no record.
    """
    raise HTTPException(
        status_code=410,
        detail="Mine/KBA overlap detail is withheld pending written permission "
               "from the KBA Secretariat. The summary count remains available.",
    )


@router.get("/mining-wdpa")
async def get_mining_wdpa_overlaps():
    """410 Gone — the per-site listing republished WDPA records.

    Each row carried `wdpa_id` and `name` straight from the World Database on
    Protected Areas: their records, reshaped into ours. Withheld 2026-09-03
    pending written permission from UNEP-WCMC.

    The aggregate `mining_in_wdpa` count on /overlaps/summary stays. A count of
    how many mines intersect a protected area is our own finding about mines;
    it identifies no protected area and reproduces no record.
    """
    raise HTTPException(
        status_code=410,
        detail="Mine/protected-area overlap detail is withheld pending written "
               "permission from UNEP-WCMC. The summary count remains available.",
    )


@router.get("/tailings-landslides")
async def get_tailings_landslide_proximity():
    """Tailings dams within 10 km of historical landslide events."""
    global _tailings_landslides_cache
    if _tailings_landslides_cache:
        return Response(content=_tailings_landslides_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                "SELECT * FROM overlap_tailings_landslides ORDER BY distance_km LIMIT 200"
            )
        except Exception:
            rows = []

    import json
    result = json.dumps([dict(r) for r in rows], default=str)
    _tailings_landslides_cache = result
    return Response(content=result, media_type="application/json")


@router.get("/mining-fires")
async def get_mining_fire_proximity():
    """Active fires within 25 km of mining footprints."""
    global _mining_fires_cache
    if _mining_fires_cache:
        return Response(content=_mining_fires_cache, media_type="application/json")

    async with db.pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                "SELECT * FROM overlap_mining_fires ORDER BY distance_km LIMIT 5000"
            )
        except Exception:
            rows = []

    import json
    result = json.dumps([dict(r) for r in rows], default=str)
    _mining_fires_cache = result
    return Response(content=result, media_type="application/json")
