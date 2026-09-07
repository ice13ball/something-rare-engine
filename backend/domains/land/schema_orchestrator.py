# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Schema DDL and the cross-family sync orchestrator for land layers,
extracted verbatim from `land_layers.py`.

- `ensure_land_schema` — creates every land-layer table (356 lines of DDL).
  Imported by name from `main.py` (`from land_layers import ... ensure_land_schema
  ...`) and called from `main.py` lifespan after `schema.ensure_schema()`.
  DDL correctness here is provable only by a live boot; this move is a pure
  relocation of the function body (byte-identical), not a re-verification of
  the DDL itself.
- `sync_all_land_sources` — a CROSS-FAMILY orchestrator (same shape as
  `_sync_all_sources`): runs 9 of the ~20 land syncs then
  `land_overlaps.refresh_overlap_views`, and DELIBERATELY omits
  arctic-rivers, permafrost-thaw and all 7 DataCite syncs. That membership
  list is preserved exactly — do not "complete" it.
"""

from __future__ import annotations

import logging

import db
from sync_log import is_sync_paused
from domains.land.extractive import (
    _sync_mining_footprints,
    _sync_kbas,
    _sync_wdpa,
    _sync_tailings,
    _enrich_tailings_from_grid,
    _sync_dams,
)
from domains.land.hazards import (
    _sync_active_fires,
    _sync_air_quality,
    _sync_landslides,
    _sync_water_risk,
)

log = logging.getLogger("land_layers")


# ── Schema ─────────────────────────────────────────────────────────────────

async def ensure_land_schema():
    """Create land-layer tables. Called from main.py lifespan after schema.ensure_schema()."""
    async with db.pool.acquire() as conn:
        # ── Phase 1 ────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS mining_footprints (
                id          SERIAL PRIMARY KEY,
                country     TEXT,
                area_km2    DOUBLE PRECISION,
                ftype       TEXT,
                source      TEXT,
                geom        geometry(MultiPolygon, 4326),
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_mining_footprints_geom ON mining_footprints USING GIST (geom)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS key_biodiversity_areas (
                id          SERIAL PRIMARY KEY,
                site_name   TEXT,
                country     TEXT,
                status      TEXT,
                criteria    TEXT,
                area_km2    DOUBLE PRECISION,
                geom        geometry(MultiPolygon, 4326),
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_kbas_geom ON key_biodiversity_areas USING GIST (geom)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS wdpa (
                id          SERIAL PRIMARY KEY,
                wdpa_id     INTEGER,
                name        TEXT,
                desig       TEXT,
                desig_type  TEXT,
                iucn_cat    TEXT,
                country     TEXT,
                status      TEXT,
                area_km2    DOUBLE PRECISION,
                geom        geometry(MultiPolygon, 4326),
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_wdpa_geom ON wdpa USING GIST (geom)")

        # forest-loss: raster tiles served from GFW — no DB table

        # ── Phase 2 ────────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tailings_dams (
                id              SERIAL PRIMARY KEY,
                dam_name        TEXT,
                mine_name       TEXT,
                country         TEXT,
                dam_type        TEXT,
                height_m        DOUBLE PRECISION,
                volume_m3       DOUBLE PRECISION,
                risk_class      TEXT,
                status          TEXT,
                owner_company   TEXT,
                operator        TEXT,
                construction_year INTEGER,
                hazard_raw      TEXT,
                raise_type      TEXT,
                data_source     TEXT DEFAULT 'wapha',
                geom            geometry(Point, 4326),
                created_at      TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tailings_geom ON tailings_dams USING GIST (geom)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS active_fires (
                id          SERIAL PRIMARY KEY,
                latitude    DOUBLE PRECISION,
                longitude   DOUBLE PRECISION,
                brightness  DOUBLE PRECISION,
                confidence  TEXT,
                frp         DOUBLE PRECISION,
                instrument  TEXT,
                acq_date    DATE,
                geom        geometry(Point, 4326),
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_fires_geom ON active_fires USING GIST (geom)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_fires_date ON active_fires (acq_date)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS air_quality_stations (
                id          SERIAL PRIMARY KEY,
                location_id INTEGER UNIQUE,
                name        TEXT,
                city        TEXT,
                country     TEXT,
                pm25        DOUBLE PRECISION,
                so2         DOUBLE PRECISION,
                no2         DOUBLE PRECISION,
                o3          DOUBLE PRECISION,
                co          DOUBLE PRECISION,
                last_updated TIMESTAMPTZ,
                geom        geometry(Point, 4326),
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_air_quality_geom ON air_quality_stations USING GIST (geom)")

        # Enrich schema — safe to run on populated table
        for col_sql in [
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS locality TEXT",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS timezone TEXT",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS is_mobile BOOLEAN DEFAULT FALSE",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS is_monitor BOOLEAN DEFAULT FALSE",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS provider TEXT",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS owner TEXT",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS datetime_first TIMESTAMPTZ",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS datetime_last TIMESTAMPTZ",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS pm10 DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS bc DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS no DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS nox DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS humidity DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS temperature DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS co2 DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS pm1 DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS pm4 DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS ch4 DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS ufp DOUBLE PRECISION",
            "ALTER TABLE air_quality_stations ADD COLUMN IF NOT EXISTS coverage_pct DOUBLE PRECISION",
        ]:
            await conn.execute(col_sql)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS landslides (
                id           SERIAL PRIMARY KEY,
                event_date   DATE,
                event_type   TEXT,
                country      TEXT,
                location     TEXT,
                fatalities   INTEGER,
                trigger      TEXT,
                source       TEXT,
                geom         geometry(Point, 4326),
                created_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_landslides_geom ON landslides USING GIST (geom)")

        # ── Phase 3 ────────────────────────────────────────────────────
        # surface-water, carbon-flux, soil-carbon: raster tiles — no DB tables

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS dams (
                id          SERIAL PRIMARY KEY,
                dam_name    TEXT,
                river       TEXT,
                country     TEXT,
                height_m    DOUBLE PRECISION,
                purpose     TEXT,
                year_built  INTEGER,
                volume_mcm  DOUBLE PRECISION,
                geom        geometry(Point, 4326),
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_dams_geom ON dams USING GIST (geom)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS water_risk (
                id                   SERIAL PRIMARY KEY,
                string_id            TEXT UNIQUE,
                pfaf_id              BIGINT,
                gid_0                TEXT,
                name_0               TEXT,
                name_1               TEXT,
                area_km2             DOUBLE PRECISION,
                bws_score            DOUBLE PRECISION,
                bws_label            TEXT,
                bwd_score            DOUBLE PRECISION,
                drr_score            DOUBLE PRECISION,
                rfr_score            DOUBLE PRECISION,
                w_awr_min_tot_score  DOUBLE PRECISION,
                w_awr_min_tot_cat    INTEGER,
                w_awr_min_tot_label  TEXT,
                geom                 geometry(MultiPolygon, 4326),
                created_at           TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_water_risk_geom ON water_risk USING GIST (geom)")

        # ── Monitoring density point sources ───────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS wod_profiles (
                id          SERIAL PRIMARY KEY,
                lon         DOUBLE PRECISION NOT NULL,
                lat         DOUBLE PRECISION NOT NULL,
                year        INTEGER,
                dataset     TEXT,
                region      TEXT,
                UNIQUE (lon, lat, year, dataset)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pangaea_records (
                id          SERIAL PRIMARY KEY,
                pangaea_id  TEXT UNIQUE,
                lon         DOUBLE PRECISION NOT NULL,
                lat         DOUBLE PRECISION NOT NULL,
                year        INTEGER,
                title       TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bco_dmo_datasets (
                id         SERIAL PRIMARY KEY,
                doi        TEXT UNIQUE,
                lon        DOUBLE PRECISION NOT NULL,
                lat        DOUBLE PRECISION NOT NULL,
                year       INTEGER,
                title      TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS noaa_datasets (
                id         SERIAL PRIMARY KEY,
                doi        TEXT UNIQUE,
                lon        DOUBLE PRECISION NOT NULL,
                lat        DOUBLE PRECISION NOT NULL,
                year       INTEGER,
                title      TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS obis_seamap_records (
                id         SERIAL PRIMARY KEY,
                lon        DOUBLE PRECISION NOT NULL,
                lat        DOUBLE PRECISION NOT NULL,
                year       INTEGER,
                UNIQUE (lon, lat, year)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ncei_icoads_files (
                id            SERIAL PRIMARY KEY,
                file_path     TEXT UNIQUE,
                lon           DOUBLE PRECISION NOT NULL,
                lat           DOUBLE PRECISION NOT NULL,
                year          INTEGER,
                station_count INTEGER,
                data_types    TEXT[]
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cchdo_stations (
                id         SERIAL PRIMARY KEY,
                expocode   TEXT NOT NULL,
                ship       TEXT,
                country    TEXT,
                year       INTEGER,
                woce_line  TEXT,
                lon        DOUBLE PRECISION NOT NULL,
                lat        DOUBLE PRECISION NOT NULL,
                UNIQUE (expocode, lon, lat)
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_ncei_icoads_year ON ncei_icoads_files(year)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_cchdo_stations_expocode ON cchdo_stations(expocode)")

        # ── Arctic River Stations ──────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS arctic_river_stations (
                station_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                river_name TEXT NOT NULL,
                site_label TEXT,
                lat DOUBLE PRECISION NOT NULL,
                lon DOUBLE PRECISION NOT NULL,
                geom geometry(Point, 4326),
                record_start DATE,
                record_end DATE,
                mean_annual_discharge_km3 DOUBLE PRECISION,
                summary_stats JSONB NOT NULL DEFAULT '{}'::jsonb,
                units JSONB,
                discharge_monthly JSONB,
                biogeochem_monthly JSONB NOT NULL DEFAULT '{}'::jsonb,
                annual_fluxes JSONB,
                citation TEXT,
                CONSTRAINT arctic_river_stations_source_check
                    CHECK (source IN ('arcticgro','pangaea_lena','pangaea_caa'))
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS arctic_river_stations_geom_gix "
            "ON arctic_river_stations USING GIST (geom)"
        )
        # Idempotent CHECK migration so adding future sub-sources never needs a destructive change
        await conn.execute(
            "ALTER TABLE arctic_river_stations "
            "DROP CONSTRAINT IF EXISTS arctic_river_stations_source_check"
        )
        await conn.execute(
            "ALTER TABLE arctic_river_stations ADD CONSTRAINT arctic_river_stations_source_check "
            "CHECK (source IN ('arcticgro','pangaea_lena','pangaea_caa'))"
        )
        # Per-param source units (verbatim from the dataset), added 2026-06 after the
        # ArcticGRO provider flagged that values are mass concentration (mg/L), not molar.
        await conn.execute(
            "ALTER TABLE arctic_river_stations ADD COLUMN IF NOT EXISTS units JSONB"
        )

        # ── Permafrost Thaw Features ───────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS permafrost_thaw_features (
                id SERIAL PRIMARY KEY,
                source TEXT NOT NULL,
                unique_id TEXT NOT NULL,
                feature_name TEXT,
                feature_type TEXT,
                feature_category TEXT,
                thaw_type TEXT,
                data_source_type TEXT,
                authors TEXT,
                source_doi TEXT,
                imagery TEXT,
                lat DOUBLE PRECISION NOT NULL,
                lon DOUBLE PRECISION NOT NULL,
                geom GEOMETRY(Point, 4326),
                synced_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT permafrost_thaw_features_source_check
                    CHECK (source IN ('alaska_webb','arts_panarctic'))
            )
        """)
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS permafrost_thaw_features_src_uid_uidx "
            "ON permafrost_thaw_features (source, unique_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS permafrost_thaw_features_geom_gix "
            "ON permafrost_thaw_features USING GIST (geom)"
        )
        # Idempotent CHECK migration — adding the pan-Arctic ARTS source later needs
        # only 'arts_panarctic' added to this list, no destructive change.
        await conn.execute(
            "ALTER TABLE permafrost_thaw_features "
            "DROP CONSTRAINT IF EXISTS permafrost_thaw_features_source_check"
        )
        await conn.execute(
            "ALTER TABLE permafrost_thaw_features ADD CONSTRAINT permafrost_thaw_features_source_check "
            "CHECK (source IN ('alaska_webb','arts_panarctic'))"
        )
        await conn.execute("ALTER TABLE permafrost_thaw_features OWNER TO abyssal_user")

    log.info("Land layer schema ready")



# ═══════════════════════════════════════════════════════════════════════════
# Sync orchestration — called from main.py
# ═══════════════════════════════════════════════════════════════════════════

async def sync_all_land_sources():
    """Run all land layer syncs sequentially, then refresh overlap views."""
    for name, action, fn in [
        ("mining_footprints", "land-mining", _sync_mining_footprints),
        ("kbas", "land-kbas", _sync_kbas),
        ("wdpa", "land-wdpa", _sync_wdpa),
        ("tailings", "land-tailings", _sync_tailings),
        ("tailings_enrich", "land-tailings-enrich", _enrich_tailings_from_grid),
        ("active_fires", "land-fires", _sync_active_fires),
        ("air_quality", "land-air-quality", _sync_air_quality),
        ("landslides", "land-landslides", _sync_landslides),
        ("dams", "land-dams", _sync_dams),
        ("water_risk", "land-water-risk", _sync_water_risk),
    ]:
        try:
            if await is_sync_paused(action):
                log.info("%s: skipped (paused)", name)
                continue
            await fn()
        except Exception as e:
            log.error("%s sync failed: %s", name, e)

    # Refresh overlap materialized views after all syncs complete
    try:
        from land_overlaps import refresh_overlap_views
        await refresh_overlap_views()
    except Exception as e:
        log.error("Overlap view refresh failed: %s", e)
